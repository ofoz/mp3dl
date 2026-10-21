"""把 vendor 里的 musicdl 源码接入 sys.path（不安装，避免重依赖）"""
import sys

from ..config import Config


def install():
    src = str(Config.MUSICDL_SRC)
    if src not in sys.path:
        sys.path.insert(0, src)


install()
