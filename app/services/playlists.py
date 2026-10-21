"""歌单解析：只支持粘贴分享链接（网易云 / QQ音乐 / 酷狗）

大歌单解析要几十秒（每首都要解析直链），所以做成后台任务 + 前端轮询，
避免网关 60s 超时直接把请求掐断。
"""
import threading
import time
import uuid
from urllib.parse import parse_qs, urlparse

from ..config import Config
from . import platforms, quality

# 域名 -> 平台（含已下线平台，用于给出明确提示）
HOST_RULES = [
    ("163.com", "NeteaseMusicClient"),
    ("music.126.net", "NeteaseMusicClient"),
    ("y.qq.com", "QQMusicClient"),
    ("qq.com", "QQMusicClient"),
    ("kugou.com", "KugouMusicClient"),
    ("kuwo.cn", "KuwoMusicClient"),
    ("migu.cn", "MiguMusicClient"),
    ("music.migu.cn", "MiguMusicClient"),
    ("91q.com", "QianqianMusicClient"),
    ("qishui.douyin.com", "SodaMusicClient"),
]

_tasks = {}
_lock = threading.Lock()
TASK_TTL = 1800


def detect_source(url: str):
    host = (urlparse(url).hostname or "").lower()
    for suffix, source in HOST_RULES:
        if host == suffix or host.endswith("." + suffix):
            return source
    return None


def _clean_title(platform: str, url: str, count: int = 0) -> str:
    label = platforms.PLATFORMS.get(platform, {}).get("label", platform)
    pid = ""
    try:
        q = parse_qs(urlparse(url).query)
        pid = (q.get("id") or q.get("disstid") or q.get("playlistId") or [""])[0]
        if not pid:
            frag = urlparse(url).fragment
            if frag:
                q2 = parse_qs(urlparse(frag).query)
                pid = (q2.get("id") or q2.get("playlistId") or [""])[0]
        if not pid:
            pid = urlparse(url).path.rstrip("/").split("/")[-1].removesuffix(".html")
    except Exception:
        pass
    name = _fetch_playlist_name(platform, pid) if pid else ""
    if name:
        return name
    return f"{label}歌单" + (f"（{count}首）" if count else "")


def _fetch_playlist_name(platform: str, pid: str) -> str:
    """尽力取到歌单真名，取不到不影响主流程。"""
    import requests
    ua = {"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"}
    try:
        if platform == "NeteaseMusicClient":
            resp = requests.post("https://music.163.com/api/v6/playlist/detail",
                                 data={"id": pid}, headers=ua, timeout=6)
            return ((resp.json() or {}).get("playlist") or {}).get("name") or ""
        if platform == "QQMusicClient":
            resp = requests.get("https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg",
                                params={"disstid": pid, "type": "1", "json": "1", "utf8": "1"},
                                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://y.qq.com/"},
                                timeout=6)
            data = resp.json() or {}
            return ((data.get("cdlist") or [{}])[0] or {}).get("dissname") or ""
    except Exception:
        return ""
    return ""


def start_parse(url: str) -> str:
    task_id = uuid.uuid4().hex
    with _lock:
        _gc()
        _tasks[task_id] = {"status": "running", "started": time.time(), "tracks": [], "title": "", "error": ""}
    threading.Thread(target=_run_parse, args=(task_id, url), daemon=True).start()
    return task_id


def get_parse(task_id):
    with _lock:
        task = _tasks.get(task_id)
        if not task:
            return None
        return {
            "task_id": task_id,
            "status": task["status"],
            "title": task.get("title", ""),
            "error": task.get("error", ""),
            "total": len(task.get("tracks", [])),
            "tracks": task.get("tracks", []),
            "elapsed": round(time.time() - task["started"], 1),
        }


def _run_parse(task_id, url):
    try:
        source = detect_source(url)
        if not source:
            raise ValueError("暂不支持该链接，请粘贴网易云 / QQ音乐 / 酷狗的歌单链接")
        if not platforms.is_enabled(source):
            meta = platforms.PLATFORMS.get(source, {})
            raise ValueError(f"{meta.get('label', source)} {meta.get('offline_reason', '已下线')}")
        if not platforms.PLATFORMS.get(source, {}).get("playlist"):
            raise ValueError(f"{platforms.PLATFORMS.get(source, {}).get('label', source)} 暂不支持歌单解析")

        with quality.use_profile(source, "mp3"):
            client = platforms.get_client(source)
            song_infos = client.parseplaylist(url) or []

        tracks, seen = [], set()
        for song in song_infos[: Config.MAX_PLAYLIST_TRACKS]:
            name = (song.song_name or "").strip()
            if not name:
                continue
            dedup_key = (name, (song.singers or "").strip())
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            platforms.TRACKS.put(song, source)
            tracks.append(platforms.track_payload(song, source))

        with _lock:
            task = _tasks.get(task_id)
            if task is not None:
                task.update({
                    "status": "done" if tracks else "empty",
                    "tracks": tracks,
                    "title": _clean_title(source, url, len(tracks)),
                    "error": "" if tracks else "没有解析到曲目，可能是私密歌单或链接已失效",
                })
    except Exception as err:
        with _lock:
            task = _tasks.get(task_id)
            if task is not None:
                task.update({"status": "failed", "error": str(err)[:200]})


def _gc():
    cutoff = time.time() - TASK_TTL
    for key in [k for k, v in _tasks.items() if v["started"] < cutoff]:
        _tasks.pop(key, None)
