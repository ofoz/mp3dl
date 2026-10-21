"""下载任务队列：单曲 / 歌单批量，进度落库，ZIP 打包"""
import os
import uuid
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor

from ..config import Config
from .. import db
from . import pipeline, platforms, pricing


EXECUTOR = ThreadPoolExecutor(max_workers=Config.JOB_WORKERS, thread_name_prefix="mp3job")
_counters = {}
_lock = threading.Lock()


def create_job(kind, tracks, quality, user_id, ip, title=""):
    tracks = tracks[: Config.MAX_PLAYLIST_TRACKS]
    job_id = uuid.uuid4().hex
    db.create_job(job_id, kind, user_id, ip, quality, title, len(tracks))
    for i, track in enumerate(tracks):
        db.add_job_item(job_id, i, track, quality)
    return job_id


def start(job_id):
    items = db.get_job_items(job_id)
    if not items:
        db.update_job(job_id, status="failed")
        return
    db.update_job(job_id, status="running")
    with _lock:
        _counters[job_id] = {"remaining": len(items)}
    for item in items:
        EXECUTOR.submit(_run_item, job_id, item["id"])


def _run_item(job_id, item_id):
    job = db.get_job(job_id)
    if not job or job["status"] == "cancelled":
        _finish_one(job_id)
        return
    item = db.one("SELECT * FROM job_items WHERE id=?", (item_id,))
    if not item:
        _finish_one(job_id)
        return
    try:
        db.update_item(item_id, status="running")
        song, platform = _pick_song(item)
        if song is None:
            # 该平台搜不到，跨平台兜底
            song, platform = _cross_platform_fallback(item)
        if song is None:
            raise pipeline.DownloadFailed("所有平台均未找到可用音源")
        row = pipeline.ensure_file(
            song, platform, job["quality"],
            on_status=lambda s: db.update_item(item_id, status=s),
        )
        db.update_item(item_id, status="done", file_id=row["token"], source_used=platform,
                       song_name=row.get("song_name") or item["song_name"],
                       singers=row.get("singers") or item["singers"])
        db.bump_job(job_id, "finished")
        pricing.commit_ref(_ref(job_id, item["idx"]))
    except pipeline.LosslessUnavailable:
        db.update_item(item_id, status="failed", error="该音源无无损版本")
        db.bump_job(job_id, "failed")
        pricing.refund_ref(_ref(job_id, item["idx"]), "该音源无无损版本，已退回")
    except Exception as err:
        db.update_item(item_id, status="failed", error=str(err)[:180])
        db.bump_job(job_id, "failed")
        pricing.refund_ref(_ref(job_id, item["idx"]), "该曲目下载失败，已退回")
    finally:
        _finish_one(job_id)


def _ref(job_id, idx):
    """计费记录与任务曲目一一对应：job_id + 曲目序号。"""
    return f"{job_id}:{int(idx)}"


def _pick_song(item):
    hit = platforms.TRACKS.get(item["track_key"]) if item["track_key"] else None
    if hit:
        return hit[0], hit[1]
    res = platforms.search_specific(item["platform"], f"{item['song_name']} {item['singers']}".strip())
    cands = res.get("tracks") or []
    if not cands:
        return None, item["platform"]
    got = platforms.TRACKS.get(cands[0]["track_key"])
    return (got[0], got[1]) if got else (None, item["platform"])


def _cross_platform_fallback(item):
    keyword = f"{item['song_name']} {item['singers']}".strip()
    for src in platforms.DEFAULT_SOURCES:
        if src == item["platform"]:
            continue
        try:
            res = platforms.search_specific(src, keyword)
        except Exception:
            continue
        cands = res.get("tracks") or []
        if not cands:
            continue
        got = platforms.TRACKS.get(cands[0]["track_key"])
        if got:
            return got[0], got[1]
    return None, item["platform"]


def _finish_one(job_id):
    with _lock:
        state = _counters.get(job_id)
        if not state:
            return
        state["remaining"] -= 1
        finished = state["remaining"] <= 0
        if finished:
            _counters.pop(job_id, None)
    if not finished:
        return
    job = db.get_job(job_id)
    if not job:
        return
    total, failed = job["total"], job["failed"]
    status = "done" if failed == 0 else ("failed" if failed >= total else "partial")
    db.update_job(job_id, status=status, finished=total - failed)


def job_detail(job_id):
    job = db.get_job(job_id)
    if not job:
        return None
    items = db.get_job_items(job_id)
    return {
        "id": job["id"],
        "kind": job["kind"],
        "title": job["title"],
        "quality": job["quality"],
        "status": job["status"],
        "total": job["total"],
        "finished": job["finished"],
        "failed": job["failed"],
        "created_at": job["created_at"],
        "items": [
            {
                "idx": it["idx"],
                "song_name": it["song_name"],
                "singers": it["singers"],
                "album": it["album"],
                "cover_url": it["cover_url"],
                "status": it["status"],
                "error": it["error"],
                "file_id": it["file_id"],
                "platform": it["platform"],
                "source_used": it["source_used"],
            }
            for it in items
        ],
    }


def build_zip(job_id, dst_path):
    job = db.get_job(job_id)
    if not job:
        raise FileNotFoundError("任务不存在")
    rows = db.query(
        """SELECT f.*, i.song_name AS i_name, i.singers AS i_singers
           FROM job_items i JOIN files f ON f.token = i.file_id
           WHERE i.job_id=? ORDER BY i.idx ASC""",
        (job_id,),
    )
    if not rows:
        raise FileNotFoundError("没有可打包的文件")
    used = set()
    with zipfile.ZipFile(dst_path, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for row in rows:
            if not os.path.exists(row["path"]):
                continue
            name = _safe_name(f"{row['song_name']} - {row['singers']}") + f".{row['ext']}"
            base, i = name, 1
            while name in used:
                stem, ext = os.path.splitext(base)
                name = f"{stem} ({i}){ext}"
                i += 1
            used.add(name)
            zf.write(row["path"], arcname=name)
    return dst_path


def _safe_name(name):
    for ch in '<>:"/\\|?*\n\r\t':
        name = name.replace(ch, "_")
    return (name or "track").strip()[:120]
