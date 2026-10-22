'''
Function:
    Modern WebUI backend server for musicdl
Author:
    Zhenchao Jin / Enhanced Modern WebUI
'''
import os
import re
import time
import uuid
import json
import io
import av
import queue
import tempfile
import urllib.parse
import threading
import html
import requests
import json_repair
import concurrent.futures
import socket
import subprocess
from pathlib import Path
from flask import Flask, request, Response, jsonify, send_from_directory, stream_with_context, redirect

from musicdl import musicdl
from musicdl.modules.sources import MusicClientBuilder, BuildMusicClient
from musicdl.modules.utils import SongInfo, SongInfoUtils

requests.packages.urllib3.disable_warnings()

# Directories
HERE = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(HERE, 'static')
DOWNLOAD_DIR = os.environ.get('MUSICDL_DOWNLOAD_DIR', os.path.join(os.getcwd(), 'musicdl_web_downloads'))
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# Sources definition with categories
SUPPORTED_SOURCES = {
    # Platforms in Greater China
    'NeteaseMusicClient':  {'label': '网易云音乐', 'short': '网易云', 'category': '国内主流', 'default': True},
    'QQMusicClient':       {'label': 'QQ 音乐',   'short': 'QQ音乐', 'category': '国内主流', 'default': True},
    'KuwoMusicClient':     {'label': '酷我音乐',   'short': '酷我',   'category': '国内主流', 'default': True},
    'KugouMusicClient':    {'label': '酷狗音乐',   'short': '酷狗',   'category': '国内主流', 'default': True},
    'MiguMusicClient':     {'label': '咪咕音乐',   'short': '咪咕',   'category': '国内主流', 'default': True},
    'BodianMusicClient':   {'label': '波点音乐',   'short': '波点',   'category': '国内主流', 'default': True},
    'SodaMusicClient':     {'label': '汽水音乐',   'short': '汽水',   'category': '国内主流', 'default': False},
    # Aggregators & Free Sources
    'MyFreeMP3MusicClient':{'label': 'MyFreeMP3', 'short': 'MyFreeMP3', 'category': '聚合平台', 'default': False},
    'GequbaoMusicClient':  {'label': '歌曲宝',     'short': '歌曲宝', 'category': '聚合平台', 'default': False},
    'GDStudioMusicClient': {'label': 'GDStudio聚合', 'short': 'GDStudio', 'category': '聚合平台', 'default': False},
    # Global & Indie
    'JamendoMusicClient':  {'label': 'Jamendo',   'short': 'Jamendo', 'category': '海外与独立', 'default': False},
    'SoundCloudMusicClient':{'label': 'SoundCloud', 'short': 'SoundCloud', 'category': '海外与独立', 'default': False},
}

SOURCE_ORDER = list(SUPPORTED_SOURCES.keys())
SEARCH_SIZE_PER_SOURCE = 5
PER_SOURCE_TIMEOUT = 25

RESULT_EXT_TO_MIME = {
    'mp3': 'audio/mpeg',
    'flac': 'audio/flac',
    'wav': 'audio/wav',
    'm4a': 'audio/mp4',
    'aac': 'audio/aac',
    'ape': 'audio/x-ape',
    'ogg': 'audio/ogg',
    'webm': 'audio/webm',
}


# Client Manager
class ClientManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._clients = {}

    def get_client(self, source_name):
        with self._lock:
            if source_name not in self._clients:
                self._clients[source_name] = BuildMusicClient(module_cfg={
                    'type': source_name,
                    'search_size_per_source': SEARCH_SIZE_PER_SOURCE,
                    'disable_print': True,
                    'max_retries': 2,
                })
            return self._clients[source_name]


MANAGER = ClientManager()


# Persistent Track Registry (跨进程/跨服务重启永久保留已注册音源直链与歌词)
REGISTRY_CACHE_FILE = os.path.join(DOWNLOAD_DIR, '.track_registry.json')

class TrackRegistry:
    def __init__(self, cache_file=REGISTRY_CACHE_FILE):
        self._lock = threading.Lock()
        self._save_lock = threading.Lock()
        self._tracks = {}
        self.cache_file = cache_file
        self._load_cache()

    def _load_cache(self):
        if not os.path.exists(self.cache_file):
            return
        try:
            with open(self.cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for token, item in data.items():
                song_dict = item.get('song_info', {})
                song = SongInfo()
                for k, v in song_dict.items():
                    setattr(song, k, v)
                self._tracks[token] = {
                    'song_info': song,
                    'source': item.get('source', ''),
                    'headers': item.get('headers', {}),
                    'cookies': item.get('cookies', {}),
                    'created_at': item.get('created_at', time.time()),
                }
        except Exception:
            pass

    def _save_cache(self):
        threading.Thread(target=self._save_cache_worker, daemon=True).start()

    def _save_cache_worker(self):
        if not self._save_lock.acquire(blocking=False):
            return
        try:
            with self._lock:
                items = list(self._tracks.items())[-2000:]
                data = {}
                for token, item in items:
                    song = item['song_info']
                    song_dict = {
                        'song_name': getattr(song, 'song_name', ''),
                        'singers': getattr(song, 'singers', ''),
                        'album': getattr(song, 'album', ''),
                        'duration': getattr(song, 'duration', ''),
                        'file_size': getattr(song, 'file_size', ''),
                        'ext': getattr(song, 'ext', 'mp3'),
                        'download_url': getattr(song, 'download_url', ''),
                        'lyric': getattr(song, 'lyric', ''),
                        'cover_url': getattr(song, 'cover_url', ''),
                        'source': getattr(song, 'source', item.get('source', '')),
                    }
                    data[token] = {
                        'song_info': song_dict,
                        'source': item['source'],
                        'headers': item['headers'],
                        'cookies': item['cookies'],
                        'created_at': item['created_at'],
                    }
            tmp_file = f"{self.cache_file}.tmp_{os.getpid()}"
            with open(tmp_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp_file, self.cache_file)
        except Exception:
            pass
        finally:
            self._save_lock.release()

    def add(self, song_info: SongInfo, source: str) -> str:
        token = uuid.uuid4().hex[:16]
        client = MANAGER.get_client(source)
        headers = dict(getattr(client, 'default_download_headers', {}) or {})
        headers.update(dict(getattr(song_info, 'default_download_headers', {}) or {}))
        cookies = dict(getattr(client, 'default_download_cookies', {}) or {})
        cookies.update(dict(getattr(song_info, 'default_download_cookies', {}) or {}))
        
        with self._lock:
            self._tracks[token] = {
                'song_info': song_info,
                'source': source,
                'headers': headers,
                'cookies': cookies,
                'created_at': time.time(),
            }
        self._save_cache()
        return token

    def add_batch(self, items: list) -> list:
        """批量注册曲目：内存毫秒级就绪，后台线程异步持久化，彻底消除磁盘IO阻塞"""
        tokens = []
        client_cache = {}
        with self._lock:
            for song_info, source in items:
                token = uuid.uuid4().hex[:16]
                if source not in client_cache:
                    client = MANAGER.get_client(source)
                    client_cache[source] = (
                        dict(getattr(client, 'default_download_headers', {}) or {}),
                        dict(getattr(client, 'default_download_cookies', {}) or {})
                    )
                c_headers, c_cookies = client_cache[source]
                headers = dict(c_headers)
                headers.update(dict(getattr(song_info, 'default_download_headers', {}) or {}))
                cookies = dict(c_cookies)
                cookies.update(dict(getattr(song_info, 'default_download_cookies', {}) or {}))
                self._tracks[token] = {
                    'song_info': song_info,
                    'source': source,
                    'headers': headers,
                    'cookies': cookies,
                    'created_at': time.time(),
                }
                tokens.append(token)
        self._save_cache()
        return tokens

    def get(self, token: str):
        with self._lock:
            return self._tracks.get(token)


REGISTRY = TrackRegistry()


# Download Manager for background tasks
DOWNLOADS = {}
DL_LOCK = threading.Lock()


def detect_real_quality(song_info: SongInfo, source: str) -> dict:
    """按第一性原理与客观源站事实探测真实品质，绝不虚构无损"""
    # 1. 优先检查已经确定的真实 download_url 或真实 ext
    raw_ext = getattr(song_info, 'ext', None)
    ext = str(raw_ext).lower().strip().lstrip('.') if raw_ext else ''
    if ext in {'none', 'null'}:
        ext = ''

    # 从已有直链嗅探实际格式
    download_url = getattr(song_info, 'download_url', '') or ''
    if download_url and isinstance(download_url, str) and download_url.startswith('http'):
        clean_u = download_url.split('?')[0].lower()
        if clean_u.endswith('.flac'):
            ext = 'flac'
        elif clean_u.endswith('.m4a') or clean_u.endswith('.aac'):
            ext = 'm4a'
        elif clean_u.endswith('.wav'):
            ext = 'wav'
        elif clean_u.endswith('.ogg'):
            ext = 'ogg'
        elif clean_u.endswith('.mp3'):
            ext = 'mp3'

    # 若已有明确真实 ext
    if ext:
        if ext in {'flac', 'wav', 'ape', 'alac', 'dsf', 'dff'}:
            return {'ext': ext, 'lossless': True, 'quality_type': 'lossless', 'quality_label': '无损'}
        elif ext in {'m4a', 'aac'}:
            return {'ext': ext, 'lossless': False, 'quality_type': 'hq', 'quality_label': 'HQ'}
        elif ext == 'mp3':
            bitrate = getattr(song_info, 'bitrate', 0) or 0
            if bitrate >= 320000 or bitrate == 320:
                return {'ext': 'mp3', 'lossless': False, 'quality_type': 'hq', 'quality_label': '320K'}
            return {'ext': 'mp3', 'lossless': False, 'quality_type': 'standard', 'quality_label': 'MP3'}
        else:
            return {'ext': ext, 'lossless': False, 'quality_type': 'standard', 'quality_label': ext.upper()}

    # 2. 若尚未嗅探直链（歌单极速导入模式），深入检索源站元数据中的客观指标
    search_data = getattr(song_info, 'raw_data', {}).get('search', {}) if hasattr(song_info, 'raw_data') else {}
    if not isinstance(search_data, dict):
        search_data = {}

    # (A) 网易云源站客观事实判断
    if source == 'NeteaseMusicClient' or '163' in str(source).lower():
        if search_data.get('sq') or search_data.get('hr'):
            return {'ext': 'flac', 'lossless': True, 'quality_type': 'lossless', 'quality_label': '无损'}
        if search_data.get('h'):
            return {'ext': 'mp3', 'lossless': False, 'quality_type': 'hq', 'quality_label': '320K'}
        if search_data.get('l') or search_data.get('m'):
            return {'ext': 'mp3', 'lossless': False, 'quality_type': 'standard', 'quality_label': 'MP3'}

    # (B) QQ 音乐源站客观事实判断
    if source == 'QQMusicClient' or 'qq' in str(source).lower():
        file_info = search_data.get('file', {})
        if not isinstance(file_info, dict):
            file_info = {}
        size_flac = file_info.get('size_flac') or search_data.get('sizeflac') or 0
        size_320 = file_info.get('size_320mp3') or search_data.get('size320') or 0
        size_aac = file_info.get('size_192aac') or file_info.get('size_320aac') or 0
        if size_flac and int(size_flac) > 0:
            return {'ext': 'flac', 'lossless': True, 'quality_type': 'lossless', 'quality_label': '无损'}
        if (size_320 and int(size_320) > 0) or (size_aac and int(size_aac) > 0):
            return {'ext': 'm4a' if size_aac else 'mp3', 'lossless': False, 'quality_type': 'hq', 'quality_label': 'HQ'}
        return {'ext': 'mp3', 'lossless': False, 'quality_type': 'standard', 'quality_label': 'MP3'}

    # (C) 酷我音乐源站客观事实判断
    if source == 'KuwoMusicClient' or 'kuwo' in str(source).lower():
        has_lossless = search_data.get('hasLossless') or search_data.get('haslossless')
        if has_lossless and str(has_lossless) in {'1', 'true', 'True'}:
            return {'ext': 'flac', 'lossless': True, 'quality_type': 'lossless', 'quality_label': '无损'}
        return {'ext': 'mp3', 'lossless': False, 'quality_type': 'standard', 'quality_label': 'MP3'}

    # (D) 酷狗音乐源站客观事实判断
    if source == 'KugouMusicClient' or 'kugou' in str(source).lower():
        sq_hash = search_data.get('sqhash') or search_data.get('SQFileHash')
        if sq_hash:
            return {'ext': 'flac', 'lossless': True, 'quality_type': 'lossless', 'quality_label': '无损'}
        hq_hash = search_data.get('hqhash') or search_data.get('HQFileHash')
        if hq_hash:
            return {'ext': 'mp3', 'lossless': False, 'quality_type': 'hq', 'quality_label': '320K'}
        return {'ext': 'mp3', 'lossless': False, 'quality_type': 'standard', 'quality_label': 'MP3'}

    # (E) 兜底：未探测或无元数据，诚实展示为标准 MP3，绝不无脑设为无损！
    return {'ext': 'mp3', 'lossless': False, 'quality_type': 'standard', 'quality_label': 'MP3'}


def track_to_payload(song_info: SongInfo, token: str, source: str) -> dict:
    source_meta = SUPPORTED_SOURCES.get(source, {})
    q = detect_real_quality(song_info, source)

    raw_lyric = getattr(song_info, 'lyric', None)
    lyric_str = str(raw_lyric).strip() if raw_lyric else ''
    if lyric_str in {'NULL', 'None', 'null'}:
        lyric_str = ''
    # 真实判定：歌词必须是非空有效文本，严禁任何假冒
    has_lyric = bool(lyric_str and len(lyric_str) > 10 and ('[' in lyric_str or '\n' in lyric_str))

    return {
        'token': token,
        'source': source,
        'source_label': source_meta.get('label', source),
        'source_short': source_meta.get('short', source),
        'song_name': str(getattr(song_info, 'song_name', '未知曲目') or '未知曲目'),
        'singers': str(getattr(song_info, 'singers', '未知艺人') or '未知艺人'),
        'album': str(getattr(song_info, 'album', '') or ''),
        'duration': str(getattr(song_info, 'duration', '') or '00:00'),
        'file_size': str(getattr(song_info, 'file_size', '') or ''),
        'ext': q['ext'],
        'lossless': q['lossless'],
        'quality_type': q['quality_type'],
        'quality_label': q['quality_label'],
        'identifier': str(getattr(song_info, 'identifier', '') or ''),
        'cover_url': f'/api/cover/{token}',
        'has_lyric': has_lyric,
        'lyric': lyric_str,
        'download_url': f'/api/stream/{token}?download=1',
        'stream_url': f'/api/stream/{token}',
    }


class _NullProgress:
    def add_task(self, *a, **k): return 0
    def update(self, *a, **k): pass
    def advance(self, *a, **k): pass
    @property
    def tasks(self):
        class _T: total = 0; completed = 0
        return {_: _T() for _ in range(10)}
    def __getattr__(self, _): return lambda *a, **k: None


def _safe_search(client, keyword, url, bucket, progress):
    try:
        client._search(keyword=keyword, search_url=url, request_overrides={},
                       song_infos=bucket, progress=progress)
    except Exception:
        pass


def _drain(buckets, cursors, source, seen, lock, emit):
    emitted = 0
    for i, bucket in enumerate(buckets):
        while cursors[i] < len(bucket):
            song_info = bucket[cursors[i]]
            cursors[i] += 1
            if not isinstance(song_info, SongInfo) or not song_info.with_valid_download_url:
                continue
            with lock:
                dedup_key = f"{song_info.song_name}_{song_info.singers}_{song_info.file_size}"
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
            token = REGISTRY.add(song_info, source)
            emit('result', track_to_payload(song_info, token, source))
            emitted += 1
    return emitted


def search_stream(keyword, sources):
    out = queue.Queue()
    seen = set()
    lock = threading.Lock()
    active_count = {'n': 0}

    def emit(event, data):
        out.put(f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n")

    def run_source(source):
        try:
            client = MANAGER.get_client(source)
            progress = _NullProgress()
            try:
                search_urls = client._constructsearchurls(keyword=keyword, rule={}, request_overrides={})
            except Exception as err:
                emit('source_error', {'source': source, 'message': str(err)})
                return

            buckets = [[] for _ in search_urls]
            threads = []
            for i, url in enumerate(search_urls):
                t = threading.Thread(target=_safe_search, args=(client, keyword, url, buckets[i], progress), daemon=True)
                t.start()
                threads.append(t)

            deadline = time.time() + PER_SOURCE_TIMEOUT
            cursors = [0] * len(buckets)
            count = 0
            while True:
                drained = _drain(buckets, cursors, source, seen, lock, emit)
                count += drained
                alive = any(t.is_alive() for t in threads)
                if not alive or time.time() > deadline:
                    break
                time.sleep(0.1)

            count += _drain(buckets, cursors, source, seen, lock, emit)
            timed_out = any(t.is_alive() for t in threads)
            emit('source_done', {'source': source, 'count': count, 'timed_out': timed_out})
        except Exception as err:
            emit('source_error', {'source': source, 'message': str(err)})
        finally:
            with lock:
                active_count['n'] -= 1
                if active_count['n'] == 0:
                    out.put(None)

    valid_sources = [s for s in sources if s in SUPPORTED_SOURCES]
    if not valid_sources:
        yield 'event: done\ndata: {"count": 0}\n\n'
        return

    active_count['n'] = len(valid_sources)
    for source in valid_sources:
        emit('source_start', {'source': source, 'label': SUPPORTED_SOURCES[source]['label']})
        threading.Thread(target=run_source, args=(source,), daemon=True).start()

    total = 0
    while True:
        msg = out.get()
        if msg is None:
            break
        if msg.startswith('event: result'):
            total += 1
        yield msg
    yield f'event: done\ndata: {{"count": {total}}}\n\n'


# Flask App
app = Flask(__name__, static_folder=None)


@app.route('/')
def index():
    return send_from_directory(STATIC_DIR, 'index.html')


@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory(STATIC_DIR, filename)


@app.route('/api/sources')
def api_sources():
    sources_data = []
    for sid in SOURCE_ORDER:
        info = SUPPORTED_SOURCES[sid]
        sources_data.append({
            'id': sid,
            'label': info['label'],
            'short': info['short'],
            'category': info['category'],
            'default': info['default'],
        })
    return jsonify({'sources': sources_data})


@app.route('/api/search/stream')
def api_search_stream():
    keyword = (request.args.get('q') or '').strip()
    raw_sources = (request.args.get('sources') or '').strip()
    if not keyword:
        return jsonify({'error': '关键词不能为空'}), 400

    if raw_sources:
        sources = [s for s in raw_sources.split(',') if s in SUPPORTED_SOURCES]
    else:
        sources = [s for s in SOURCE_ORDER if SUPPORTED_SOURCES[s]['default']]

    @stream_with_context
    def generate():
        yield 'retry: 10000\n\n'
        for msg in search_stream(keyword, sources):
            yield msg

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


def transcode_audio(input_bytes: bytes, target_format: str = 'mp3') -> bytes:
    target_format = target_format.lower().lstrip('.')
    inp_buffer = io.BytesIO(input_bytes)
    out_buffer = io.BytesIO()

    with av.open(inp_buffer, mode='r') as in_container:
        in_stream = next((s for s in in_container.streams if s.type == 'audio'), None)
        if in_stream is None:
            return input_bytes

        with av.open(out_buffer, mode='w', format=target_format) as out_container:
            codec_name = 'libmp3lame' if target_format == 'mp3' else target_format
            if target_format == 'wav':
                codec_name = 'pcm_s16le'
            elif target_format == 'flac':
                codec_name = 'flac'
            elif target_format in ('m4a', 'aac'):
                codec_name = 'aac'

            codec = av.Codec(codec_name, 'w')
            sample_fmt = codec.audio_formats[0].name if codec.audio_formats else 's16p'

            rate = in_stream.rate or 44100
            if codec.audio_rates and rate not in codec.audio_rates:
                rate = codec.audio_rates[0]

            out_stream = out_container.add_stream(codec_name, rate=rate)
            out_stream.format = sample_fmt
            if target_format == 'mp3':
                out_stream.bit_rate = 320000
            elif target_format in ('m4a', 'aac'):
                out_stream.bit_rate = 256000

            resampler = av.AudioResampler(
                format=sample_fmt,
                layout='stereo',
                rate=rate
            )

            for packet in in_container.demux(in_stream):
                try:
                    for frame in packet.decode():
                        frame.pts = None
                        for resampled_frame in resampler.resample(frame):
                            for out_packet in out_stream.encode(resampled_frame):
                                out_container.mux(out_packet)
                except Exception:
                    continue

            for out_packet in out_stream.encode(None):
                out_container.mux(out_packet)

    return out_buffer.getvalue()


def try_embed_metadata(raw_bytes: bytes, ext: str, song: SongInfo) -> bytes:
    """Attempt to embed lyrics and basic ID3 tags into audio bytes."""
    ext = ext.lower().lstrip('.')
    if not getattr(song, 'lyric', None) and not getattr(song, 'song_name', None):
        return raw_bytes
    try:
        with tempfile.NamedTemporaryFile(suffix=f'.{ext}', delete=False) as tmp:
            tmp.write(raw_bytes)
            tmp_path = Path(tmp.name)
        if not getattr(song, 'lyric', None) and getattr(song, 'song_name', None):
            song.lyric = resolve_fast_lrc(song.song_name, getattr(song, 'singers', ''), getattr(song, 'identifier', None))
        if getattr(song, 'lyric', None):
            SongInfoUtils.embedlyrics(tmp_path, overwrite=True, lyrics_text=str(song.lyric))
        SongInfoUtils.embedbasictags(
            tmp_path, overwrite=False,
            title=str(song.song_name) if song.song_name else None,
            album=str(song.album) if song.album else None,
            artists=[str(song.singers)] if song.singers else None
        )
        with open(tmp_path, 'rb') as f:
            embedded_bytes = f.read()
        tmp_path.unlink(missing_ok=True)
        return embedded_bytes
    except Exception:
        return raw_bytes


def make_content_disposition(filename: str, ext: str = 'mp3') -> str:
    ext = str(ext or 'mp3').lower().strip().lstrip('.')
    if not ext or ext in {'none', 'null'}:
        ext = 'mp3'
    # 彻底清除可能传入的 .none 后缀并确保后缀正确
    if filename.lower().endswith('.none'):
        filename = filename[:-5]
    if not filename.lower().endswith(f".{ext}"):
        filename = f"{filename}.{ext}"

    # 提取纯 ASCII 字符作为老旧客户端兜底名，严禁包含任何非 ASCII 或 Latin-1 范围外的字符
    ascii_clean = re.sub(r'[^a-zA-Z0-9_\.\-]', '_', filename)
    ascii_clean = re.sub(r'_+', '_', ascii_clean).strip('._- ')
    if not ascii_clean or ascii_clean == ext:
        safe_ascii = f"musicdl_audio.{ext}"
    elif not ascii_clean.endswith(f".{ext}"):
        safe_ascii = f"{ascii_clean}.{ext}"
    else:
        safe_ascii = ascii_clean

    encoded_filename = urllib.parse.quote(filename)
    return f'attachment; filename="{safe_ascii}"; filename*=UTF-8\'\'{encoded_filename}'


def resolve_netease_direct_url(song_id):
    """0.1秒获取网易云官方高品质音频直链"""
    if not song_id:
        return None
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://music.163.com/',
    }
    for level in ['standard', 'exhigh']:
        try:
            data = {'ids': json.dumps([int(song_id)]), 'level': level, 'encodeType': 'mp3'}
            resp = requests.post('https://music.163.com/api/song/enhance/player/url/v1', data=data, headers=headers, timeout=(2, 4), verify=False).json()
            items = resp.get('data') or []
            if items and items[0].get('url'):
                return items[0]['url']
        except Exception:
            continue
    return None


def is_singer_match(target_singers, cand_artists, song_name, cand_name):
    """严格比对歌手与过滤翻唱，保证绝不货不对板"""
    raw_name = str(song_name or '').lower()
    c_name = str(cand_name or '').lower()
    # 翻唱与改编一票否决黑名单
    for bad_tag in ['翻唱', 'cover', '改编', 'dj版', '伴奏', 'instrumental']:
        if bad_tag not in raw_name and bad_tag in c_name:
            return False

    if not target_singers:
        return True
    
    # 拆解目标歌手
    raw_singers = re.split(r'[/,、;&\s]+', str(target_singers or '').strip())
    targets = [s.strip().lower() for s in raw_singers if s.strip() and s.strip() not in {'未知歌手', '未知艺人'}]
    if not targets:
        return True

    # 拆解候选歌手
    cands = [str(a or '').strip().lower() for a in cand_artists if str(a or '').strip()]
    if not cands:
        return False

    for t in targets:
        for c in cands:
            if t == c or t in c or c in t:
                return True
    return False


def resolve_kuwo_direct_url(song_name, singers='', song_id=None):
    """通过酷我官方接口获取 CDN 直链（严格歌手匹配，彻底拦截 588957081/563182854 及 <500KB 下架播报假音频）"""
    # 1. 若本身传入了酷我原生 ID（如酷我歌单），直接验证该 ID 直链
    if song_id:
        rid = str(song_id).removeprefix('MUSIC_')
        try:
            play_url_api = f"http://antiserver.kuwo.cn/anti.s?type=convert_url&rid={rid}&format=mp3&response=url"
            play_resp = requests.get(play_url_api, timeout=(2, 3), headers={'User-Agent': 'Mozilla/5.0'})
            res_url = play_resp.text.strip()
            if res_url.startswith('http') and not any(fake_id in res_url for fake_id in ['588957081', '563182854']):
                try:
                    head_resp = requests.head(res_url, timeout=2, headers={'User-Agent': 'Mozilla/5.0'})
                    clen = int(head_resp.headers.get('Content-Length', 0) or 0)
                    if clen == 0 or clen >= 500 * 1024:
                        return res_url
                except Exception:
                    return res_url
        except Exception:
            pass

    if not song_name:
        return None

    s_name, c_singer = clean_music_query(song_name, singers)
    query = f"{s_name} {c_singer}".strip() if c_singer else s_name

    # 2. 搜索并严格遍历候选结果进行歌手与非翻唱匹配
    search_urls = [
        f"http://www.kuwo.cn/search/searchMusicBykeyWord?vipver=1&client=kt&ft=music&cluster=0&strategy=2012&encoding=utf8&rformat=json&mobi=1&issubtitle=1&show_copyright_off=1&pn=0&rn=5&all={urllib.parse.quote(query)}",
        f"http://search.kuwo.cn/r.s?client=kt&all={urllib.parse.quote(query)}&pn=0&rn=5&rformat=json&encoding=utf8"
    ]

    for s_url in search_urls:
        try:
            resp = requests.get(s_url, timeout=(2, 3), headers={'User-Agent': 'Mozilla/5.0'})
            try:
                data = json_repair.loads(resp.text) or {}
            except Exception:
                data = {}
            items = data.get('abslist') or []
            for item in items:
                cand_artist = html.unescape(item.get('ARTIST', '')).replace('\xa0', ' ')
                cand_name = html.unescape(item.get('SONGNAME', '')).replace('\xa0', ' ')
                
                # 严格歌手比对与翻唱过滤
                if not is_singer_match(singers, [cand_artist], song_name, cand_name):
                    continue

                rid = str(item.get('MUSICRID', '')).removeprefix('MUSIC_')
                if not rid:
                    continue

                play_url_api = f"http://antiserver.kuwo.cn/anti.s?type=convert_url&rid={rid}&format=mp3&response=url"
                play_resp = requests.get(play_url_api, timeout=(2, 3), headers={'User-Agent': 'Mozilla/5.0'})
                res_url = play_resp.text.strip()
                if res_url.startswith('http'):
                    # 坚决过滤酷我官方下架假音频 (588957081 / 563182854 提示音 "当前音乐已从酷我音乐下线")
                    if any(fake_id in res_url for fake_id in ['588957081', '563182854']):
                        continue
                    try:
                        head_resp = requests.head(res_url, timeout=2, headers={'User-Agent': 'Mozilla/5.0'})
                        clen = int(head_resp.headers.get('Content-Length', 0) or 0)
                        if 0 < clen < 500 * 1024:
                            continue
                    except Exception:
                        pass
                    return res_url
        except Exception:
            continue

    return None


def resolve_qq_fast_url(song_mid):
    """QQ 音乐通过备用开放接口秒级获取播放直链（配置合理超时与快速重试）"""
    if not song_mid:
        return None
    for attempt in range(2):
        try:
            r = requests.get(f'https://api.xunhuisi.store/API/QQMusic/Song.php?mid={song_mid}&type=json', timeout=(3, 7)).json()
            u = r.get('music_url')
            if u and str(u).startswith('http'):
                return u
        except Exception:
            continue
    return None


def safe_dict_extract(d, keys, default=None):
    """递归安全提取嵌套字典，彻底避免因返回 'data': null 引发的 AttributeError"""
    curr = d
    for k in keys:
        if not isinstance(curr, dict):
            return default
        curr = curr.get(k)
        if curr is None:
            return default
    return curr


def clean_music_query(song_name, singers=''):
    """智能净化歌名与歌手名，剔除 (电视剧...)、[Live]、feat 等干扰词"""
    s_raw = str(song_name or '').strip()
    s_clean = re.sub(r'[\(（\[【].*?[\)）\]】]', '', s_raw).strip()
    s_name = s_clean if len(s_clean) >= 2 else s_raw
    clean_singer = str(singers or '').split(' / ')[0].split(',')[0].split('、')[0].strip()
    if clean_singer.lower() in {'未知歌手', '未知艺人', 'various artists', 'unknown'}:
        clean_singer = ''
    return s_name, clean_singer


def compute_match_score(song_name, singers, album, cand_name, cand_singers, cand_album=''):
    """计算候选曲目与目标歌单曲目的综合匹配度评分 (0-100)"""
    # 1. 歌手一票否决：若歌手完全对不上，直接 0 分，杜绝翻唱
    if not is_singer_match(singers, cand_singers, song_name, cand_name):
        return 0

    score = 50.0

    # 2. 歌名相似度 (0-30分)
    clean_target = re.sub(r'[\(\[\{（【].*?[\)\]\}）】]', '', str(song_name or '')).strip().lower()
    clean_cand = re.sub(r'[\(\[\{（【].*?[\)\]\}）】]', '', str(cand_name or '')).strip().lower()
    if clean_target == clean_cand:
        score += 30
    elif clean_target in clean_cand or clean_cand in clean_target:
        score += 20
    else:
        score += 10

    # 3. 伴奏/Live 反偏惩罚 (-25 ~ -40分)
    target_lower = str(song_name or '').lower()
    cand_lower = str(cand_name or '').lower()
    if 'live' not in target_lower and '现场' not in target_lower and '演唱会' not in target_lower:
        if 'live' in cand_lower or '现场' in cand_lower or '演唱会' in cand_lower:
            score -= 25
    if '伴奏' not in target_lower and 'instrumental' not in target_lower:
        if '伴奏' in cand_lower or 'instrumental' in cand_lower:
            score -= 40

    # 4. 专辑严格对齐加分 (0-20分)
    if album and cand_album:
        a1 = str(album).strip().lower()
        a2 = str(cand_album).strip().lower()
        if a1 == a2:
            score += 20
        elif a1 in a2 or a2 in a1:
            score += 10

    return max(0, score)


def resolve_by_qq_search(song_name, singers='', album=''):
    """通过 QQ 音乐官方移动端检索对齐 mid，按匹配度最高算法获取正品直链"""
    if not song_name:
        return None
    s_name, c_singer = clean_music_query(song_name, singers)
    query = f"{s_name} {c_singer}".strip() if c_singer else s_name
    url = "https://u.y.qq.com/cgi-bin/musicu.fcg"
    payload = {
        "comm": {"ct": "19", "cv": "1859", "uin": "0"},
        "music.search.SearchCgiService.DoSearchForQQMusicMobile": {
            "method": "DoSearchForQQMusicMobile",
            "module": "music.search.SearchCgiService",
            "param": {"search_type": 0, "query": query, "page_num": 1, "num_per_page": 8}
        }
    }
    try:
        r = requests.post(url, json=payload, timeout=(3, 5)).json()
        items = safe_dict_extract(r, ["music.search.SearchCgiService.DoSearchForQQMusicMobile", "data", "body", "item_song"], [])
        candidates = []
        for item in (items or []):
            cand_name = str(item.get("title", "")).replace("<em>", "").replace("</em>", "")
            cand_singers = [s.get("name") for s in (item.get("singer", []) or []) if isinstance(s, dict) and s.get("name")]
            cand_album = str(safe_dict_extract(item, ["album", "name"], "") or item.get("albumname") or "")
            score = compute_match_score(song_name, singers, album, cand_name, cand_singers, cand_album)
            mid = item.get("mid")
            if score > 0 and mid:
                candidates.append((score, mid))

        # 按匹配度从高到低排序，优先取匹配度最高的一首
        candidates.sort(key=lambda x: x[0], reverse=True)
        for score, mid in candidates:
            u = resolve_qq_fast_url(mid)
            if u:
                return u
    except Exception:
        pass
    return None


def resolve_fast_cover(song_name, singers='', identifier='', album=''):
    """极速对齐获取歌曲的 300x300 原厂官方高清专辑封面"""
    if not song_name:
        return ''

    # 1. 若有网易云纯数字 ID，直接调用网易云详情接口获取官方高清封面
    if identifier and str(identifier).isdigit():
        try:
            r = requests.get(f'http://music.163.com/api/song/detail/?id={identifier}&ids=[{identifier}]', timeout=(2, 3)).json()
            songs = r.get('songs', [])
            if songs:
                pic = songs[0].get('album', {}).get('picUrl')
                if pic and str(pic).startswith('http'):
                    return str(pic)
        except Exception:
            pass

    # 2. 通过 QQ 音乐极速检索匹配专辑 mid，拼接原厂官方 300x300 高清图
    s_name, c_singer = clean_music_query(song_name, singers)
    query = f"{s_name} {c_singer}".strip() if c_singer else s_name
    url = "https://u.y.qq.com/cgi-bin/musicu.fcg"
    payload = {
        "comm": {"ct": "19", "cv": "1859", "uin": "0"},
        "music.search.SearchCgiService.DoSearchForQQMusicMobile": {
            "method": "DoSearchForQQMusicMobile",
            "module": "music.search.SearchCgiService",
            "param": {"search_type": 0, "query": query, "page_num": 1, "num_per_page": 3}
        }
    }
    try:
        r = requests.post(url, json=payload, timeout=(2, 3)).json()
        items = safe_dict_extract(r, ["music.search.SearchCgiService.DoSearchForQQMusicMobile", "data", "body", "item_song"], [])
        if items:
            for item in items:
                alb_mid = item.get('album', {}).get('mid')
                if alb_mid and str(alb_mid).strip():
                    return f"https://y.qq.com/music/photo_new/T002R300x300M000{alb_mid}.jpg"
    except Exception:
        pass

    # 3. 通过网易云搜索兜底获取专辑图片
    try:
        w_url = f"http://music.163.com/api/search/get/web?s={urllib.parse.quote(query)}&type=1&offset=0&total=true&limit=1"
        wr = requests.get(w_url, timeout=(2, 3)).json()
        songs = wr.get('result', {}).get('songs', [])
        if songs:
            pic = songs[0].get('album', {}).get('artist', {}).get('img1v1Url')
            if pic and str(pic).startswith('http'):
                return str(pic)
    except Exception:
        pass

    return ''


def resolve_qq_official_lrc(song_mid):
    """根据 QQ 音乐 songmid 0.05秒精准获取原厂官方毫秒级 LRC 歌词"""
    if not song_mid:
        return ''
    headers = {'Referer': 'https://y.qq.com/', 'User-Agent': 'Mozilla/5.0'}
    params = {
        'songmid': str(song_mid),
        'g_tk': '5381',
        'loginUin': '0',
        'hostUin': '0',
        'format': 'json',
        'inCharset': 'utf8',
        'outCharset': 'utf-8',
        'platform': 'yqq'
    }
    try:
        r = requests.get('https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg', headers=headers, params=params, timeout=(3, 5)).json()
        raw_lrc = r.get('lyric')
        if raw_lrc:
            lrc = base64.b64decode(raw_lrc).decode('utf-8', errors='ignore')
            if lrc and len(lrc.strip()) > 10:
                return lrc.strip()
    except Exception:
        pass
    return ''


def resolve_netease_lrc_by_id(song_id):
    """根据网易云歌曲 ID 0.05秒精准获取官方 LRC 歌词"""
    if not song_id:
        return ''
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://music.163.com/'
    }
    try:
        lr = requests.get(f'https://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1', headers=headers, timeout=(3, 5), verify=False).json()
        lrc = safe_dict_extract(lr, ['lrc', 'lyric'], '')
        if lrc and str(lrc).strip() and str(lrc).strip() not in {'NULL', 'None'}:
            return str(lrc).strip()
    except Exception:
        pass
    return ''


def resolve_kugou_fast_lrc(song_name, singers=''):
    """通过酷狗 Web 搜索 + 移动端双通道极速检索全曲库毫秒级 LRC 歌词（HTTPS 全程加密，免海外 IP 封锁）"""
    if not song_name:
        return ''
    s_name, c_singer = clean_music_query(song_name, singers)
    queries = []
    if c_singer:
        queries.append(f"{s_name} {c_singer}".strip())
    queries.append(s_name)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }

    for query in queries:
        encoded_query = urllib.parse.quote(query)
        hash_ = ''
        dur = 0

        # 通道 1: 酷狗官方 Web 端搜索（海外 IP 畅通无阻，绝不返回 null）
        try:
            web_url = f"https://songsearch.kugou.com/song_search_v2?keyword={encoded_query}&page=1&pagesize=2&platform=WebFilter"
            r = requests.get(web_url, timeout=(3, 5), headers=headers).json()
            lists = safe_dict_extract(r, ['data', 'lists'], [])
            if lists:
                first = lists[0]
                hash_ = first.get('FileHash') or first.get('HQFileHash') or first.get('SQFileHash') or ''
                dur = first.get('Duration', 0)
        except Exception:
            pass

        # 通道 2: 酷狗移动端接口兜底
        if not hash_:
            try:
                mob_url = f"https://mobilecdn.kugou.com/api/v3/search/song?format=json&keyword={encoded_query}&page=1&pagesize=2"
                r = requests.get(mob_url, timeout=(3, 5), headers=headers).json()
                info = safe_dict_extract(r, ['data', 'info'], [])
                if info:
                    first = info[0]
                    hash_ = first.get('hash') or ''
                    dur = first.get('duration', 0)
            except Exception:
                pass

        # 匹配到 hash 即刻拉取 LRC 歌词
        if hash_:
            try:
                krc_url = f"https://krcs.kugou.com/search?ver=1&man=yes&client=mobi&keyword={encoded_query}&duration={dur}&hash={hash_}"
                kr = requests.get(krc_url, timeout=(3, 5), headers=headers).json()
                cands = safe_dict_extract(kr, ['candidates'], [])
                if cands:
                    cand = cands[0]
                    cid, ak = cand.get('id'), cand.get('accesskey')
                    if cid and ak:
                        dl_url = f"https://lyrics.kugou.com/download?ver=1&client=pc&id={cid}&accesskey={ak}&fmt=lrc&charset=utf8"
                        dl_res = requests.get(dl_url, timeout=(3, 5), headers=headers).json()
                        raw_c = dl_res.get('content')
                        if raw_c:
                            lrc = base64.b64decode(raw_c).decode('utf-8', errors='ignore')
                            if lrc and len(lrc.strip()) > 10:
                                return lrc.strip()
            except Exception:
                pass

    return ''


def resolve_netease_search_lrc(song_name, singers=''):
    """通过网易云 cloudsearch 检索对齐获取 LRC 歌词"""
    if not song_name:
        return ''
    s_name, c_singer = clean_music_query(song_name, singers)
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://music.163.com/'
    }
    queries = []
    if c_singer:
        queries.append(f"{s_name} {c_singer}".strip())
    queries.append(s_name)

    for q in queries:
        try:
            sr_url = f"https://music.163.com/api/cloudsearch/pc?s={urllib.parse.quote(q)}&type=1&offset=0&limit=2"
            sr = requests.post(sr_url, headers=headers, timeout=(3, 5), verify=False).json()
            songs = safe_dict_extract(sr, ['result', 'songs'], [])
            if songs:
                sid = songs[0].get('id')
                if sid:
                    lrc = resolve_netease_lrc_by_id(sid)
                    if lrc:
                        return lrc
        except Exception:
            continue
    return ''


def resolve_fast_lrc(song_name, singers='', song_id=None, source=''):
    """全网工业级精准歌词引擎：平台原厂直出绝对优先（QQ官方/网易云官方） -> 酷狗对齐 -> 网易云云检索"""
    # 1.【平台原厂直出绝对优先】若歌曲来自 QQ 音乐或具备 QQ mid
    if source == 'QQMusicClient' or 'qq' in str(source).lower() or (song_id and not str(song_id).isdigit() and len(str(song_id)) >= 10):
        mid = song_id
        if not mid or str(mid).isdigit():
            mid = resolve_by_qq_search(song_name, singers)
        if mid:
            lrc = resolve_qq_official_lrc(mid)
            if lrc:
                return lrc

    # 2.【平台原厂直出绝对优先】若歌曲来自网易云音乐或具备数字 song_id
    if source == 'NeteaseMusicClient' or '163' in str(source).lower() or (song_id and str(song_id).isdigit()):
        if song_id and str(song_id).isdigit():
            lrc = resolve_netease_lrc_by_id(song_id)
            if lrc:
                return lrc

    # 3. 兜底尝试 QQ 音乐移动端检索对齐 mid 获取官方原厂毫秒级歌词
    if song_name:
        mid = resolve_by_qq_search(song_name, singers)
        if mid:
            lrc = resolve_qq_official_lrc(mid)
            if lrc:
                return lrc

    # 4. 酷狗 Web + 移动端双通道兜底
    lrc = resolve_kugou_fast_lrc(song_name, singers)
    if lrc:
        return lrc

    # 5. 网易云云检索对齐兜底
    lrc = resolve_netease_search_lrc(song_name, singers)
    if lrc:
        return lrc

    return ''


def resolve_by_netease_search(song_name, singers='', album=''):
    """通过网易云云搜索获取官方高品质播放直链（按匹配度最高原则精准对齐）"""
    if not song_name:
        return None
    s_name, c_singer = clean_music_query(song_name, singers)
    queries = [f"{s_name} {c_singer}".strip()] if c_singer else []
    queries.append(s_name)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://music.163.com/'
    }
    for q in queries:
        try:
            sr_url = f"https://music.163.com/api/cloudsearch/pc?s={urllib.parse.quote(q)}&type=1&offset=0&limit=8"
            r = requests.post(sr_url, headers=headers, timeout=(3, 5), verify=False).json()
            songs = safe_dict_extract(r, ['result', 'songs'], [])
            candidates = []
            for s in (songs or []):
                cand_name = s.get('name', '')
                cand_artists = [a.get('name', '') for a in s.get('ar', []) if a.get('name')]
                cand_album = s.get('al', {}).get('name', '') if isinstance(s.get('al'), dict) else ''
                score = compute_match_score(song_name, singers, album, cand_name, cand_artists, cand_album)
                sid = s.get('id')
                if score > 0 and sid:
                    candidates.append((score, sid))

            candidates.sort(key=lambda x: x[0], reverse=True)
            for score, sid in candidates:
                url = resolve_netease_direct_url(sid)
                if url:
                    return url
        except Exception:
            continue
    return None


def resolve_instant_stream(song, entry):
    """按平台精准定位直链：原歌单平台优先直达，对应歌手与专辑严格对齐，最高匹配度解析"""
    url = getattr(song, 'download_url', None)
    if url and str(url).startswith('http'):
        return url

    raw_search = getattr(song, 'raw_data', {}).get('search', {}) if hasattr(song, 'raw_data') else {}
    source = entry.get('source', '') or getattr(song, 'source', '')
    song_album = getattr(song, 'album', '') or ''

    # 1.【歌单平台绝对优先】若歌单来自 QQ 音乐，100% 直奔 QQ 音乐官方原版直通！
    if source == 'QQMusicClient' or 'qq' in str(source).lower():
        mid = song.identifier or raw_search.get('mid') or raw_search.get('songmid')
        if mid:
            url = resolve_qq_fast_url(mid)
            if url:
                song.download_url = url
                return url
        # 自带 mid 遇到偶发抖动或无有效 mid 时，在 QQ 音乐本源平台内进行匹配度最高对齐直连
        url = resolve_by_qq_search(song.song_name, song.singers, album=song_album)
        if url:
            song.download_url = url
            return url

    # 2.【歌单平台绝对优先】若歌单来自网易云音乐，100% 直奔网易云官方原版直通！
    if source == 'NeteaseMusicClient' or '163' in str(source).lower() or 'netease' in str(source).lower():
        song_id = getattr(song, 'identifier', '') or raw_search.get('songid')
        if song_id and str(song_id).isdigit():
            url = resolve_netease_direct_url(song_id)
            if url:
                song.download_url = url
                return url
        url = resolve_by_netease_search(song.song_name, song.singers, album=song_album)
        if url:
            song.download_url = url
            return url

    # 3.【歌单平台绝对优先】若歌单来自酷我音乐，直接按酷我官方解析！
    if source == 'KuwoMusicClient' or 'kuwo' in str(source).lower():
        song_id = getattr(song, 'identifier', '') or raw_search.get('MUSICRID') or raw_search.get('musicrid')
        url = resolve_kuwo_direct_url(song.song_name, song.singers, song_id=song_id)
        if url:
            song.download_url = url
            return url

    # 4. 跨平台兜底（仅在原平台未解析出直链时）：严格同歌手正版对齐，绝不拿翻唱充数！
    url = resolve_by_netease_search(song.song_name, song.singers, album=song_album)
    if url:
        song.download_url = url
        return url

    url = resolve_by_qq_search(song.song_name, song.singers, album=song_album)
    if url:
        song.download_url = url
        return url

    url = resolve_kuwo_direct_url(song.song_name, song.singers)
    if url:
        song.download_url = url
        return url

    return url


@app.route('/api/stream/<token>')
def api_stream(token):
    entry = REGISTRY.get(token)
    if not entry:
        return '音频已失效或未找到', 404

    song = entry['song_info']
    url = resolve_instant_stream(song, entry)

    if not url or not str(url).startswith('http'):
        return '无效的音频直链', 404

    is_download = request.args.get('download') == '1'
    embed_lyric = request.args.get('embed_lyric') == '1'
    target_format = (request.args.get('format') or 'original').lower().strip().lstrip('.')

    orig_ext = str(getattr(song, 'ext', '') or '').lstrip('.').lower()
    if not orig_ext or orig_ext in {'none', 'null'}:
        clean_url = url.split('?')[0].lower()
        if clean_url.endswith('.flac'):
            orig_ext = 'flac'
        elif clean_url.endswith('.m4a') or clean_url.endswith('.aac'):
            orig_ext = 'm4a'
        elif clean_url.endswith('.wav'):
            orig_ext = 'wav'
        elif clean_url.endswith('.ogg'):
            orig_ext = 'ogg'
        else:
            orig_ext = 'mp3'
    song.ext = orig_ext

    # 在线试听：直接 302 重定向至 CDN，让浏览器原生硬解流式播放，彻底免除反代二次中转缓冲、避免 WSGI chunked 协议冲突与海外地域封锁！
    if not is_download and not embed_lyric and target_format in {'', 'original'}:
        return redirect(url, code=302)

    # 规范化 upstream_headers，根据真实直链域名配置，坚决避免跨平台 referer 引发 CDN 403 Forbidden
    upstream_headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': '*/*',
        'Accept-Encoding': 'identity;q=1, *;q=0',
    }
    if 'kuwo.cn' in url:
        upstream_headers['Referer'] = 'http://www.kuwo.cn/'
    elif 'music.126.net' in url or '163.com' in url:
        upstream_headers['Referer'] = 'https://music.163.com/'
    elif 'qqmusic.qq.com' in url or 'qq.com' in url:
        upstream_headers['Referer'] = 'https://y.qq.com/'

    range_header = request.headers.get('Range')
    if range_header and not is_download:
        upstream_headers['Range'] = range_header

    try:
        up = requests.get(url, headers=upstream_headers,
                          stream=True, timeout=(6, 15), verify=False)
    except Exception as err:
        return f'源站连接失败: {err}', 502

    # Check if format transcoding is required for download
    need_transcode = is_download and target_format not in {'', 'original', orig_ext}

    if need_transcode:
        try:
            raw_bytes = up.content
            transcoded_bytes = transcode_audio(raw_bytes, target_format=target_format)
            final_ext = target_format
            if embed_lyric:
                transcoded_bytes = try_embed_metadata(transcoded_bytes, final_ext, song)
            filename = f"{song.song_name} - {song.singers}.{final_ext}"
            resp_headers = {
                'Content-Type': RESULT_EXT_TO_MIME.get(final_ext, 'application/octet-stream'),
                'Content-Length': str(len(transcoded_bytes)),
                'Content-Disposition': make_content_disposition(filename, final_ext),
                'Cache-Control': 'no-cache',
            }
            return Response(transcoded_bytes, status=200, headers=resp_headers)
        except Exception:
            # Fallback to original streaming on transcoding failure
            pass

    # If original download with metadata embedding requested
    if is_download and embed_lyric:
        try:
            raw_bytes = up.content
            final_bytes = try_embed_metadata(raw_bytes, orig_ext, song)
            final_ext = orig_ext
            filename = f"{song.song_name} - {song.singers}.{final_ext}"
            resp_headers = {
                'Content-Type': RESULT_EXT_TO_MIME.get(final_ext, 'application/octet-stream'),
                'Content-Length': str(len(final_bytes)),
                'Content-Disposition': make_content_disposition(filename, final_ext),
                'Cache-Control': 'no-cache',
            }
            return Response(final_bytes, status=200, headers=resp_headers)
        except Exception:
            pass

    # Default original streaming / download
    final_ext = orig_ext
    resp_headers = {
        'Content-Type': RESULT_EXT_TO_MIME.get(final_ext, 'application/octet-stream'),
        'Accept-Ranges': 'bytes',
        'Cache-Control': 'no-cache',
    }

    if is_download:
        filename = f"{song.song_name} - {song.singers}.{final_ext}"
        resp_headers['Content-Disposition'] = make_content_disposition(filename, final_ext)

    for h in ('Content-Length', 'Content-Range'):
        if h in up.headers:
            resp_headers[h] = up.headers[h]

    def generate():
        try:
            for chunk in up.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        finally:
            up.close()

    return Response(stream_with_context(generate()), status=up.status_code, headers=resp_headers)


@app.route('/api/cover/<token>')
def api_cover(token):
    entry = REGISTRY.get(token)
    song = entry['song_info'] if entry else None

    url = getattr(song, 'cover_url', None) if song else None
    if (not url or not str(url).startswith('http')) and song:
        s_name = getattr(song, 'song_name', '')
        s_singers = getattr(song, 'singers', '')
        s_id = getattr(song, 'identifier', '')
        s_album = getattr(song, 'album', '')
        url = resolve_fast_cover(s_name, s_singers, s_id, s_album)
        if url:
            song.cover_url = url
            REGISTRY._save_cache()

    if not url or not str(url).startswith('http'):
        return '', 404

    # 规范反盗链 Referer 请求头
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8'
    }
    if 'qq.com' in url:
        headers['Referer'] = 'https://y.qq.com/'
    elif '126.net' in url or '163.com' in url:
        headers['Referer'] = 'https://music.163.com/'
    elif 'kuwo.cn' in url:
        headers['Referer'] = 'http://www.kuwo.cn/'

    try:
        up = requests.get(url, headers=headers, timeout=(4, 8), verify=False)
        if up.status_code == 200 and up.content:
            return Response(up.content, status=200,
                            headers={'Content-Type': up.headers.get('Content-Type', 'image/jpeg'),
                                     'Cache-Control': 'public, max-age=86400'})
        return redirect(url, code=302)
    except Exception:
        return redirect(url, code=302)


@app.route('/api/lyric/<token>')
def api_lyric(token):
    entry = REGISTRY.get(token)
    song = entry['song_info'] if entry else None
    source = (entry.get('source') if entry else '') or (request.args.get('source') or '').strip()

    # 优先从注册表曲目中提取，若 token 不在内存中（如容器重启后），从 query 参数提取兜底
    song_name = getattr(song, 'song_name', '') if song else (request.args.get('song_name') or '').strip()
    singers = getattr(song, 'singers', '') if song else (request.args.get('singers') or '').strip()
    song_id = getattr(song, 'identifier', '') if song else (request.args.get('song_id') or '').strip()
    if not song_id and song and hasattr(song, 'raw_data'):
        song_id = song.raw_data.get('search', {}).get('mid', '') or song.raw_data.get('search', {}).get('songmid', '') or song.raw_data.get('search', {}).get('songid', '')

    print(f"[Lyric API] Request: token={token}, source='{source}', song='{song_name}', singer='{singers}', sid='{song_id}'", flush=True)

    raw_lyric = getattr(song, 'lyric', '') if song else ''
    lyric = str(raw_lyric or '').strip()
    if lyric in {'NULL', 'None', 'null'}:
        lyric = ''

    if not lyric and (song_name or song_id):
        lyric = resolve_fast_lrc(song_name, singers, song_id=song_id, source=source)
        if lyric and song:
            song.lyric = lyric
            REGISTRY._save_cache()

    print(f"[Lyric API] Response: has_lyric={bool(lyric)}, length={len(lyric)} chars", flush=True)

    if request.args.get('download') == '1':
        if not lyric:
            return Response('', status=204)
        fname = f"{song_name or 'audio'} - {singers or 'artist'}.lrc"
        encoded_filename = urllib.parse.quote(fname)
        headers = {
            'Content-Type': 'text/plain; charset=utf-8',
            'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}",
            'Cache-Control': 'no-cache',
        }
        return Response(lyric.encode('utf-8'), status=200, headers=headers)

    return jsonify({'lyric': lyric, 'has_lyric': bool(lyric)})


@app.route('/api/track/info/<token>')
def api_track_info(token):
    entry = REGISTRY.get(token)
    if not entry:
        return jsonify({'error': 'Track not found'}), 404
    song = entry['song_info']
    source = entry.get('source', '')
    return jsonify(track_to_payload(song, token, source))


def extract_playlist_title(client, song_infos, url):
    """从各音乐平台解析结果或原网页中提取真实的原始歌单名称"""
    # 1. 优先读取客户端在解析时记录的歌单名称
    name = getattr(client, 'cur_playlist_name', None)
    if name and not str(name).strip().startswith('playlist-'):
        return str(name).strip()

    # 2. 从 song_infos 首曲的 work_dir 目录还原真实歌单名
    if song_infos:
        work_dir = getattr(song_infos[0], 'work_dir', '')
        if work_dir:
            base = os.path.basename(str(work_dir).rstrip('/\\'))
            cleaned = re.sub(r'^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\s*', '', base).strip()
            if cleaned and not cleaned.startswith('playlist-'):
                return cleaned

    # 3. 若以上未获取到有效名称，通过轻量 HTTP 嗅探网页 <title> 还原
    if url and str(url).startswith('http'):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            }
            resp = requests.get(url, headers=headers, timeout=(3, 5), verify=False)
            match = re.search(r'<title>(.*?)</title>', resp.text, re.IGNORECASE | re.DOTALL)
            if match:
                raw_title = match.group(1).strip()
                # 剔除平台品牌后缀
                for suffix in [
                    ' - 歌单 - 网易云音乐',
                    ' - 网易云音乐',
                    ' - QQ音乐-千万正版音乐海量无损曲库新歌热歌天天畅听的高品质音乐平台！',
                    ' - QQ音乐',
                    ' - 酷狗音乐',
                    ' - 酷我音乐',
                    ' - 咪咕音乐网',
                    ' - 咪咕音乐',
                    ' - Apple Music',
                ]:
                    if suffix in raw_title:
                        raw_title = raw_title.replace(suffix, '').strip()
                if ' - ' in raw_title:
                    parts = raw_title.split(' - ')
                    if len(parts) >= 2 and parts[0].strip():
                        raw_title = parts[0].strip()
                if raw_title and len(raw_title) < 100:
                    return raw_title
        except Exception:
            pass

    return (str(name).strip() if name and not str(name).startswith('playlist-') else '')


def fast_parse_netease_playlist(url):
    """极速秒级解析网易云歌单元数据，0.3秒获取全量歌曲信息"""
    m = re.search(r'id=(\d+)', url)
    if not m:
        m = re.search(r'playlist/(\d+)', url)
    if not m:
        return None
    playlist_id = m.group(1)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://music.163.com/',
    }
    try:
        resp = requests.post('https://music.163.com/api/v6/playlist/detail', data={'id': playlist_id}, headers=headers, timeout=(3, 8), verify=False)
        data = resp.json()
        playlist = data.get('playlist') or {}
        title = playlist.get('name') or f"网易云歌单-{playlist_id}"
        tracks_raw = playlist.get('tracks') or []
        track_ids = [t.get('id') for t in (playlist.get('trackIds') or []) if t.get('id')]

        if len(tracks_raw) < len(track_ids) and track_ids:
            needed_ids = track_ids[:200]
            try:
                detail_resp = requests.post(
                    'https://music.163.com/api/v3/song/detail',
                    data={'c': json.dumps([{'id': i} for i in needed_ids])},
                    headers=headers, timeout=(3, 8), verify=False
                ).json()
                if detail_resp.get('songs'):
                    tracks_raw = detail_resp.get('songs')
            except Exception:
                pass

        song_infos = []
        for t in tracks_raw:
            song_name = t.get('name') or '未知歌曲'
            singers = ' / '.join([ar.get('name') for ar in t.get('ar', []) if ar.get('name')]) or '未知歌手'
            album = t.get('al', {}).get('name') or ''
            cover_url = t.get('al', {}).get('picUrl') or ''
            song_id_str = str(t.get('id') or '')
            dt_ms = int(t.get('dt') or 0)
            duration_s = dt_ms // 1000
            duration = f"{duration_s // 60:02d}:{duration_s % 60:02d}"
            t_search = dict(t)
            t_search.update({
                'songid': song_id_str,
                'songname': song_name,
                'singers': singers,
                'album': album,
                'cover_url': cover_url,
                'duration': duration,
            })
            song_info = SongInfo(
                source='NeteaseMusicClient',
                raw_data={
                    'search': t_search,
                    'download': {},
                    'lyric': {}
                }
            )
            song_info.identifier = song_id_str
            song_info.song_name = song_name
            song_info.singers = singers
            song_info.album = album
            song_info.cover_url = cover_url
            song_info.duration = duration
            song_infos.append(song_info)

        return title, song_infos
    except Exception as e:
        print(f"fast_parse_netease_playlist failed: {e}")
        return None


@app.route('/api/playlist/parse', methods=['POST'])
def api_parse_playlist():
    data = request.get_json(silent=True) or {}
    url = (data.get('url') or '').strip()
    source = data.get('source')
    if not url:
        return jsonify({'error': '歌单链接不能为空'}), 400

    # Auto-detect source if not specified
    if not source:
        if '163.com' in url:
            source = 'NeteaseMusicClient'
        elif 'qq.com' in url:
            source = 'QQMusicClient'
        elif 'kuwo.cn' in url:
            source = 'KuwoMusicClient'
        elif 'kugou.com' in url:
            source = 'KugouMusicClient'
        elif 'migu.cn' in url:
            source = 'MiguMusicClient'
        elif 'apple.com' in url:
            source = 'AppleMusicClient'
        elif 'spotify.com' in url:
            source = 'SpotifyMusicClient'
        else:
            source = 'NeteaseMusicClient'

    source_label_map = {
        'NeteaseMusicClient': '网易云音乐',
        'QQMusicClient': 'QQ音乐',
        'KuwoMusicClient': '酷我音乐',
        'KugouMusicClient': '酷狗音乐',
        'MiguMusicClient': '咪咕音乐',
        'AppleMusicClient': 'Apple Music',
        'SpotifyMusicClient': 'Spotify',
        'BilibiliMusicClient': 'B站音乐',
    }
    source_label = source_label_map.get(source, source)

    try:
        # 1. 优先尝试秒级极速元数据解析（针对网易云等超大歌单，秒出结果彻底避免 504 Gateway Time-out）
        if source == 'NeteaseMusicClient' or '163.com' in url:
            fast_res = fast_parse_netease_playlist(url)
            if fast_res:
                final_title, song_infos = fast_res
                tracks = []
                for song_info in (song_infos or []):
                    token = REGISTRY.add(song_info, 'NeteaseMusicClient')
                    tracks.append(track_to_payload(song_info, token, 'NeteaseMusicClient'))
                return jsonify({
                    'source': 'NeteaseMusicClient',
                    'source_label': '网易云音乐',
                    'title': final_title,
                    'playlist_name': final_title,
                    'count': len(tracks),
                    'tracks': tracks
                })

        # 2. 兜底调用客户端原生解析（强制开启 fast_metadata_mode 并设置 12 秒熔断）
        client = MANAGER.get_client(source)
        if hasattr(client, 'cur_playlist_name'):
            delattr(client, 'cur_playlist_name')
        client.fast_metadata_mode = True

        def _do_client_parse():
            return client.parseplaylist(url)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_do_client_parse)
            try:
                song_infos = future.result(timeout=12)
            except concurrent.futures.TimeoutError:
                return jsonify({'error': f'{source_label}歌单解析超时（超过12秒），源站响应缓慢，请稍后重试或检查链接是否有效'}), 200

        tracks = []
        for song_info in (song_infos or []):
            token = REGISTRY.add(song_info, source)
            tracks.append(track_to_payload(song_info, token, source))

        if not tracks:
            return jsonify({'error': f'未在{source_label}歌单中提取到有效曲目，请检查歌单是否公开或链接是否有效'}), 200

        playlist_title = extract_playlist_title(client, song_infos, url)
        final_title = playlist_title or f"{source_label}歌单"

        return jsonify({
            'source': source,
            'source_label': source_label,
            'title': final_title,
            'playlist_name': final_title,
            'count': len(tracks),
            'tracks': tracks
        })
    except Exception as err:
        return jsonify({'error': f"解析歌单失败: {str(err)}"}), 200


@app.route('/api/playlist/activate', methods=['POST'])
def api_activate_playlist():
    """纯元数据秒级激活载入：接收歌单的歌名、歌手、专辑、平台等元数据，瞬间注册会话并在主页展示区呈现"""
    data = request.get_json(silent=True) or {}
    raw_tracks = data.get('tracks') or []
    if not isinstance(raw_tracks, list) or not raw_tracks:
        return jsonify({'error': '无效的歌单曲目数据'}), 400

    activated_tracks = []
    song_info_list = []
    for t in raw_tracks:
        song_name = str(t.get('song_name') or '未知曲目').strip()
        singers = str(t.get('singers') or '未知歌手').strip()
        album = str(t.get('album') or '').strip()
        source = str(t.get('source') or 'QQMusicClient').strip()
        identifier = str(t.get('identifier') or '').strip()
        duration = str(t.get('duration') or '00:00').strip()
        cover_url = str(t.get('cover_url') or '').strip()
        ext = str(t.get('ext') or '').strip()

        # 构建轻量级 SongInfo，绝不预先发起任何耗时的网络直链请求，0 毫秒完成！
        song_info = SongInfo(
            source=source,
            raw_data={
                'search': {
                    'songname': song_name,
                    'singers': singers,
                    'album': album,
                    'mid': identifier,
                    'songmid': identifier,
                    'songid': identifier,
                    'cover_url': cover_url,
                    'duration': duration,
                },
                'download': {},
                'lyric': {}
            }
        )
        song_info.identifier = identifier
        song_info.song_name = song_name
        song_info.singers = singers
        song_info.album = album
        song_info.duration = duration
        if cover_url:
            song_info.cover_url = cover_url
        if ext and ext.lower() not in {'none', 'null'}:
            song_info.ext = ext

        song_info_list.append((song_info, source))

    tokens = REGISTRY.add_batch(song_info_list)
    activated_tracks = [
        track_to_payload(song_info, token, source)
        for (song_info, source), token in zip(song_info_list, tokens)
    ]

    return jsonify({
        'count': len(activated_tracks),
        'tracks': activated_tracks
    })


# Temporary in-memory sync cache for QR cross-device migration (TTL: 15 mins)
SYNC_STORE = {}
SYNC_STORE_LOCK = threading.Lock()

def clean_expired_sync_sessions():
    now = time.time()
    with SYNC_STORE_LOCK:
        expired = [k for k, v in SYNC_STORE.items() if now - v.get('created_at', 0) > 900]
        for k in expired:
            SYNC_STORE.pop(k, None)


DEFAULT_SERVER_DOMAIN = os.environ.get('MUSICDL_DOMAIN', 'music.dbas.fun').strip()


def get_real_lan_ip():
    """获取本机物理无线网卡/以太网的真实局域网 IP，智能排除 VPN/TUN/TAP 虚拟网卡"""
    # 0. 优先支持环境变量显式指定
    env_lan_ip = os.environ.get('MUSICDL_LAN_IP', '').strip()
    if env_lan_ip:
        return env_lan_ip

    # 1. Windows 下通过 ipconfig 深度解析真实的物理 WLAN 或 Ethernet 适配器 IP
    if os.name == 'nt':
        try:
            out = subprocess.check_output('ipconfig', shell=True).decode('gbk', errors='ignore')
            current_adapter = ''
            wlan_ip = None
            eth_ip = None
            other_ips = []
            for line in out.splitlines():
                line = line.strip()
                if not line:
                    continue
                if ':' in line and not line.startswith(('IPv4', 'Subnet', 'Default', '子网', '默认', '本地', '临时', '连接')):
                    current_adapter = line
                if 'IPv4' in line:
                    ip_match = re.search(r'(\d+\.\d+\.\d+\.\d+)', line)
                    if ip_match:
                        ip = ip_match.group(1)
                        if ip.startswith('127.'):
                            continue
                        adapter_lower = current_adapter.lower()
                        # 过滤常见的代理与虚拟网卡 (singbox_tun, clash, tap-windows, vethernet, tailscale, zerotier 等)
                        if any(v in adapter_lower for v in ('tun', 'tap', 'vpn', 'vethernet', 'tailscale', 'zerotier', 'hyper-v', 'wsl')):
                            continue
                        if any(w in adapter_lower for w in ('wlan', '无线', 'wi-fi', 'wifi')):
                            wlan_ip = ip
                        elif any(e in adapter_lower for e in ('以太', 'ethernet')):
                            eth_ip = ip
                        else:
                            other_ips.append(ip)
            if wlan_ip:
                return wlan_ip
            if eth_ip:
                return eth_ip
            if other_ips:
                return other_ips[0]
        except Exception:
            pass

    # 2. Linux / macOS 或通用 socket 探测 (排除 TUN 常见网段)
    for target in [('223.5.5.5', 80), ('10.255.255.255', 1), ('8.8.8.8', 80)]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(target)
            ip = s.getsockname()[0]
            s.close()
            if ip and not ip.startswith('127.') and not ip.startswith('172.18.'):
                return ip
        except Exception:
            continue
    try:
        hostname = socket.gethostname()
        for ip in socket.gethostbyname_ex(hostname)[2]:
            if not ip.startswith('127.') and ':' not in ip and not ip.startswith('172.18.'):
                return ip
    except Exception:
        pass
    return '172.20.10.6'


def is_ip_address(host_str):
    """判断字符串是否为纯 IPv4 地址"""
    parts = host_str.split('.')
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return True
    return False


def resolve_sync_endpoint(req):
    """
    根据运行环境与访问特征全自动智能研判当前环境，生成唯一确定的同步 URL：
    - 绝无人工切换选项，彻底防呆
    - 云端部署/域名访问 -> 云端服务器二维码 (music.dbas.fun)
    - 本地/局域网访问 -> 局域网物理 IP 二维码 (172.20.10.6:5050)
    """
    raw_host = (req.headers.get('X-Forwarded-Host') or req.host or '127.0.0.1:5050').strip()
    scheme = req.headers.get('X-Forwarded-Proto') or req.scheme or 'http'

    if ':' in raw_host:
        host_name, port_str = raw_host.split(':', 1)
        port = f":{port_str}"
    else:
        host_name = raw_host
        port = ''

    # 1. 判断是否处于云端服务器环境
    env_deploy = (os.environ.get('MUSICDL_ENV', '') or os.environ.get('MUSICDL_DEPLOY', '')).lower()
    is_cloud_server = (
        env_deploy in ('server', 'production', 'cloud') or
        'music.dbas.fun' in host_name or
        'dbas.fun' in host_name or
        (not is_ip_address(host_name) and host_name not in ('localhost', '0.0.0.0', '::1'))
    )

    if is_cloud_server:
        # 处于云端服务器环境
        if not is_ip_address(host_name) and host_name not in ('localhost', '0.0.0.0'):
            base_url = f"{scheme}://{raw_host}"
            display_domain = raw_host
        else:
            server_domain = os.environ.get('MUSICDL_EXTERNAL_URL', '').strip() or DEFAULT_SERVER_DOMAIN
            if not server_domain.startswith(('http://', 'https://')):
                base_url = f"https://{server_domain}" if ('https' in scheme or ':443' in port) else f"http://{server_domain}"
                display_domain = server_domain
            else:
                base_url = server_domain.rstrip('/')
                display_domain = urllib.parse.urlparse(base_url).netloc or server_domain
        return {
            'env_type': 'server',
            'base_url': base_url,
            'badge_text': f"☁️ 云端同步 ({display_domain})",
            'sub_text': '已连接云端服务器，支持任意移动设备扫码'
        }

    # 2. 处于本地局域网环境
    lan_ip = get_real_lan_ip()
    actual_port = port or ':5050'
    lan_url = f"http://{lan_ip}{actual_port}"
    return {
        'env_type': 'lan',
        'base_url': lan_url,
        'badge_text': f"🌐 局域网同步 ({lan_ip}{actual_port})",
        'sub_text': '手机连接同一 WiFi 即可扫码秒级自动合并'
    }


@app.route('/api/sync/create', methods=['POST'])
def api_sync_create():
    """将歌单与配置临时注册到服务端内存生成简短同步码，用于二维码毫秒级跨设备迁移"""
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '无效的配置数据'}), 400

    clean_expired_sync_sessions()
    token = uuid.uuid4().hex[:12]
    with SYNC_STORE_LOCK:
        SYNC_STORE[token] = {
            'data': data,
            'created_at': time.time()
        }

    endpoint_info = resolve_sync_endpoint(request)
    sync_url = f"{endpoint_info['base_url'].rstrip('/')}/#sync={token}"

    return jsonify({
        'success': True,
        'token': token,
        'expires_in': 900,
        'sync_url': sync_url,
        'base_url': endpoint_info['base_url'],
        'env_type': endpoint_info['env_type'],
        'badge_text': endpoint_info['badge_text'],
        'sub_text': endpoint_info['sub_text']
    })


@app.route('/api/sync/get/<token>', methods=['GET'])
def api_sync_get(token):
    """跨端设备通过短 token 快速拉取完整配置与歌单"""
    clean_expired_sync_sessions()
    with SYNC_STORE_LOCK:
        entry = SYNC_STORE.get(token)

    if not entry:
        return jsonify({'error': '该配置同步码已过期或不存在'}), 404

    return jsonify({
        'success': True,
        'data': entry['data']
    })


@app.route('/api/download/local', methods=['POST'])
def api_download_local():
    data = request.get_json(silent=True) or {}
    token = data.get('token')
    entry = REGISTRY.get(token)
    if not entry:
        return jsonify({'error': '曲目未找到'}), 404

    song: SongInfo = entry['song_info']
    source = entry['source']
    
    def do_download():
        try:
            client = MANAGER.get_client(source)
            client.download(song_infos=[song])
        except Exception as e:
            print(f"Download error: {e}")

    threading.Thread(target=do_download, daemon=True).start()
    return jsonify({'success': True, 'message': '已加入后台下载队列'})


@app.route('/api/track/resolve', methods=['POST'])
def api_track_resolve():
    """当曲目的 token 或源站直链失效时，根据歌曲名与歌手即时自愈重新连接最新可用音源"""
    data = request.get_json(silent=True) or {}
    song_name = str(data.get('song_name', '')).strip()
    singers = str(data.get('singers', '')).strip()
    source = str(data.get('source', '')).strip()
    if not song_name:
        return jsonify({'error': '缺少歌曲名'}), 400

    # 秒级极速获取可用直链，绝不调用慢速全局 search 导致网关 504 切断
    direct_url = resolve_by_netease_search(song_name, singers) or resolve_kuwo_direct_url(song_name, singers)
    if direct_url:
        new_song = SongInfo(
            source='KuwoMusicClient' if 'kuwo' in direct_url else 'NeteaseMusicClient',
            song_name=song_name,
            singers=singers or '未知歌手',
            download_url=direct_url
        )
        new_song.ext = 'mp3'
        new_cover = resolve_fast_cover(song_name, singers)
        if new_cover:
            new_song.cover_url = new_cover
        new_token = REGISTRY.add(new_song, new_song.source)
        payload = track_to_payload(new_song, new_token, new_song.source)
        return jsonify({'success': True, 'track': payload})

    return jsonify({'error': f'未检索到可用的音源直链: {song_name}'}), 200


def run_server(host='127.0.0.1', port=5050, work_dir=None):
    global DOWNLOAD_DIR, REGISTRY_CACHE_FILE
    if work_dir:
        DOWNLOAD_DIR = os.path.abspath(work_dir)
        os.makedirs(DOWNLOAD_DIR, exist_ok=True)
        REGISTRY_CACHE_FILE = os.path.join(DOWNLOAD_DIR, '.track_registry.json')
    app.run(host=host, port=port, threaded=True, debug=False)


if __name__ == '__main__':
    run_server()
