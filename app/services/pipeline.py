"""单曲下载流水线：解析 -> 拉取 -> 转码 -> 打标 -> 入库缓存"""
import hashlib
import os
import time

import requests

from ..config import Config
from .. import db
from . import platforms, quality, tagger, transcode

requests.packages.urllib3.disable_warnings()

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

REFERERS = {
    "NeteaseMusicClient": "https://music.163.com/",
    "QQMusicClient": "https://y.qq.com/",
    "KugouMusicClient": "https://www.kugou.com/",
    "KuwoMusicClient": "http://www.kuwo.cn/",
    "MiguMusicClient": "https://music.migu.cn/",
    "QianqianMusicClient": "https://music.91q.com/",
}


class LosslessUnavailable(Exception):
    pass


class DownloadFailed(Exception):
    pass


# 单曲上限：正常无损 30~130MB，给到 500MB 足够，同时挡住异常无穷流
MAX_TRACK_BYTES = 500 * 1024 * 1024


def file_id_of(platform, song, target_quality):
    raw = f"{platform}:{getattr(song, 'identifier', '') or song.song_name}:{getattr(song, 'song_name', '')}:{target_quality}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _headers(platform, song):
    headers = {"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "identity"}
    if getattr(song, "default_download_headers", None):
        headers.update({k: v for k, v in song.default_download_headers.items() if v})
    ref = REFERERS.get(platform)
    if ref:
        headers.setdefault("Referer", ref)
    return headers


def fetch_to_file(url, path, platform, song, timeout=(8, 60)):
    headers = _headers(platform, song)
    cookies = getattr(song, "default_download_cookies", None) or {}
    with requests.get(url, headers=headers, cookies=cookies or None, stream=True,
                      timeout=timeout, verify=False) as resp:
        if resp.status_code >= 400:
            raise DownloadFailed(f"HTTP {resp.status_code}")
        total = 0
        with open(path, "wb") as fp:
            for chunk in resp.iter_content(chunk_size=256 * 1024):
                if chunk:
                    fp.write(chunk)
                    total += len(chunk)
                    # 音源异常时可能返回一个无穷流，不设上限会把磁盘写满
                    if total > MAX_TRACK_BYTES:
                        raise DownloadFailed("音源文件异常（超过单曲上限）")
        if total < 20 * 1024:
            raise DownloadFailed("文件过小，疑似无效音源")
        return total


def _cache_path(file_id, ext):
    sub = Config.CACHE_DIR / file_id[:2]
    sub.mkdir(parents=True, exist_ok=True)
    return sub / f"{file_id}.{ext}"


def _resolve(track_key, song, platform, target_quality):
    """拿到可用的 SongInfo；链接失效则按歌名重新检索一次。"""
    need_flac = target_quality == "flac"
    if song is not None and getattr(song, "download_url", None) and not need_flac:
        return song
    name = (song.song_name if song else "") or ""
    singers = (song.singers if song else "") or ""
    if not name:
        raise DownloadFailed("缺少曲目信息")
    if need_flac:
        song = None  # 无损必须重新按 flac 档解析
    keyword = f"{name} {singers.split(',')[0]}".strip()
    res = platforms.search_specific(platform, keyword, profile="flac" if need_flac else "mp3")
    cands = res.get("tracks") or []
    if not cands:
        raise DownloadFailed("该平台未检索到可下载音源")
    if need_flac:
        cands = [c for c in cands if transcode.is_lossless(c.get("ext", ""))] or cands
    best = _pick_best(cands, name, singers, need_lossless=need_flac)
    hit = platforms.TRACKS.get(best["track_key"])
    if not hit:
        raise DownloadFailed("音源解析失败")
    return hit[0]


def _pick_best(cands, name, singers, need_lossless=False):
    def score(t):
        s = 0
        if t["song_name"] == name:
            s += 3
        elif name and name in t["song_name"]:
            s += 1
        first_singer = (singers or "").split(",")[0].strip()
        if first_singer and first_singer in (t["singers"] or ""):
            s += 2
        if need_lossless:
            # 无损档优先挑真正的无损文件，避免挑到 mp3 后判定失败
            s += 10 if transcode.is_lossless(t.get("ext", "")) else 0
        return s
    return max(cands, key=score)


def ensure_file(song, platform, target_quality="mp3", track_meta=None, on_status=None):
    """主入口：确保磁盘上有该曲目的目标音质文件，返回 files 表行。"""
    def status(msg):
        if on_status:
            on_status(msg)

    status("resolving")
    song = _resolve(None, song, platform, target_quality)
    if song is None or not getattr(song, "download_url", None):
        raise DownloadFailed("无法解析下载直链")

    file_id = file_id_of(platform, song, target_quality)
    row = db.get_file(file_id)
    if row and os.path.exists(row["path"]):
        db.touch_file(file_id)
        status("cached")
        return row

    src_ext = (song.ext or "").lstrip(".").lower()
    if target_quality == "flac" and not transcode.is_lossless(src_ext):
        raise LosslessUnavailable(f"该音源无无损版本（{src_ext or '未知'}）")

    tmp_dir = Config.TMP_DIR
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_src = tmp_dir / f"{file_id}.src"
    status("downloading")
    size = fetch_to_file(song.download_url, str(tmp_src), platform, song)

    try:
        if target_quality == "flac":
            final_ext, final_path = src_ext, _cache_path(file_id, src_ext)
            os.replace(tmp_src, final_path)
        else:
            if src_ext == "mp3":
                final_ext, final_path = "mp3", _cache_path(file_id, "mp3")
                os.replace(tmp_src, final_path)
            else:
                status("transcoding")
                final_ext, final_path = "mp3", _cache_path(file_id, "mp3")
                ok = transcode.to_mp3(str(tmp_src), str(final_path), Config.MP3_BITRATE)
                if not ok:
                    raise DownloadFailed("转码失败")
    finally:
        if tmp_src.exists():
            try:
                tmp_src.unlink()
            except OSError:
                pass

    status("tagging")
    if final_ext == "mp3":
        cover = tagger.read_cover_bytes(getattr(song, "cover_url", "") or "")
        tagger.write_tags(
            str(final_path),
            title=getattr(song, "song_name", "") or "",
            artist=getattr(song, "singers", "") or "",
            album=getattr(song, "album", "") or "",
            cover=cover,
            lyric=getattr(song, "lyric", "") or "",
        )

    duration = transcode.probe_duration(str(final_path))
    if not duration and getattr(song, "duration_s", None):
        duration = int(song.duration_s)
    db.upsert_file(
        file_id, file_id, str(final_path), final_ext, os.path.getsize(final_path),
        target_quality, getattr(song, "song_name", "") or "", getattr(song, "singers", "") or "",
        duration, platform,
    )
    status("done")
    return db.get_file(file_id)


def cleanup_cache():
    """按 TTL + 容量上限清理缓存文件。"""
    removed = 0
    # ZIP 兜底清理：正常情况下响应结束就删了，这里防「发到一半断开」之类的残留
    zip_dir = Config.TMP_DIR / "zip"
    if zip_dir.exists():
        cutoff = time.time() - 3600
        for p in zip_dir.glob("*.zip"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    removed += 1
            except OSError:
                continue
    for row in db.expired_files(Config.FILE_KEEP_HOURS):
        try:
            if os.path.exists(row["path"]):
                os.remove(row["path"])
        except OSError:
            pass
        db.delete_file_row(row["id"])
        removed += 1
    limit = Config.CACHE_MAX_GB * 1024 ** 3
    if db.total_cache_size() > limit:
        for row in db.query("SELECT * FROM files ORDER BY last_access ASC LIMIT 200"):
            if db.total_cache_size() <= limit * 0.8:
                break
            try:
                if os.path.exists(row["path"]):
                    os.remove(row["path"])
            except OSError:
                pass
            db.delete_file_row(row["id"])
            removed += 1
    db.rate_gc(int(time.time()) - 7 * 86400)
    return removed
