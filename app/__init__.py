"""Flask 应用装配"""
import logging
import secrets
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from .config import Config
from . import db, ratelimit, security
from .services import pricing, quality

WEB_DIR = Path(__file__).resolve().parent.parent / "web"

log = logging.getLogger("mp3dl")

# 这些是文档里出现过的示例值，等于没有密钥
_WEAK_SECRETS = {
    "",
    "mp3dl-dev-secret-change-me",
    "please-change-this-secret",
    "改成一段足够长的随机字符串",
    "changeme",
    "secret",
}


def _ensure_secret_key():
    """直连令牌（下载 / 封面）用 SECRET_KEY 签名。

    如果沿用示例里的默认值，任何人都能自己签发令牌，
    进而把本站当成任意 URL 的代理（SSRF）。所以这里强制兜底：
    没配或用了示例值，就在 storage 里生成一个随机密钥持久化复用。
    """
    current = (Config.SECRET_KEY or "").strip()
    if current not in _WEAK_SECRETS and len(current) >= 24:
        return
    path = Path(Config.STORAGE_DIR) / ".secret_key"
    try:
        if path.exists():
            key = path.read_text(encoding="utf-8").strip()
        else:
            key = secrets.token_urlsafe(48)
            path.write_text(key, encoding="utf-8")
            try:
                path.chmod(0o600)
            except OSError:
                pass
        if len(key) >= 24:
            Config.SECRET_KEY = key
            log.warning(
                "MP3DL_SECRET 未设置或仍在用示例值，已改用 %s 中的随机密钥；"
                "多实例部署请显式设置 MP3DL_SECRET", path
            )
            return
    except OSError as err:
        log.error("无法写入密钥文件 %s：%s", path, err)
    # 兜底：至少本次运行不可预测（重启后旧令牌失效）
    Config.SECRET_KEY = secrets.token_urlsafe(48)
    log.warning("使用进程内随机密钥，重启后已签发的下载链接会失效")


def _bootstrap_admin():
    if not Config.ADMIN_EMAIL or not Config.ADMIN_PASSWORD:
        return
    if not security.valid_email(Config.ADMIN_EMAIL):
        log.warning("MP3DL_ADMIN_EMAIL 不是合法邮箱，跳过管理员初始化")
        return
    if db.get_user_by_email(Config.ADMIN_EMAIL):
        return
    db.create_user(
        Config.ADMIN_EMAIL,
        security.hash_password(Config.ADMIN_PASSWORD),
        nickname="管理员",
        is_admin=1,
    )
    log.info("已创建管理员账号 %s", Config.ADMIN_EMAIL)


def _prune_musicdl_dir(max_age=6 * 3600):
    """musicdl 每次搜索都会写 <plat>/<时间戳 关键词>/search_results.pkl。

    它只是库自己的诊断缓存，本站完全不用，留着会一天天把磁盘吃掉。
    """
    import shutil
    root = Path(Config.MUSICDL_WORK_DIR)
    if not root.exists():
        return 0
    now = time.time()
    removed = 0
    for plat_dir in root.iterdir():
        if not plat_dir.is_dir():
            continue
        for item in plat_dir.iterdir():
            try:
                if now - item.stat().st_mtime < max_age:
                    continue
                shutil.rmtree(item) if item.is_dir() else item.unlink()
                removed += 1
            except OSError:
                continue
    return removed


def _cleanup_loop():
    from .services import pipeline
    while True:
        try:
            removed = pipeline.cleanup_cache()
            if removed:
                log.info("缓存清理：移除 %s 个过期文件", removed)
            pruned = _prune_musicdl_dir()
            if pruned:
                log.info("清理 musicdl 搜索缓存：%s 个目录", pruned)
        except Exception as err:
            log.warning("缓存清理失败：%s", err)
        time.sleep(1800)


def create_app():
    Config.ensure_dirs()
    _ensure_secret_key()
    db.init_db()
    quality.init()
    _bootstrap_admin()
    try:
        _prune_musicdl_dir(max_age=0)
    except Exception as err:
        log.warning("启动清理 musicdl 缓存失败：%s", err)

    app = Flask(__name__, static_folder=None)
    app.config["SECRET_KEY"] = Config.SECRET_KEY
    app.config["JSON_AS_ASCII"] = False
    app.json.ensure_ascii = False
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

    @app.before_request
    def _load_user():
        security.load_current_user()

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.path.startswith("/api/"):
            resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

    @app.errorhandler(ratelimit.RateLimited)
    def _rate_limited(err):
        return ratelimit.error_response(err)

    @app.errorhandler(pricing.InsufficientCredits)
    def _insufficient_credits(err):
        return jsonify({
            "error": str(err),
            "code": "credits_insufficient",
            "need": err.need,
            "balance": err.balance,
            "short": err.short,
        }), 402

    @app.errorhandler(413)
    def _too_large(_):
        return jsonify({"error": "文件过大"}), 413

    @app.errorhandler(Exception)
    def _server_error(err):
        from werkzeug.exceptions import HTTPException
        if isinstance(err, HTTPException):
            return jsonify({"error": err.description}), err.code
        log.exception("未处理异常")
        return jsonify({"error": "服务器内部错误，请稍后重试"}), 500

    from .api import register_blueprints
    register_blueprints(app)

    @app.route("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.route("/admin")
    def admin_page():
        # 页面本身是公开的静态壳，数据全部走 /api/admin/*（那里才有鉴权）
        return send_from_directory(WEB_DIR, "admin.html")

    @app.route("/assets/<path:filename>")
    def assets(filename):
        return send_from_directory(WEB_DIR / "assets", filename)

    @app.route("/favicon.ico")
    def favicon():
        return ("", 204)

    threading.Thread(target=_cleanup_loop, daemon=True).start()
    return app
