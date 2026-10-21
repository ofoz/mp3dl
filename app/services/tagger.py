"""MP3 标签写入：标题/歌手/专辑/封面/歌词"""
import ipaddress
import os
import socket
from urllib.parse import urlparse

from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC, USLT, TCON, ID3NoHeaderError

from ..config import Config


def _mime_from_bytes(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF":
        return "image/webp"
    return "image/jpeg"


def write_tags(path: str, title: str = "", artist: str = "", album: str = "",
               cover: bytes = None, lyric: str = "", genre: str = "") -> bool:
    if not path.lower().endswith(".mp3"):
        return False
    try:
        try:
            tags = ID3(path)
        except ID3NoHeaderError:
            tags = ID3()
        if title:
            tags.delall("TIT2")
            tags.add(TIT2(encoding=3, text=title))
        if artist:
            tags.delall("TPE1")
            tags.add(TPE1(encoding=3, text=artist))
        if album:
            tags.delall("TALB")
            tags.add(TALB(encoding=3, text=album))
        if genre:
            tags.delall("TCON")
            tags.add(TCON(encoding=3, text=genre))
        if cover:
            tags.delall("APIC")
            tags.add(APIC(encoding=3, mime=_mime_from_bytes(cover), type=3, desc="Cover", data=cover))
        if lyric:
            tags.delall("USLT")
            tags.add(USLT(encoding=3, lang="chi", desc="", text=lyric))
        tags.save(path)
        return True
    except Exception:
        return False


# QQ 音乐的封面地址由 album_mid 拼成，专辑信息缺失时会拼出字面量 "None"（M000None.jpg），
# 这种地址必然 404，提前拦掉可以避免碎图和无谓请求。
_BAD_COVER_MARKS = ("/M000None", "M000None.jpg", "photo_new/T002R800x800M000.", "None.jpg")


# 封面只可能是这几个音源 CDN 上的图片。白名单 + 内网地址黑名单双保险，
# 防止 /api/cover 被当成通用 HTTP 代理去打内网或云元数据。
DEFAULT_COVER_HOSTS = (
    "126.net", "163.com", "kugou.com", "kugou.net", "qq.com", "gtimg.cn",
    "qpic.cn", "kuwo.cn", "migu.cn", "91q.com", "douyinpic.com",
    "byteimg.com", "douyinstatic.com", "pddpic.com",
)
MAX_COVER_BYTES = 3 * 1024 * 1024


def _cover_hosts():
    raw = (Config.COVER_HOSTS or "").strip()
    extra = tuple(h.strip().lower().lstrip(".") for h in raw.split(",") if h.strip())
    return DEFAULT_COVER_HOSTS + extra


def _is_private_ip(ip):
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return any((addr.is_private, addr.is_loopback, addr.is_link_local,
                addr.is_reserved, addr.is_multicast, addr.is_unspecified))


def safe_cover_url(url: str) -> bool:
    """封面 URL 是否允许服务端去取。"""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if not any(host == h or host.endswith("." + h) for h in _cover_hosts()):
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        if _is_private_ip(info[4][0]):
            return False
    return True


def usable_cover(url: str) -> str:
    url = (url or "").strip()
    if not url.lower().startswith("http"):
        return ""
    if any(mark in url for mark in _BAD_COVER_MARKS):
        return ""
    return url


def read_cover_bytes(url: str, timeout=8) -> bytes:
    url = usable_cover(url)
    if not url or not safe_cover_url(url):
        return b""
    try:
        import requests
        with requests.get(url, timeout=timeout, verify=False, stream=True,
                          allow_redirects=False,
                          headers={"User-Agent": "Mozilla/5.0",
                                   "Referer": "https://music.163.com/"}) as resp:
            if not resp.ok:
                return b""
            buf = bytearray()
            for chunk in resp.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                buf.extend(chunk)
                if len(buf) >= MAX_COVER_BYTES:
                    break
        if len(buf) > 512:
            return bytes(buf[:MAX_COVER_BYTES])
    except Exception:
        pass
    return b""
