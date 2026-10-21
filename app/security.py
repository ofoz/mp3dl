"""账号与会话：PBKDF2 口令哈希 + 服务端会话 + 钱包（积分 / 免费额度）"""
import hashlib
import hmac
import ipaddress
import re
import secrets

from flask import g, request

from . import db
from .config import Config
from .services import pricing

SESSION_COOKIE = "mp3dl_sid"
SESSION_DAYS = 30
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")

_trusted_nets = None


def _parse_trusted(raw):
    nets = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            nets.append(ipaddress.ip_network(part, strict=False))
        except ValueError:
            continue
    return nets


def _is_trusted_proxy(ip):
    """判断请求是否来自我们自己的反向代理。"""
    global _trusted_nets
    if _trusted_nets is None:
        _trusted_nets = _parse_trusted(Config.TRUSTED_PROXIES)
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return any(addr in net for net in _trusted_nets)


def hash_password(password: str, salt: str = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000)
    return f"pbkdf2${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    calc = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return hmac.compare_digest(calc, digest)


def valid_email(email: str) -> bool:
    return bool(email and EMAIL_RE.match(email.strip()))


def valid_password(password: str) -> bool:
    return bool(password and 6 <= len(password) <= 64)


def login(uid, ip="", ua=""):
    token = secrets.token_urlsafe(32)
    db.create_session(token, uid, SESSION_DAYS, ip, ua)
    db.touch_login(uid)
    return token


def logout(token):
    if token:
        db.delete_session(token)


def load_current_user():
    """在 before_request 里调用，挂到 g.user。"""
    token = request.cookies.get(SESSION_COOKIE)
    g.user = None
    g.session_token = token
    if not token:
        return
    sess = db.get_session(token)
    if not sess:
        return
    user = db.get_user(sess["user_id"])
    if user and user["status"] == 1:
        g.user = user


def public_user(user):
    """对外的用户信息（含钱包快照，前端据此显示余额与价目）。"""
    if not user:
        return None
    uid = user["id"]
    return {
        "id": uid,
        "email": user["email"],
        "nickname": user["nickname"] or user["email"].split("@")[0],
        "is_admin": bool(user["is_admin"]),
        "wallet": pricing.wallet(uid),
    }


def client_ip() -> str:
    """真实客户端 IP。

    只有当直连方是我们的反向代理时才读 X-Forwarded-For——
    否则任何人都能随便填这个头，把「每 IP 限流」「每日免费额度」
    变成摆设（实测：轮换 XFF 可以无限注册、无限下载）。
    """
    remote = request.remote_addr or "0.0.0.0"
    if not _is_trusted_proxy(remote):
        return remote

    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        # 从右往左取第一个「非代理」地址：右侧是我们加的，左侧是客户端伪造的
        parts = [p.strip() for p in fwd.split(",") if p.strip()]
        for ip in reversed(parts):
            if not _is_trusted_proxy(ip):
                return ip
        if parts:
            return parts[0]
    real = request.headers.get("X-Real-IP")
    if real and not _is_trusted_proxy(real.strip()):
        return real.strip()
    return remote
