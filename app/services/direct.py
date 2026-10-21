"""直连下载：音频字节不经过本站。

两条通道，按「浏览器能不能读到字节」自动选：

1. **302 直连**（FLAC / 兜底）：服务端只回一个跳转，浏览器自己去 CDN 取。
   缺点是拿不到文件名、也没法写标签。
2. **浏览器取流 + 本地打标**（MP3 首选）：页面用 fetch 把音频读到内存，
   在用户机器上用 JS 写 ID3v2 标签（歌名/歌手/封面/歌词），再落成文件。
   这样文件名可控、标签完整，而本站只发几 KB 的标签数据。

第 2 条能成立的前提是：直链走 https（否则 HTTPS 站点会被混合内容拦截）、
且 CDN 返回 `Access-Control-Allow-Origin`（否则 fetch 读不到字节）。
只满足前者的（如酷狗 http 直链）和没有 CORS 的（酷我、咪咕）自动降级为服务端中转。
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import socket
import threading
import time
from urllib.parse import urlparse

from ..config import Config

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36")

# 按 CDN 域名缓存探测结果：同一台 CDN 的策略一致，没必要每首都探
_cors_cache = {}
_cors_lock = threading.Lock()
CORS_TTL = 6 * 3600

# 明确不支持 CORS 的域名，直接拉黑不探测（省一次 RTT）
_KNOWN_NO_CORS = ("sycdn.kuwo.cn", "freetyst.nf.migu.cn", "music.migu.cn",
                  "cdn.migu.cn", "ws.sycdn.kuwo.cn")


def _host_is_public(host: str) -> bool:
    """直链域名解析出来的地址必须是公网，否则探测请求本身就成了 SSRF。"""
    try:
        infos = socket.getaddrinfo(host, None)
    except (socket.gaierror, UnicodeError):
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if any((addr.is_private, addr.is_loopback, addr.is_link_local,
                addr.is_reserved, addr.is_multicast, addr.is_unspecified)):
            return False
    return True


def cors_allowed(url: str, origin: str = "") -> bool:
    """探测 CDN 是否允许浏览器跨域读取该直链。

    用 Range 只取 1 字节，避免为探测白拉 8MB。
    """
    try:
        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        host = (parsed.hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    if scheme not in ("http", "https"):
        return False
    if any(bad in host for bad in _KNOWN_NO_CORS):
        return False
    if not _host_is_public(host):
        return False

    # http / https 的策略可能不同，按 scheme 分开缓存
    key = f"{scheme}://{host}"
    now = time.time()
    with _cors_lock:
        hit = _cors_cache.get(key)
        if hit and now - hit[1] < CORS_TTL:
            return hit[0]

    ok = False
    try:
        import requests
        resp = requests.get(
            url,
            headers={"Origin": origin or "https://example.com", "User-Agent": UA,
                     "Range": "bytes=0-1023"},
            stream=True,
            timeout=6,
        )
        allow = (resp.headers.get("access-control-allow-origin") or "").strip()
        resp.close()
        ok = allow == "*" or (bool(origin) and allow == origin)
    except Exception:
        ok = False

    with _cors_lock:
        _cors_cache[key] = (ok, now)
    return ok


def prepare(url: str, page_is_https: bool, origin: str = ""):
    """返回 (交给浏览器的 url, 是否真能直连)。

    https 页面遇到 http 直链时，先试着把 scheme 换成 https——不少 CDN
    两种协议都能服务（酷狗就是），换成功就仍然直连，不必降级中转。
    """
    if not url or not str(url).startswith("http"):
        return url, False
    if page_is_https and not is_https(url):
        upgraded = "https://" + url.split("://", 1)[1]
        if cors_allowed(upgraded, origin):
            return upgraded, True
        return url, False
    return url, cors_allowed(url, origin)


def can_browser_fetch(url: str, page_is_https: bool, origin: str = "") -> bool:
    """浏览器能否直接取到这个直链。"""
    return prepare(url, page_is_https, origin)[1]


MAX_AGE = 900  # 直连令牌有效期 15 分钟，够用户点开，又能防止链接被长期外传


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


def _sign(payload: str) -> str:
    key = Config.SECRET_KEY.encode()
    return _b64encode(hmac.new(key, payload.encode(), hashlib.sha256).digest())[:32]


def issue(url: str, song_name: str, singers: str, platform: str) -> str:
    """把直链封装成带签名和有效期的令牌。"""
    payload = {
        "u": url,
        "n": (song_name or "")[:80],
        "s": (singers or "")[:80],
        "p": platform,
        "e": int(time.time()) + MAX_AGE,
    }
    raw = _b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    return f"{raw}.{_sign(raw)}"


def verify(token: str):
    """校验令牌，返回 payload 或 None。"""
    if not token or "." not in token:
        return None
    raw, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(raw)):
        return None
    try:
        payload = json.loads(_b64decode(raw))
    except Exception:
        return None
    if int(payload.get("e", 0)) < time.time():
        return None
    url = payload.get("u") or ""
    if not url.startswith("http"):
        return None
    return payload


def is_https(url: str) -> bool:
    return url.lower().startswith("https://")


def safe_redirect_headers() -> dict:
    """关键响应头：
    - Referrer-Policy: no-referrer -> 绕过 CDN 防盗链；
    - no-store -> 令牌不复用；
    """
    return {
        "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store, no-cache, must-revalidate",
        "X-Download-Mode": "direct",
    }
