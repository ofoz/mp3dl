"""平台注册表 + 客户端池 + 并发搜索 + 曲目会话缓存"""
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout, as_completed

from . import musicdl_env  # noqa: F401
from . import pricing, quality
from .tagger import usable_cover
from ..config import Config

from musicdl.modules.sources import BuildMusicClient  # noqa: E402

# 国内主流平台
# enabled=False 表示已下线：不参与搜索、不展示、不可下载。
# 保留定义是为了歌单链接能识别出「这个平台已下线」，而不是笼统报「不支持该链接」。
PLATFORMS = {
    "NeteaseMusicClient": {
        "label": "网易云音乐", "short": "网易云", "color": "#e5484d",
        "playlist": True, "default": True,
    },
    # 保留但默认不选中：只返回 ogg/flac（需要服务端转码才能交付 mp3），无法走浏览器直连。
    # 用户主动勾选才参与搜索。timeout 给到 150s，避免用户勾选后拿不到结果。
    # transcode=True：必然过服务器转码，所以按「服务端转码」价计费，不吃每日免费额度。
    "QQMusicClient": {
        "label": "QQ音乐", "short": "QQ", "color": "#31c27c",
        "playlist": True, "default": False,
        "timeout": 150, "transcode": True,
    },
    "KugouMusicClient": {
        "label": "酷狗音乐", "short": "酷狗", "color": "#2ba3ec",
        "playlist": True, "default": True,
    },
    # 已下线：CDN 不给 CORS，浏览器无法直连，音频只能过服务器中转而白烧带宽
    "KuwoMusicClient": {
        "label": "酷我音乐", "short": "酷我", "color": "#ffb400",
        "playlist": True, "default": False, "enabled": False,
        "offline_reason": "音源不支持直连下载，已下线",
    },
    # 已下线：同上
    "MiguMusicClient": {
        "label": "咪咕音乐", "short": "咪咕", "color": "#ff5a5f",
        "playlist": True, "default": False, "enabled": False,
        "offline_reason": "音源不支持直连下载，已下线",
    },
    "QianqianMusicClient": {
        "label": "千千音乐", "short": "千千", "color": "#6c5ce7",
        "playlist": True, "default": False, "enabled": False,
        "offline_reason": "已无可用音源，已下线",
    },
    # 已下线：只返回 m4a，要交付 mp3 必须服务端转码；且搜到的多为翻唱
    "SodaMusicClient": {
        "label": "汽水音乐", "short": "汽水", "color": "#00d4aa",
        "playlist": False, "default": False, "enabled": False,
        "offline_reason": "只提供 m4a，需服务端转码，且音源多为翻唱，已下线",
    },
    # 已下线：直链全部落在 *.kuwo.cn（酷我马甲站），同样没有 CORS
    "BodianMusicClient": {
        "label": "波点音乐", "short": "波点", "color": "#ff7ac6",
        "playlist": False, "default": False, "enabled": False,
        "offline_reason": "直链走酷我 CDN，不支持浏览器直连，已下线",
    },
}


def is_enabled(source: str) -> bool:
    meta = PLATFORMS.get(source)
    return bool(meta) and meta.get("enabled", True)


# 实际在用的平台（对外所有入口都以此为准）
ENABLED_SOURCES = [k for k, v in PLATFORMS.items() if v.get("enabled", True)]
DEFAULT_SOURCES = [k for k, v in PLATFORMS.items() if v.get("enabled", True) and v["default"]]

_local = threading.local()


def normalize_sources(sources):
    if not sources:
        return list(DEFAULT_SOURCES)
    out = []
    for s in sources:
        s = str(s).strip()
        if s in PLATFORMS and is_enabled(s) and s not in out:
            out.append(s)
    return out or list(DEFAULT_SOURCES)


def get_client(source: str):
    """每线程独立客户端，避免 session 串扰。"""
    cache = getattr(_local, "clients", None)
    if cache is None:
        cache = {}
        _local.clients = cache
    client = cache.get(source)
    if client is None:
        client = BuildMusicClient(module_cfg={
            "type": source,
            "search_size_per_source": Config.SEARCH_SIZE_PER_SOURCE,
            "disable_print": True,
            "max_retries": 2,
            "maintain_session": True,
            # musicdl 每次搜索都会落一份 search_results.pkl，默认目录会无限膨胀
            "work_dir": str(Config.MUSICDL_WORK_DIR),
        })
        cache[source] = client
    return client


def needs_transcode(source: str) -> bool:
    """该平台的音源是否必须经服务端转码（无法浏览器直连交付 mp3）。"""
    return bool((PLATFORMS.get(source) or {}).get("transcode"))


def source_note(source: str) -> str:
    """平台说明（悬浮提示 / 选中 toast 用），文案跟着价目表走。"""
    meta = PLATFORMS.get(source) or {}
    if meta.get("note"):
        return meta["note"]
    if needs_transcode(source):
        return f"需服务端转码，{Config.PRICE_CREDIT_TRANSCODE} 积分/首"
    return ""


def source_timeout(source: str) -> int:
    """单平台搜索超时：需要服务端转码/走第三方接口的平台给更长预算，否则用户主动勾选也拿不到结果。"""
    meta = PLATFORMS.get(source) or {}
    try:
        return int(meta.get("timeout") or Config.SOURCE_TIMEOUT)
    except (TypeError, ValueError):
        return Config.SOURCE_TIMEOUT


def meta_payload(source: str) -> dict:
    meta = PLATFORMS.get(source) or {}
    transcode = needs_transcode(source)
    price = pricing.unit_price("mp3", transcode)
    return {
        "key": source,
        "label": meta.get("label", source),
        "short": meta.get("short", source),
        "color": meta.get("color", "#888"),
        "playlist": bool(meta.get("playlist")),
        "default": bool(meta.get("default")),
        "transcode": transcode,
        "credits": price["credits"],
        "free_ok": price["free_ok"],
        "note": source_note(source),
    }


# ---------- 曲目会话缓存（搜索结果里的直链不暴露给前端） ----------
class TrackStore:
    def __init__(self, ttl=1800, cap=4000):
        self._data = {}
        self._lock = threading.Lock()
        self.ttl = ttl
        self.cap = cap

    def put(self, song_info, platform):
        key = self._key(platform, song_info)
        with self._lock:
            if len(self._data) >= self.cap:
                self._evict()
            self._data[key] = (time.time(), song_info, platform)
        return key

    def get(self, key):
        with self._lock:
            item = self._data.get(key)
            if not item:
                return None
            ts, song, platform = item
            if time.time() - ts > self.ttl:
                self._data.pop(key, None)
                return None
            return song, platform

    def _evict(self):
        now = time.time()
        for k in [k for k, v in self._data.items() if now - v[0] > self.ttl][:500]:
            self._data.pop(k, None)
        if len(self._data) >= self.cap:
            for k in sorted(self._data, key=lambda k: self._data[k][0])[: self.cap // 4]:
                self._data.pop(k, None)

    @staticmethod
    def _key(platform, song):
        ident = getattr(song, "identifier", "") or getattr(song, "song_name", "")
        return f"{platform}:{ident}"


TRACKS = TrackStore()


def track_payload(song, platform):
    transcode = needs_transcode(platform)
    mp3_price = pricing.unit_price("mp3", transcode)
    flac_price = pricing.unit_price("flac", transcode)
    return {
        "track_key": TrackStore._key(platform, song),
        "platform": platform,
        "platform_label": PLATFORMS.get(platform, {}).get("label", platform),
        "platform_color": PLATFORMS.get(platform, {}).get("color", "#888"),
        "song_name": song.song_name or "",
        "singers": song.singers or "",
        "album": song.album or "",
        "ext": (song.ext or "").lstrip(".").lower(),
        "file_size": song.file_size or "",
        "file_size_bytes": song.file_size_bytes or 0,
        "duration": song.duration or "",
        "duration_s": song.duration_s or 0,
        "cover_url": usable_cover(song.cover_url or ""),
        "has_lyric": bool(song.lyric),
        "transcode": transcode,
        "price": {
            "mp3": {"credits": mp3_price["credits"], "free_ok": mp3_price["free_ok"]},
            "flac": {"credits": flac_price["credits"], "free_ok": flac_price["free_ok"]},
        },
    }


def _request_overrides(source, profile="mp3"):
    """MP3 档才强制走「音质列表」分支。

    网易云在无 cookies 时会直接吃第三方接口返回的无损文件（单首 130MB+），
    传一个与内置默认值不同的 cookie 即可让它按音质档位申请 320k MP3。
    但内置 cookie 没有无损权益，所以无损档反而要放开走第三方无损通道。
    酷狗/QQ 传 cookies 会砍掉大半搜索结果，一律不动。
    """
    if source == "NeteaseMusicClient" and profile == "mp3":
        try:
            from musicdl.modules.utils.neteaseutils import DEFAULT_COOKIES
            cookies = dict(DEFAULT_COOKIES)
        except Exception:
            cookies = {}
        cookies["MP3DL"] = "1"
        return {"cookies": cookies}
    return {}


LOSSLESS_EXTS = {"flac", "wav", "ape", "alac", "wv", "tta", "dsf", "dff"}


def search_one(source: str, keyword: str, profile: str = "mp3"):
    started = time.time()
    with quality.use_profile(source, profile):
        client = get_client(source)
        song_infos = client.search(keyword=keyword, request_overrides=_request_overrides(source, profile)) or []
    tracks = []
    for song in song_infos:
        if not song.song_name:
            continue
        TRACKS.put(song, source)
        tracks.append(track_payload(song, source))
    # 小体积（mp3/ogg）优先展示：用户一眼就能挑到不用转码的版本；无损档则保持原生顺序
    if profile == "mp3":
        tracks.sort(key=lambda t: 1 if t.get("ext") in LOSSLESS_EXTS else 0)
    return {
        "platform": source,
        "label": PLATFORMS.get(source, {}).get("label", source),
        "count": len(tracks),
        "elapsed": round(time.time() - started, 2),
        "tracks": tracks,
    }


class _HookList(list):
    """带钩子的 list：musicdl 的 _search 每解析出一首就 append 一次，
    把它的目标容器换成这个类，就能在搜索过程中拿到单曲，实现边搜边推。
    """

    def __init__(self, on_append):
        super().__init__()
        self._on_append = on_append

    def append(self, item):
        super().append(item)
        try:
            self._on_append(item)
        except Exception:  # 回调失败不能影响搜索本身
            pass

    def extend(self, items):
        for item in items:
            self.append(item)


def search_stream(source: str, keyword: str, profile: str = "mp3", on_track=None):
    """与 search_one 等价，但每解析出一首就回调 on_track(track_dict)。

    musicdl 的 search() 内部按 URL 并发调 _search，而 _search 是「逐首解析」的
    （每首要额外请求 1~2 次拿直链），整平台要 20~30s。这里把 _search 收到的
    song_infos 容器换成 _HookList，逐首回调，首屏几百毫秒内就能出第一首。
    """
    started = time.time()
    hits = []

    def emit(song):
        if not song.song_name:
            return
        TRACKS.put(song, source)
        payload = track_payload(song, source)
        hits.append(payload)
        if on_track is not None:
            on_track(payload)

    with quality.use_profile(source, profile):
        client = get_client(source)
        orig = client._search

        def patched(*args, **kwargs):
            # _search(keyword, search_url, request_overrides, song_infos, progress[, progress_id])
            args = list(args)
            watch = target = None
            if len(args) >= 4 and isinstance(args[3], list):
                target, watch = args[3], _HookList(emit)
                args[3] = watch
            else:
                key = next((k for k, v in kwargs.items() if isinstance(v, list)), None)
                if key is not None:
                    target, watch = kwargs[key], _HookList(emit)
                    kwargs[key] = watch
            try:
                return orig(*args, **kwargs)
            finally:
                # 把钩子收到的条目写回原容器，search() 的统计/pkl 落盘才不会漏
                if target is not None and watch is not None:
                    target.extend(list(watch))

        client._search = patched
        try:
            client.search(keyword=keyword, request_overrides=_request_overrides(source, profile))
        finally:
            try:
                del client._search
            except AttributeError:
                client._search = orig

    return {
        "platform": source,
        "label": PLATFORMS.get(source, {}).get("label", source),
        "count": len(hits),
        "elapsed": round(time.time() - started, 2),
        "tracks": hits,
    }


def search_all(keyword, sources, profile="mp3"):
    """并发搜索，按平台返回（超时的平台返回空并标注 timeout）。

    用统一的 deadline 而不是「每个平台各等一次」：后者会把各平台超时累加，
    勾上 QQ（150s）时整个请求可能挂到 3 分钟。
    """
    sources = normalize_sources(sources)
    if not sources:
        return []
    deadline = time.time() + max(source_timeout(s) for s in sources)
    done = {}
    pool = ThreadPoolExecutor(max_workers=min(len(sources), 5))
    futures = {pool.submit(search_one, s, keyword, profile): s for s in sources}
    try:
        for fut in as_completed(futures, timeout=max(0.1, deadline - time.time())):
            src = futures[fut]
            try:
                done[src] = fut.result()
            except Exception as err:
                done[src] = {
                    "platform": src, "label": PLATFORMS.get(src, {}).get("label", src),
                    "count": 0, "elapsed": 0, "tracks": [], "error": str(err)[:200],
                }
    except FutureTimeout:
        pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    results = []
    for src in sources:
        if src in done:
            results.append(done[src])
        else:
            results.append({
                "platform": src, "label": PLATFORMS.get(src, {}).get("label", src),
                "count": 0, "elapsed": source_timeout(src), "tracks": [], "error": "timeout",
            })
    return results


def search_specific(source, keyword, profile="mp3"):
    """针对某个平台重新检索（用于无损档或链接失效后的补救）。"""
    if not is_enabled(source):
        raise RuntimeError("该音源已下线")
    return search_one(source, keyword, profile)
