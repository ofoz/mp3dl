"""歌单：链接解析（异步任务）+ 批量下载（逐首计费）"""
from flask import Blueprint, g, jsonify, request

from .. import ratelimit, security
from ..config import Config
from ..services import platforms, playlists, pricing
from . import download

bp = Blueprint("playlist", __name__, url_prefix="/api/playlist")


@bp.post("/parse")
def parse():
    ratelimit.check_search(security.client_ip())
    data = request.get_json(silent=True) or {}
    url = str(data.get("url", "")).strip()
    if not url:
        return jsonify({"error": "请粘贴歌单链接"}), 400
    if not url.lower().startswith("http"):
        return jsonify({"error": "链接格式不正确"}), 400
    source = playlists.detect_source(url)
    enabled = [(k, v) for k, v in platforms.PLATFORMS.items()
               if v.get("playlist") and v.get("enabled", True)]
    if not source:
        return jsonify({
            "error": "暂不支持该链接",
            "hint": "支持 " + " / ".join(v["label"] for _, v in enabled) + " 的歌单分享链接",
            "supported": [{"key": k, "label": v["label"], "playlist": v["playlist"]}
                          for k, v in enabled],
        }), 400
    if not platforms.is_enabled(source):
        meta = platforms.PLATFORMS.get(source, {})
        return jsonify({
            "error": f"{meta.get('label', source)} {meta.get('offline_reason', '已下线')}",
            "code": "platform_offline",
        }), 400
    task_id = playlists.start_parse(url)
    return jsonify({"task_id": task_id, "platform": source,
                    "platform_label": platforms.PLATFORMS.get(source, {}).get("label", source)})


@bp.get("/parse/<task_id>")
def parse_status(task_id):
    task = playlists.get_parse(task_id)
    if not task:
        return jsonify({"error": "解析任务已过期，请重新提交"}), 404
    return jsonify(task)


@bp.post("/download")
def download_playlist():
    user = getattr(g, "user", None)
    if not user:
        return jsonify({"error": "批量下载需要先登录", "code": "login_required"}), 401

    data = request.get_json(silent=True) or {}
    track_keys = data.get("track_keys") or []
    quality = (data.get("quality") or "mp3").lower()
    title = str(data.get("title") or "歌单")[:60]

    if not isinstance(track_keys, list) or not track_keys:
        return jsonify({"error": "请至少选择一首歌"}), 400
    if len(track_keys) > Config.MAX_PLAYLIST_TRACKS:
        return jsonify({"error": f"单次最多 {Config.MAX_PLAYLIST_TRACKS} 首"}), 400
    if quality == "flac":
        return jsonify({
            "error": "批量打包暂只支持 MP3 320k",
            "hint": "无损音质请单曲下载（直连，速度更快）",
        }), 400

    tracks = []
    for key in track_keys:
        hit = platforms.TRACKS.get(key)
        if not hit:
            continue
        song, platform = hit
        if not platforms.is_enabled(platform):
            continue
        tracks.append(platforms.track_payload(song, platform))
    if not tracks:
        return jsonify({"error": "曲目已过期，请重新解析歌单", "code": "track_expired"}), 404

    # 先算总账再动手：免费额度抵几首、还要多少积分，一次说清楚
    plan = pricing.quote(user["id"], [
        {"quality": quality, "transcode": platforms.needs_transcode(t["platform"])} for t in tracks
    ])
    if not plan["ok"]:
        return jsonify({
            "error": (f"积分不足：{len(tracks)} 首需 {plan['credits']} 积分"
                      f"（免费额度可抵 {plan['free']} 首），当前余额 {plan['balance']} 积分，"
                      f"还差 {plan['short']} 积分"),
            "code": "credits_insufficient",
            "need": plan["credits"], "balance": plan["balance"], "short": plan["short"],
            "wallet": pricing.wallet(user["id"]),
        }), 402

    ratelimit.check_download(security.client_ip(), len(tracks))
    job_id = download.create_paid_job(user, tracks, quality, kind="playlist", title=title)
    return jsonify({
        "mode": "job", "job_id": job_id, "total": len(tracks), "quality": quality,
        "plan": plan, "wallet": pricing.wallet(user["id"]),
    })
