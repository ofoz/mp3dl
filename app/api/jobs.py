"""任务：进度查询 / 我的任务 / ZIP 打包（都要登录）"""
import os

from flask import Blueprint, g, jsonify, send_file

from .. import db
from ..config import Config
from ..services import jobs

bp = Blueprint("jobs", __name__, url_prefix="/api/jobs")


def _require_login():
    return jsonify({"error": "请先登录", "code": "login_required"}), 401


def _owner(job, user):
    return bool(user and (job["user_id"] == user["id"] or user["is_admin"]))


@bp.get("/<job_id>")
def detail(job_id):
    user = getattr(g, "user", None)
    if not user:
        return _require_login()
    job = db.get_job(job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    if not _owner(job, user):
        return jsonify({"error": "无权访问该任务"}), 403
    data = jobs.job_detail(job_id)
    data["can_zip"] = data["finished"] > 0
    return jsonify(data)


@bp.get("")
def my_jobs():
    user = getattr(g, "user", None)
    if not user:
        return jsonify({"jobs": []})
    rows = db.recent_jobs("", user["id"], limit=15)
    out = []
    for r in rows:
        detail = jobs.job_detail(r["id"]) or {}
        out.append({
            "id": r["id"], "kind": r["kind"], "title": r["title"], "status": r["status"],
            "total": r["total"], "finished": r["finished"], "failed": r["failed"],
            "quality": r["quality"], "created_at": r["created_at"],
            # 批量任务不做 ZIP（用户要的就是逐个文件），歌单/单曲仍可打包
            "zip": r["kind"] != "batch",
            "items": [
                {"song_name": it.get("song_name") or "", "singers": it.get("singers") or "",
                 "status": it.get("status"), "error": it.get("error"),
                 "file_id": it.get("file_id"), "source_used": it.get("source_used")}
                for it in detail.get("items", [])
            ],
        })
    return jsonify({"jobs": out})


@bp.get("/<job_id>/zip")
def zip_download(job_id):
    user = getattr(g, "user", None)
    if not user:
        return _require_login()
    job = db.get_job(job_id)
    if not job:
        return jsonify({"error": "任务不存在"}), 404
    if not _owner(job, user):
        return jsonify({"error": "无权访问该任务"}), 403
    if job["finished"] <= 0:
        return jsonify({"error": "还没有已完成的曲目"}), 400

    # ZIP 写在站点自己的 tmp/zip 下，而不是系统临时目录：
    # 同一个任务重复打包直接覆盖同名文件，不会一次泄漏几十上百 MB；
    # 万一响应没走完，pipeline 的定时清理也会兜底删除。
    zip_dir = Config.TMP_DIR / "zip"
    zip_dir.mkdir(parents=True, exist_ok=True)
    dst = str(zip_dir / f"{job['id']}.zip")
    try:
        jobs.build_zip(job_id, dst)
    except FileNotFoundError as err:
        _unlink(dst)
        return jsonify({"error": str(err)}), 404
    except Exception:
        _unlink(dst)
        raise

    name = _zip_name(job["title"])
    resp = send_file(dst, as_attachment=True, download_name=name,
                     mimetype="application/zip")
    # 正常情况响应发完就删；删不掉也没关系，定时任务会兜底
    resp.call_on_close(lambda: _unlink(dst))
    return resp


def _unlink(path):
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


def _zip_name(title):
    """文件名只用于 Content-Disposition，仍要挡掉能污染响应头的字符。"""
    base = str(title or "歌单")
    for ch in '<>:"/\\|?*\r\n\t':
        base = base.replace(ch, "_")
    return base.strip()[:60] + ".zip"
