"""下载通道编排 + 计费

通道：
- 普通 MP3：优先让浏览器直连音源、在用户机器上写 ID3（本站零音频流量）；
  不满足条件（需转码 / 无 CORS / 混合内容）自动降级为服务端流水线。
- FLAC：签名直连 302，流量全在 CDN。
- 需转码（QQ）与批量打包：服务端任务。

计费：所有下载都必须登录。普通 MP3 先吃每日免费额度，超出按积分；
QQ（服务端转码）与无损直接按积分。单曲任务失败会退回，不白扣。
"""
import os
import time

from flask import Blueprint, Response, g, jsonify, redirect, request, send_file

from .. import db, ratelimit, security
from ..config import Config
from ..services import direct, jobs, pipeline, platforms, pricing, tagger

bp = Blueprint("download", __name__, url_prefix="/api")

REUSE_WINDOW = 1800  # 直连失败改走服务端时，允许复用这笔扣费的时间窗（秒）


def _login_required():
    return jsonify({
        "error": "下载需要先登录（登录后每天有免费额度）",
        "code": "login_required",
    }), 401


def _check_quality(quality):
    quality = (quality or "mp3").lower()
    if quality not in {"mp3", "flac"}:
        raise ValueError("不支持的音质")
    return quality


def _wallet(user):
    return pricing.wallet(user["id"]) if user else None


def _reusable_charge(user, charge_id, track_key, platform="", quality=""):
    """直连失败 -> 服务端中转时复用同一笔扣费，避免用户被扣两次。

    只认本人的、未退回的、同一首、同一音质、同一平台的记录：
    否则可以先用免费额度换一笔 1 首的 charge，再拿它去抵 50 积分的无损。
    """
    if not charge_id:
        return None
    try:
        row = db.get_charge(int(charge_id))
    except (TypeError, ValueError):
        return None
    if not row or row["user_id"] != user["id"] or row["status"] == "refunded":
        return None
    # 已经被挂到某次交付上的 charge 不能再复用：
    # 否则同一笔扣费可以反复喂给 /api/download/batch，一次付费换来无限次任务。
    if (row["ref"] or "").strip():
        return None
    if row["track"] and track_key and row["track"] != track_key:
        return None
    if platform and row["platform"] and row["platform"] != platform:
        return None
    if quality and row["quality"] and row["quality"] != quality:
        return None
    if time.time() - int(row["created_at"] or 0) > REUSE_WINDOW:
        return None
    return {"id": row["id"], "kind": row["kind"], "amount": row["amount"],
            "free": row["kind"] == "free", "reuse": True}


def _bill(user, platform, quality, track_key, reuse=None):
    if reuse:
        return reuse
    return pricing.charge(
        user["id"], platform, quality,
        transcode=platforms.needs_transcode(platform),
        track=track_key,
    )


@bp.post("/download")
def download():
    user = getattr(g, "user", None)
    if not user:
        return _login_required()

    data = request.get_json(silent=True) or {}
    track_key = str(data.get("track_key", "")).strip()
    try:
        quality = _check_quality(data.get("quality"))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    mode = str(data.get("mode", "auto")).lower()

    hit = _resolve_song(track_key)
    if not hit[0]:
        return jsonify({"error": "曲目已过期，请重新搜索", "code": "track_expired"}), 404
    song, platform = hit
    if not platforms.is_enabled(platform):
        return jsonify({"error": "该音源已下线，请换一个平台", "code": "platform_offline"}), 400

    ratelimit.check_download(security.client_ip())
    reuse = _reusable_charge(user, data.get("reuse_charge_id"), track_key, platform, quality)

    # 无损档 / 显式直连：只下发签名直链，流量全部走 CDN
    if quality == "flac" or mode == "direct":
        return _direct_download(song, platform, quality, user, reuse, track_key)

    # MP3 首选：浏览器自己去音源取字节，本地写 ID3，服务器只发几 KB 标签
    if quality == "mp3" and mode != "server" and Config.MP3_BROWSER_FIRST:
        resp = _browser_download(song, platform, quality, user, reuse, track_key)
        if resp is not None:
            return resp

    return _job_response(song, platform, quality, user, reuse, track_key)


def _resolve_song(track_key):
    hit = platforms.TRACKS.get(track_key)
    if not hit:
        return None, None
    return hit


def _browser_url(song, page_https, origin):
    """浏览器能不能自己取到这首的字节？能就返回可 fetch 的直链。

    两个硬条件：
    1. 源文件本身就是 mp3 —— 其他格式（ogg/flac）要转码，只能在服务器做；
    2. CDN 允许跨域（且 https 页面下不能是 http 直链）。
    """
    url = getattr(song, "download_url", None)
    if not url:
        return None
    if (getattr(song, "ext", "") or "").lstrip(".").lower() != "mp3":
        return None
    final_url, ok = direct.prepare(url, page_https, origin)
    return final_url if ok else None


def _browser_download(song, platform, quality, user, reuse, track_key):
    """判定能否让浏览器直连；可以就返回标签数据，否则返回 None 走服务端。"""
    page_https = bool(request.is_secure or Config.SITE_HTTPS)
    origin = request.host_url.rstrip("/")
    final_url = _browser_url(song, page_https, origin)
    if not final_url:
        return None

    # 确认能直连后才计费：走到这里一定会给用户一条下载通道
    charge = _bill(user, platform, quality, track_key, reuse)
    pricing.commit(charge)

    token = direct.issue(final_url, song.song_name or "", song.singers or "", platform)

    # 封面优先也走 CDN 直连（几十上百 KB，能省则省），拿不到才退回本站代理
    cover = tagger.usable_cover(getattr(song, "cover_url", "") or "")
    cover_url = ""
    if cover:
        final_cover, cover_ok = direct.prepare(cover, page_https, origin)
        cover_url = final_cover if cover_ok else f"/api/cover/{direct.issue(cover, 'cover', platform, platform)}"

    resp = jsonify({
        "mode": "browser",
        "url": f"/api/dl/{token}",
        "filename": _safe_filename(song.song_name, song.singers, "mp3"),
        "size_hint": int(getattr(song, "file_size_bytes", 0) or 0),
        "quality": quality,
        "charge_id": charge["id"],
        "charged": _charged_payload(charge),
        "wallet": _wallet(user),
        "tags": {
            "title": getattr(song, "song_name", "") or "",
            "artist": getattr(song, "singers", "") or "",
            "album": getattr(song, "album", "") or "",
            "lyric": getattr(song, "lyric", "") or "",
            "cover": cover_url,
        },
    })
    resp.headers["X-Download-Mode"] = "browser"
    return resp


def _lossless_url(song, platform):
    """无损能否拿到可直连的源；返回 (target, url) 或 (None, None)。"""
    try:
        target = pipeline._resolve(None, song, platform, "flac")
    except Exception:
        return None, None
    if not pipeline.transcode.is_lossless(getattr(target, "ext", "")):
        return None, None
    url = getattr(target, "download_url", None)
    if not url or not str(url).startswith("http"):
        return None, None
    return target, url


def _why_server(song, platform):
    ext = (getattr(song, "ext", "") or "").lstrip(".").lower()
    if ext and ext != "mp3":
        return f"源站只提供 {ext}，需服务端转码"
    return "源站不允许浏览器直连"


@bp.post("/download/batch/direct")
def download_batch_direct():
    """批量下载的「前端串行直连」通道：服务端零音频流量。

    服务端只做三件事：解析曲目、判定每首能不能直连、签发直链令牌 + 标签数据。
    音频字节由浏览器自己从 CDN 拉，在用户机器上写 ID3 后落盘，
    单首服务端流量从约 9 MB 降到约 3 KB。

    拿不到直连的（需转码 / CDN 无 CORS / 无损缺失）原样返回，
    前端再统一交给 /api/download/batch 走服务端任务兜底。
    """
    user = getattr(g, "user", None)
    if not user:
        return _login_required()

    data = request.get_json(silent=True) or {}
    raw = data.get("track_keys") or []
    if not isinstance(raw, list) or not raw:
        return jsonify({"error": "请先勾选要下载的歌曲"}), 400
    try:
        quality = _check_quality(data.get("quality"))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400

    keys = []
    for item in raw:
        key = str(item or "").strip()
        if key and key not in keys:
            keys.append(key)
    if len(keys) > Config.MAX_BATCH_TRACKS:
        return jsonify({
            "error": f"单次最多批量下载 {Config.MAX_BATCH_TRACKS} 首，请分批提交",
            "code": "too_many",
        }), 400

    picked, skipped = [], []
    for key in keys:
        song, platform = _resolve_song(key)
        if not song:
            skipped.append({"track_key": key, "error": "曲目已过期"})
        elif not platforms.is_enabled(platform):
            label = platforms.PLATFORMS.get(platform, {}).get("label", platform)
            skipped.append({"track_key": key, "error": f"{label} 已下线"})
        else:
            picked.append((key, song, platform))
    if not picked:
        return jsonify({
            "error": "勾选的曲目都已过期，请重新搜索后再下载",
            "code": "track_expired",
        }), 404

    ratelimit.check_download(security.client_ip(), len(picked))

    page_https = bool(request.is_secure or Config.SITE_HTTPS)
    origin = request.host_url.rstrip("/")

    ready, need_server = [], []
    for key, song, platform in picked:
        if quality == "flac":
            target, url = _lossless_url(song, platform)
            if target and (direct.is_https(url) or not page_https):
                ready.append({"track_key": key, "mode": "direct", "song": target,
                              "platform": platform, "url": url})
            else:
                need_server.append({"track_key": key, "reason": "源站无损不可直连"})
            continue
        final_url = _browser_url(song, page_https, origin)
        if final_url:
            ready.append({"track_key": key, "mode": "browser", "song": song,
                          "platform": platform, "url": final_url})
        else:
            need_server.append({"track_key": key, "reason": _why_server(song, platform)})

    # 只为「确实能给通道」的曲目扣费；中途余额不够就把已扣的整批退回
    if ready:
        plan = pricing.quote(user["id"], [
            {"quality": quality, "transcode": platforms.needs_transcode(x["platform"])}
            for x in ready
        ])
        if not plan["ok"]:
            return jsonify({
                "error": (f"积分不足：{len(ready)} 首需 {plan['credits']} 积分"
                          f"（免费额度可抵 {plan['free']} 首），当前余额 {plan['balance']} 积分，"
                          f"还差 {plan['short']} 积分"),
                "code": "credits_insufficient",
                "need": plan["credits"], "balance": plan["balance"], "short": plan["short"],
                "wallet": pricing.wallet(user["id"]),
            }), 402

        done = []
        try:
            for item in ready:
                charge = pricing.charge(
                    user["id"], item["platform"], quality,
                    transcode=platforms.needs_transcode(item["platform"]),
                    track=item["track_key"],
                )
                pricing.commit(charge)
                done.append(charge)
                item["charge"] = charge
        except pricing.InsufficientCredits as err:
            for charge in done:
                pricing.refund(charge["id"], "批量直连中止，已退回")
            return jsonify({
                "error": str(err), "code": "credits_insufficient",
                "need": err.need, "balance": err.balance, "short": err.short,
                "wallet": pricing.wallet(user["id"]),
            }), 402

    out = []
    for item in ready:
        song = item["song"]
        token = direct.issue(item["url"], song.song_name or "", song.singers or "",
                             item["platform"])
        row = {
            "track_key": item["track_key"],
            "mode": item["mode"],
            "url": f"/api/dl/{token}",
            "filename": _safe_filename(song.song_name, song.singers,
                                       getattr(song, "ext", quality)),
            "size_hint": int(getattr(song, "file_size_bytes", 0) or 0),
            "charge_id": item["charge"]["id"],
            "charged": _charged_payload(item["charge"]),
        }
        if item["mode"] == "browser":
            cover = tagger.usable_cover(getattr(song, "cover_url", "") or "")
            cover_url = ""
            if cover:
                final_cover, cover_ok = direct.prepare(cover, page_https, origin)
                cover_url = (final_cover if cover_ok
                             else f"/api/cover/{direct.issue(cover, 'cover', item['platform'], item['platform'])}")
            row["tags"] = {
                "title": getattr(song, "song_name", "") or "",
                "artist": getattr(song, "singers", "") or "",
                "album": getattr(song, "album", "") or "",
                "lyric": getattr(song, "lyric", "") or "",
                "cover": cover_url,
            }
        out.append(row)

    return jsonify({
        "mode": "direct_batch",
        "ready": out,
        "need_server": need_server,
        "skipped": skipped,
        "quality": quality,
        "wallet": pricing.wallet(user["id"]),
    })


@bp.post("/download/batch")
def download_batch():
    """服务端批量兜底：给每首各建一个任务，逐首计费、逐首交付，不打包 ZIP。

    正常情况下前端已经在浏览器里直连交付完了，只有拿不到直连的曲目会走到这里。
    前端可以用 `reuse_charge_ids`（{track_key: charge_id}）把直连阶段已扣的那笔
    挂到新任务上，避免失败降级被扣两次。
    """
    user = getattr(g, "user", None)
    if not user:
        return _login_required()

    data = request.get_json(silent=True) or {}
    raw = data.get("track_keys") or []
    if not isinstance(raw, list) or not raw:
        return jsonify({"error": "请先勾选要下载的歌曲"}), 400
    try:
        quality = _check_quality(data.get("quality"))
    except ValueError as err:
        return jsonify({"error": str(err)}), 400

    keys = []
    for item in raw:
        key = str(item or "").strip()
        if key and key not in keys:
            keys.append(key)
    if len(keys) > Config.MAX_BATCH_TRACKS:
        return jsonify({
            "error": f"单次最多批量下载 {Config.MAX_BATCH_TRACKS} 首，请分批提交",
            "code": "too_many",
        }), 400

    picked, skipped = [], []
    for key in keys:
        song, platform = _resolve_song(key)
        if not song:
            skipped.append({"track_key": key, "error": "曲目已过期"})
            continue
        if not platforms.is_enabled(platform):
            label = platforms.PLATFORMS.get(platform, {}).get("label", platform)
            skipped.append({"track_key": key, "error": f"{label} 已下线"})
            continue
        picked.append((key, song, platform))
    if not picked:
        return jsonify({
            "error": "勾选的曲目都已过期，请重新搜索后再下载",
            "code": "track_expired",
        }), 404

    # 直连阶段已经扣过的曲目，这里只挂账不再收钱
    reuse_raw = data.get("reuse_charge_ids") or {}
    reuse_map = {}
    if isinstance(reuse_raw, dict):
        for key, song, platform in picked:
            hit = _reusable_charge(user, reuse_raw.get(key), key, platform, quality)
            if hit:
                reuse_map[key] = hit

    # 先算总账再动手：免费额度能抵几首、还要多少积分，一次说清楚
    plan = pricing.quote(user["id"], [
        {"quality": quality, "transcode": platforms.needs_transcode(p)}
        for key, _, p in picked if key not in reuse_map
    ])
    if not plan["ok"]:
        return jsonify({
            "error": (f"积分不足：{len(picked)} 首需 {plan['credits']} 积分"
                      f"（免费额度可抵 {plan['free']} 首），当前余额 {plan['balance']} 积分，"
                      f"还差 {plan['short']} 积分"),
            "code": "credits_insufficient",
            "need": plan["credits"], "balance": plan["balance"], "short": plan["short"],
            "wallet": pricing.wallet(user["id"]),
        }), 402

    ratelimit.check_download(security.client_ip(), len(picked))
    job_id = create_paid_job(
        user, [platforms.track_payload(s, p) for _, s, p in picked], quality,
        kind="batch", title=f"批量下载 {len(picked)} 首", reuse_map=reuse_map,
    )
    return jsonify({
        "mode": "job", "job_id": job_id, "total": len(picked), "quality": quality,
        "plan": plan, "skipped": skipped, "wallet": pricing.wallet(user["id"]),
    })


def create_paid_job(user, tracks, quality, kind, title, ip=None, reuse_map=None):
    """建任务 + 逐首扣费 + 开跑。

    tracks 为 platforms.track_payload() 的列表。扣费按 ref=`job_id:idx` 记账，
    失败曲目在 services/jobs 里逐条退回；中途扣不动（并发抢额度）就整单退回。

    reuse_map 形如 {track_key: charge}：这些曲目在直连阶段已经扣过费，
    这里只把那笔账挂到任务条目上，不再收一次。
    """
    ip = ip or security.client_ip()
    reuse_map = reuse_map or {}
    job_id = jobs.create_job(kind, tracks, quality, user["id"], ip, title=title)
    try:
        for idx, track in enumerate(tracks):
            reuse = reuse_map.get(track["track_key"])
            if reuse:
                db.attach_charge_job(reuse["id"], job_id, idx)
                continue
            pricing.charge(
                user["id"], track["platform"], quality,
                transcode=platforms.needs_transcode(track["platform"]),
                ref=f"{job_id}:{idx}", track=track["track_key"],
            )
    except pricing.InsufficientCredits:
        db.update_job(job_id, status="failed")
        pricing.refund_job(job_id)
        raise
    jobs.start(job_id)
    return job_id


def _charged_payload(charge):
    if not charge:
        return None
    return {
        "kind": charge.get("kind"),
        "amount": int(charge.get("amount") or 0),
        "free": bool(charge.get("free")),
        "reuse": bool(charge.get("reuse")),
    }


@bp.get("/cover/<path:token>")
def cover_proxy(token):
    """封面走本站代理：几十 KB，相比省下的 8MB 音频可以忽略。

    必须登录 + 目标域名必须在封面白名单内：这个接口本质是「服务器替客户端抓
    URL」，不加限制就是一个现成的 SSRF（可打内网服务和云元数据）。
    """
    user = getattr(g, "user", None)
    if not user:
        return _login_required()
    payload = direct.verify(token)
    if not payload:
        return Response(b"", status=410)
    data = tagger.read_cover_bytes(payload["u"], timeout=8)
    if not data:
        return Response(b"", status=404)
    mime = "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
    resp = Response(data, mimetype=mime)
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


def _direct_download(song, platform, quality, user, reuse, track_key):
    target = song
    if quality == "flac":
        try:
            target = pipeline._resolve(None, song, platform, "flac")
        except Exception:
            return jsonify({"error": "该曲目暂未找到无损音源", "code": "lossless_unavailable"}), 404
        if not pipeline.transcode.is_lossless(getattr(target, "ext", "")):
            return jsonify({"error": "该曲目在源站没有无损版本", "code": "lossless_unavailable"}), 404

    url = getattr(target, "download_url", None)
    if not url or not str(url).startswith("http"):
        return jsonify({"error": "音源链接无效，请重试", "code": "track_expired"}), 404
    if not direct.is_https(url) and request.is_secure:
        # 混合内容会被浏览器拦截，退回服务端中转（同一条扣费，不重复收）
        return _job_response(song, platform, quality, user, reuse, track_key,
                             note="源站不支持加密直连，已改为服务端中转")

    charge = _bill(user, platform, quality, track_key, reuse)
    pricing.commit(charge)

    token = direct.issue(url, target.song_name or "", target.singers or "", platform)
    return jsonify({
        "mode": "direct",
        "url": f"/api/dl/{token}",
        "filename": _safe_filename(target.song_name, target.singers, getattr(target, "ext", quality)),
        "note": "直连下载，文件名由源站决定" if quality != "flac" else "",
        "quality": quality,
        "charge_id": charge["id"],
        "charged": _charged_payload(charge),
        "wallet": _wallet(user),
    })


def _job_response(song, platform, quality, user, reuse, track_key, note=""):
    """服务端任务：先建任务再扣费，扣费失败就把任务标失败，避免出现白跑的空任务。"""
    job_id = jobs.create_job("single", [platforms.track_payload(song, platform)], quality,
                             user["id"], security.client_ip(), title=song.song_name or "")
    try:
        charge = _bill(user, platform, quality, track_key, reuse)
    except pricing.InsufficientCredits:
        db.update_job(job_id, status="failed")
        raise
    # 复用来的那笔也挂到新任务上：任务失败时才能按 ref 退回
    db.attach_charge_job(charge["id"], job_id)
    jobs.start(job_id)
    payload = {
        "mode": "job", "job_id": job_id, "quality": quality,
        "charge_id": charge["id"], "charged": _charged_payload(charge),
        "wallet": _wallet(user),
    }
    if note:
        payload["note"] = note
    return jsonify(payload)


@bp.get("/dl/<path:token>")
def direct_download(token):
    payload = direct.verify(token)
    if not payload:
        return jsonify({"error": "下载链接已失效，请重新发起下载"}), 410
    user = getattr(g, "user", None)
    if not user:
        return _login_required()
    db.log_download(user["id"], security.client_ip(), payload.get("p", ""),
                    payload.get("n", ""), "direct", 0)
    resp = redirect(payload["u"], code=302)
    for key, value in direct.safe_redirect_headers().items():
        resp.headers[key] = value
    return resp


@bp.get("/files/<file_id>")
def get_file(file_id):
    user = getattr(g, "user", None)
    if not user:
        return _login_required()
    # 只认随机 token：sha1(file_id) 能由公开的曲目信息算出来，
    # 用它当 URL 等于把整站缓存免费开放（实测可白拿别人付过费的文件）。
    row = db.get_file_by_token(file_id)
    if not row or not os.path.exists(row["path"]):
        return jsonify({"error": "文件已过期，请重新下载"}), 404
    db.touch_file(row["id"])
    name = _safe_filename(row["song_name"], row["singers"], row["ext"])
    db.log_download(user["id"], security.client_ip(), row["platform"], row["song_name"],
                    row["quality"], int(row["size"] or 0))
    return send_file(row["path"], as_attachment=True, download_name=name,
                     mimetype="audio/mpeg" if row["ext"] == "mp3" else "application/octet-stream",
                     conditional=True)


def _safe_filename(song_name, singers, ext):
    ext = (ext or "mp3").lstrip(".")
    base = f"{song_name or 'track'} - {singers or '未知歌手'}"
    for ch in '<>:"/\\|?*\n\r\t':
        base = base.replace(ch, "_")
    return f"{base.strip()[:120]}.{ext}"
