"""账号：注册 / 登录 / 登出 / 当前用户 / 积分卡密兑换"""
from flask import Blueprint, g, jsonify, request

from .. import db, ratelimit, security
from ..services import pricing

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _set_cookie(resp, token):
    resp.set_cookie(
        security.SESSION_COOKIE, token,
        max_age=security.SESSION_DAYS * 86400,
        httponly=True, samesite="Lax",
        secure=request.is_secure,
    )
    return resp


@bp.post("/register")
def register():
    ip = security.client_ip()
    ratelimit.check_auth(ip)
    # 每个 IP 每天能注册的账号数：不卡的话「免费 10 首/天」可以靠小号无限续
    ratelimit.check_register(ip)

    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip()
    password = str(data.get("password", ""))
    nickname = str(data.get("nickname", "")).strip()[:24]

    if not security.valid_email(email):
        return jsonify({"error": "请输入有效的邮箱地址"}), 400
    if not security.valid_password(password):
        return jsonify({"error": "密码长度需在 6-64 位之间"}), 400
    if db.get_user_by_email(email):
        return jsonify({"error": "该邮箱已注册"}), 409

    db.create_user(email, security.hash_password(password), nickname)
    user = db.get_user_by_email(email)
    token = security.login(user["id"], ip, request.headers.get("User-Agent", ""))
    return _set_cookie(jsonify({"user": security.public_user(user)}), token)


@bp.post("/login")
def login():
    ip = security.client_ip()
    ratelimit.check_auth(ip)
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip()
    password = str(data.get("password", ""))

    user = db.get_user_by_email(email)
    if not user or not security.verify_password(password, user["password_hash"]):
        return jsonify({"error": "邮箱或密码不正确"}), 401
    if user["status"] != 1:
        return jsonify({"error": "账号已被禁用"}), 403

    token = security.login(user["id"], ip, request.headers.get("User-Agent", ""))
    g.user = user
    return _set_cookie(jsonify({"user": security.public_user(user)}), token)


@bp.post("/logout")
def logout():
    security.logout(getattr(g, "session_token", None))
    resp = jsonify({"ok": True})
    resp.delete_cookie(security.SESSION_COOKIE)
    return resp


@bp.get("/me")
def me():
    return jsonify({"user": security.public_user(getattr(g, "user", None))})


@bp.get("/wallet")
def wallet():
    """余额 + 今日免费余量 + 积分流水。"""
    user = getattr(g, "user", None)
    if not user:
        return jsonify({"error": "请先登录", "code": "login_required"}), 401
    return jsonify({
        "wallet": pricing.wallet(user["id"]),
        "ledger": db.ledger_list(user["id"], 30),
    })


@bp.post("/redeem")
def redeem():
    """卡密兑换积分（一张卡密 = 固定面额，一次性）。"""
    user = getattr(g, "user", None)
    if not user:
        return jsonify({"error": "请先登录", "code": "login_required"}), 401
    ratelimit.check_auth(security.client_ip())

    data = request.get_json(silent=True) or {}
    code = str(data.get("code", "")).strip().upper()
    if not code:
        return jsonify({"error": "请输入卡密"}), 400

    row = db.get_credit_code(code)
    if not row:
        return jsonify({"error": "卡密无效"}), 404
    if row["used_by"] or not db.use_credit_code(code, user["id"]):
        return jsonify({"error": "该卡密已被使用"}), 409

    added = int(row["credits"])
    balance = db.add_credits(user["id"], added)
    db.ledger_add(user["id"], added, balance, "redeem", code, "卡密兑换")
    fresh = db.get_user(user["id"])
    return jsonify({
        "user": security.public_user(fresh),
        "added": added,
        "balance": balance,
    })
