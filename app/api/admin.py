"""管理后台：站点数据 / 用户列表 / 发放积分 / 生成卡密"""
import secrets
import time
from functools import wraps

from flask import Blueprint, g, jsonify, request

from .. import db, security
from ..config import Config

bp = Blueprint("admin", __name__, url_prefix="/api/admin")

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = getattr(g, "user", None)
        if not user:
            return jsonify({"error": "请先登录"}), 401
        if not user["is_admin"]:
            return jsonify({"error": "需要管理员权限"}), 403
        return fn(*args, **kwargs)
    return wrapper


def now():
    return int(time.time())


@bp.get("/stats")
@admin_required
def stats():
    users = db.one("SELECT COUNT(*) AS c FROM users")["c"]
    credits = db.one("SELECT COALESCE(SUM(credits),0) AS s FROM users")["s"]
    files = db.one("SELECT COUNT(*) AS c, COALESCE(SUM(size),0) AS s FROM files")
    jobs_total = db.one("SELECT COUNT(*) AS c FROM jobs")["c"]
    downloads = db.one("SELECT COUNT(*) AS c FROM download_logs")["c"]
    since = now() - 86400
    downloads_24h = db.one("SELECT COUNT(*) AS c FROM download_logs WHERE created_at>=?", (since,))["c"]
    unpaid = db.one("SELECT COUNT(*) AS c FROM credit_codes WHERE used_by=0")["c"]
    codes_used = db.one("SELECT COUNT(*) AS c FROM credit_codes WHERE used_by>0")["c"]
    users_24h = db.one("SELECT COUNT(*) AS c FROM users WHERE created_at>=?", (since,))["c"]
    charged_today = db.one(
        "SELECT COALESCE(SUM(amount),0) AS s FROM charges WHERE kind='credit' AND status='committed' AND created_at>=?",
        (since,),
    )["s"]
    free_today = db.one(
        "SELECT COUNT(*) AS c FROM charges WHERE kind='free' AND status='committed' AND created_at>=?",
        (since,),
    )["c"]
    return jsonify({
        "users": users,
        "users_24h": int(users_24h),
        "credits_in_wallets": int(credits),
        "codes_unused": unpaid,
        "codes_used": int(codes_used),
        "charged_credits_24h": int(charged_today),
        "free_tracks_24h": int(free_today),
        "files": files["c"], "storage_bytes": int(files["s"]),
        "jobs": jobs_total, "downloads": downloads, "downloads_24h": downloads_24h,
        "cache_limit_gb": Config.CACHE_MAX_GB,
        "prices": {
            "mp3": Config.PRICE_CREDIT_MP3,
            "transcode": Config.PRICE_CREDIT_TRANSCODE,
            "flac": Config.PRICE_CREDIT_FLAC,
        },
        "free_daily": Config.FREE_DAILY_TRACKS,
    })


@bp.get("/users")
@admin_required
def users():
    keyword = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = max(int(request.args.get("offset", 0)), 0)
    where = ""
    args = []
    if keyword:
        where = " WHERE email LIKE ? OR nickname LIKE ?"
        args = [f"%{keyword}%", f"%{keyword}%"]
    rows = db.query("SELECT * FROM users" + where + " ORDER BY id DESC LIMIT ? OFFSET ?",
                    args + [limit, offset])
    matched = db.one("SELECT COUNT(*) AS c FROM users" + where, args)["c"]
    total = db.one("SELECT COUNT(*) AS c FROM users")["c"]
    out = []
    for r in rows:
        item = security.public_user(r) or {}
        wallet = item.pop("wallet", None) or {}
        item["credits"] = int(wallet.get("credits") or 0)
        item["free_left"] = int(wallet.get("free_left") or 0)
        item["free_limit"] = int(wallet.get("free_limit") or 0)
        item["created_at"] = r["created_at"]
        item["last_login_at"] = r["last_login_at"]
        item["status"] = r["status"]
        out.append(item)
    return jsonify({"users": out, "total": int(matched), "users_all": int(total)})


@bp.post("/users/<int:uid>/admin")
@admin_required
def set_admin(uid):
    """设置 / 取消管理员。禁止把自己降级，也禁止把最后一个管理员降级。"""
    data = request.get_json(silent=True) or {}
    try:
        is_admin = 1 if int(data.get("is_admin", 1)) == 1 else 0
    except (TypeError, ValueError):
        return jsonify({"error": "参数不正确"}), 400
    target = db.get_user(uid)
    if not target:
        return jsonify({"error": "用户不存在"}), 404
    if not is_admin:
        if uid == g.user["id"]:
            return jsonify({"error": "不能取消自己的管理员权限"}), 400
        admins = db.one("SELECT COUNT(*) AS c FROM users WHERE is_admin=1")["c"]
        if admins <= 1:
            return jsonify({"error": "站点至少要保留一个管理员"}), 400
    db.execute("UPDATE users SET is_admin=? WHERE id=?", (is_admin, uid))
    return jsonify({"ok": True, "is_admin": bool(is_admin)})


@bp.post("/credits")
@admin_required
def grant_credits():
    """后台直接发放 / 扣减积分。"""
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip()
    try:
        amount = int(data.get("credits", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "积分数不正确"}), 400
    if not email or amount == 0 or abs(amount) > 1_000_000:
        return jsonify({"error": "参数不正确"}), 400
    user = db.get_user_by_email(email)
    if not user:
        return jsonify({"error": "用户不存在"}), 404
    balance = db.add_credits(user["id"], amount)
    if balance is None:
        return jsonify({"error": "扣减失败：余额不足"}), 400
    db.ledger_add(user["id"], amount, balance, "admin", "", "后台调整")
    return jsonify({"user": security.public_user(db.get_user(user["id"])), "balance": balance})


@bp.post("/users/<int:uid>/status")
@admin_required
def toggle_status(uid):
    """启用 / 禁用账号。

    不能禁用自己（否则当场失去后台），也不能把最后一个可登录的管理员禁掉，
    不然站点就没人能进去了。
    """
    data = request.get_json(silent=True) or {}
    try:
        status = 1 if int(data.get("status", 1)) == 1 else 0
    except (TypeError, ValueError):
        return jsonify({"error": "参数不正确"}), 400
    target = db.get_user(uid)
    if not target:
        return jsonify({"error": "用户不存在"}), 404
    if not status:
        if uid == g.user["id"]:
            return jsonify({"error": "不能禁用自己"}), 400
        if target["is_admin"]:
            alive = db.one("SELECT COUNT(*) AS c FROM users WHERE is_admin=1 AND status=1")["c"]
            if alive <= 1:
                return jsonify({"error": "站点至少要保留一个可登录的管理员"}), 400
    db.execute("UPDATE users SET status=? WHERE id=?", (status, uid))
    return jsonify({"ok": True, "status": status})


@bp.post("/codes")
@admin_required
def create_codes():
    """生成积分卡密：一张卡密固定面额，一次性使用。"""
    data = request.get_json(silent=True) or {}
    try:
        credits = int(data.get("credits", Config.CREDIT_CARD_DEFAULT))
        count = min(max(int(data.get("count", 1)), 1), 100)
    except (TypeError, ValueError):
        return jsonify({"error": "参数不正确"}), 400
    if credits <= 0 or credits > 1_000_000:
        return jsonify({"error": "面额需在 1 ~ 1000000 积分之间"}), 400
    note = str(data.get("note", ""))[:40]

    codes = []
    for _ in range(count):
        # 卡密等于钱：必须用密码学安全的随机数，random 模块的 MT19937
        # 状态可以从输出反推，不适合生成凭据。
        code = "-".join([Config.CREDIT_CARD_PREFIX] +
                        ["".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(3)])
        try:
            db.create_credit_code(code, credits, note)
            codes.append(code)
        except Exception:
            continue
    return jsonify({"codes": codes, "credits": credits})


@bp.get("/codes")
@admin_required
def list_codes():
    limit = min(int(request.args.get("limit", 100)), 500)
    unused_only = (request.args.get("unused") or "") in ("1", "true")
    sql = ("SELECT c.*, u.email AS used_email FROM credit_codes c "
           "LEFT JOIN users u ON u.id=c.used_by")
    if unused_only:
        sql += " WHERE c.used_by=0"
    sql += " ORDER BY c.created_at DESC LIMIT ?"
    rows = db.query(sql, (limit,))
    return jsonify({"codes": rows})


@bp.get("/ledger")
@admin_required
def ledger():
    limit = min(int(request.args.get("limit", 100)), 500)
    rows = db.query(
        """SELECT l.*, u.email FROM credit_ledger l LEFT JOIN users u ON u.id=l.user_id
           ORDER BY l.id DESC LIMIT ?""",
        (limit,),
    )
    return jsonify({"ledger": rows})
