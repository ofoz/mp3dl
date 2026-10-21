"""音质档位控制。

musicdl 各音源在解析直链时会遍历「音质优先级列表」取第一个可用的。
这里把列表换成上下文代理，实现：
  - 默认（MP3 档）优先申请 320k MP3：文件小、无需转码、下载快；
  - 请求无损时，在当前上下文临时切到无损档，互不影响。

两个坑（已处理）：
1. 列表必须保留原有档位、无损档必须保持原始顺序，
   否则源码里 `MUSIC_QUALITIES.index(...)` 会抛错，退回 mp3。
2. BaseMusicClient.search 内部会开线程池，普通 threading.local 传不进子线程，
   所以用 contextvars，并给 ThreadPoolExecutor.submit 打上上下文继承补丁。
"""
import contextvars
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

from . import musicdl_env  # noqa: F401  确保 sys.path 已就绪

# 平台 -> (模块/类标识, 属性名, {档位: 优先申请的取值})
TARGETS = {
    "NeteaseMusicClient": ("netease", "MUSIC_QUALITIES", {
        "mp3": ["exhigh"],
        "flac": ["lossless", "hires"],
    }),
    "KugouMusicClient": ("kugou", "MUSIC_QUALITIES", {
        "mp3": ["320"],
        "flac": ["flac"],
    }),
    "KuwoMusicClient": ("kuwo_class", "MUSIC_QUALITIES", {
        "mp3": [(320, "mp3")],
        "flac": [(22000, "flac")],
    }),
}
DEFAULT_PROFILE = "mp3"
PROFILES = {}

_ctx = contextvars.ContextVar("mp3dl_profile", default=None)


class ProfileList:
    """模块级 list 的上下文代理，保持 list 常用行为。"""

    def __init__(self, values):
        self._default = list(values)
        self._local = contextvars.ContextVar("mp3dl_list", default=None)

    def set(self, values):
        self._local.set(list(values))

    def _current(self):
        return self._local.get() or self._default

    def __iter__(self):
        return iter(self._current())

    def __len__(self):
        return len(self._current())

    def __getitem__(self, item):
        return self._current()[item]

    def __contains__(self, item):
        return item in self._current()

    def index(self, item):
        return self._current().index(item)

    def __repr__(self):
        return repr(self._current())


_proxies = {}
_patched = False
_pool_patched = False


def _resolve_target(kind):
    if kind == "kuwo_class":
        from musicdl.modules.sources.kuwo import KuwoMusicClient
        return KuwoMusicClient, "KuwoMusicClient"
    module = __import__(f"musicdl.modules.sources.{kind}", fromlist=["MUSIC_QUALITIES"])
    return module, kind


def _patch_pool():
    """让线程池任务继承提交方的 contextvars。"""
    global _pool_patched
    if _pool_patched:
        return
    original = ThreadPoolExecutor.submit

    def submit(self, fn, /, *args, **kwargs):
        ctx = contextvars.copy_context()
        return original(self, ctx.run, fn, *args, **kwargs)

    ThreadPoolExecutor.submit = submit
    _pool_patched = True


def init():
    """进程启动时调用一次。"""
    global _patched
    if _patched:
        return
    _patch_pool()
    for name, (kind, attr, profiles) in TARGETS.items():
        obj, _ = _resolve_target(kind)
        original = list(getattr(obj, attr, []) or [])
        if not original:
            continue
        rotated = {}
        for profile, wants in profiles.items():
            if profile == "flac":
                # 无损档保持原始列表：第三方无损通道依赖原顺序
                rotated[profile] = list(original)
            else:
                rotated[profile] = list(wants) + [v for v in original if v not in wants]
        PROFILES[name] = rotated
        proxy = ProfileList(rotated[DEFAULT_PROFILE])
        setattr(obj, attr, proxy)
        _proxies[name] = proxy
    _patched = True


@contextmanager
def use_profile(platform: str, profile: str = DEFAULT_PROFILE):
    """在 with 块内（含其派生的线程任务）使用指定音质档位。"""
    proxy = _proxies.get(platform)
    values = PROFILES.get(platform, {}).get(profile)
    if proxy is None or not values:
        yield
        return
    prev = proxy._local.get(None)
    token = proxy._local.set(list(values))
    try:
        yield
    finally:
        proxy._local.reset(token) if prev is None else proxy._local.set(prev)
