"""全局配置（全部可通过环境变量覆盖）"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
WORKSPACE = BASE_DIR.parent


def _env(key, default=None, cast=str):
    val = os.environ.get(key, default)
    if val is None:
        return None
    if cast is bool:
        return str(val).lower() in {"1", "true", "yes", "on"}
    if cast is int:
        return int(val)
    return val


def _file_keep_hours():
    """单曲缓存的保留时长（小时）。

    以「最后一次被下载」为起点计算，不是首次生成时间。
    兼容历史变量 MP3DL_CACHE_TTL_HOURS：早期文档写的是这个名字，
    但它从来没有真正接到清理逻辑上（改了不起作用），这里做一次回退，
    免得老 .env 里的值被静默忽略。
    """
    raw = os.environ.get("MP3DL_FILE_KEEP_HOURS", "").strip()
    if raw.isdigit():
        return int(raw)
    legacy = os.environ.get("MP3DL_CACHE_TTL_HOURS", "").strip()
    if legacy.isdigit():
        return int(legacy)
    return 24


class Config:
    # 服务
    HOST = _env("MP3DL_HOST", "127.0.0.1")
    PORT = _env("MP3DL_PORT", 9080, int)
    SECRET_KEY = _env("MP3DL_SECRET", "mp3dl-dev-secret-change-me")
    DEBUG = _env("MP3DL_DEBUG", False, bool)
    # 只有来自这些地址的请求才采信 X-Forwarded-For。
    # 直连公网时 remote_addr 是真实客户端 IP，不会被信任，
    # 于是伪造 XFF 头无法绕过限流。
    TRUSTED_PROXIES = _env(
        "MP3DL_TRUSTED_PROXIES",
        "127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
    )

    # 存储
    STORAGE_DIR = Path(_env("MP3DL_STORAGE", str(BASE_DIR / "storage")))
    CACHE_DIR = STORAGE_DIR / "cache"
    TMP_DIR = STORAGE_DIR / "tmp"
    DB_PATH = Path(_env("MP3DL_DB", str(STORAGE_DIR / "mp3dl.db")))
    # musicdl 每次搜索都会把结果 pickle 落盘（它自己的诊断缓存），
    # 默认落在工作目录下会无限膨胀，统一收到 storage 里并定期清掉。
    MUSICDL_WORK_DIR = Path(_env("MP3DL_MUSICDL_DIR", str(STORAGE_DIR / "musicdl")))

    # musicdl 源码位置（vendor）：仓库自带的 vendor/ 优先，
    # 兼容旧布局（同级目录 musicdl-src），也可用 MUSICDL_SRC 显式指定
    MUSICDL_SRC = Path(_env("MUSICDL_SRC", str(
        BASE_DIR / "vendor" if (BASE_DIR / "vendor" / "musicdl").is_dir()
        else WORKSPACE / "musicdl-src"
    )))

    # 搜索
    SEARCH_SIZE_PER_SOURCE = _env("MP3DL_SEARCH_SIZE", 6, int)
    SOURCE_TIMEOUT = _env("MP3DL_SOURCE_TIMEOUT", 45, int)

    # 下载 / 转码
    MAX_TRANSCODE = _env("MP3DL_MAX_TRANSCODE", 3, int)
    JOB_WORKERS = _env("MP3DL_JOB_WORKERS", 3, int)
    MAX_PLAYLIST_TRACKS = _env("MP3DL_MAX_PLAYLIST", 200, int)
    # 搜索结果「批量下载」单次最多提交多少首（每首各建一个任务，逐首交付）
    MAX_BATCH_TRACKS = _env("MP3DL_MAX_BATCH", 100, int)
    MP3_BITRATE = _env("MP3DL_MP3_BITRATE", 320, int)

    # 缓存清理
    # FILE_KEEP_HOURS 是唯一的「单曲缓存保留时长」开关，从最后一次下载算起。
    CACHE_MAX_GB = _env("MP3DL_CACHE_MAX_GB", 20, int)
    FILE_KEEP_HOURS = _file_keep_hours()
    # 旧名别名，值恒等于 FILE_KEEP_HOURS，仅为兼容外部脚本引用。
    CACHE_TTL_HOURS = FILE_KEEP_HOURS

    # 限流（每 IP）
    RL_SEARCH_PER_MIN = _env("MP3DL_RL_SEARCH", 20, int)
    RL_DOWNLOAD_PER_MIN = _env("MP3DL_RL_DOWNLOAD", 10, int)
    RL_DAILY_TRACKS = _env("MP3DL_RL_DAILY", 300, int)
    RL_AUTH_PER_MIN = _env("MP3DL_RL_AUTH", 10, int)
    # 注册也要卡：否则「每天免费 10 首」可以靠无限注册小号绕过
    RL_REGISTER_PER_DAY = _env("MP3DL_RL_REGISTER_DAY", 3, int)

    # ---------- 计费（积分） ----------
    # 关掉后所有下载都不扣额度/积分，仅建议内网自用场景。
    BILLING_ENABLED = _env("MP3DL_BILLING", 1, int) == 1
    # 每个账号每天可免费下载的普通 MP3 首数（网易云/酷狗，浏览器直连）
    FREE_DAILY_TRACKS = _env("MP3DL_FREE_DAILY", 10, int)
    # 免费额度用完后，每首普通 MP3 的积分价
    PRICE_CREDIT_MP3 = _env("MP3DL_PRICE_MP3", 10, int)
    # 必须服务端转码的平台（QQ）每首积分价，不吃免费额度
    PRICE_CREDIT_TRANSCODE = _env("MP3DL_PRICE_TRANSCODE", 10, int)
    # 无损 FLAC 每首积分价
    PRICE_CREDIT_FLAC = _env("MP3DL_PRICE_FLAC", 50, int)
    # 卡密
    CREDIT_CARD_PREFIX = _env("MP3DL_CARD_PREFIX", "MP3")
    CREDIT_CARD_DEFAULT = _env("MP3DL_CARD_CREDITS", 100, int)
    # 「每天」按哪个时区切日（默认东八区），影响免费额度重置时间
    QUOTA_TZ_OFFSET = _env("MP3DL_TZ_OFFSET", 8, int)
    ADMIN_EMAIL = _env("MP3DL_ADMIN_EMAIL", "")
    ADMIN_PASSWORD = _env("MP3DL_ADMIN_PASSWORD", "")

    # 站点
    SITE_NAME = _env("MP3DL_SITE_NAME", "MP3库")
    SITE_SLOGAN = _env("MP3DL_SLOGAN", "搜歌即得 MP3，歌单一键打包")

    # 下载通道：MP3 优先让浏览器直连音源、本地写标签，服务器只发标签数据
    MP3_BROWSER_FIRST = _env("MP3DL_MP3_BROWSER", 1, int) == 1
    # 服务端允许去抓取封面的域名后缀（逗号分隔，叠加在内置白名单上）。
    # /api/cover 会把远端内容回给浏览器，白名单是防 SSRF 的关键一环。
    COVER_HOSTS = _env("MP3DL_COVER_HOSTS", "")
    # 反代后面 request.is_secure 可能判断不出 https，这里兜底声明
    SITE_HTTPS = _env("MP3DL_SITE_HTTPS", 0, int) == 1

    @classmethod
    def ensure_dirs(cls):
        for d in (cls.STORAGE_DIR, cls.CACHE_DIR, cls.TMP_DIR, cls.MUSICDL_WORK_DIR):
            Path(d).mkdir(parents=True, exist_ok=True)
