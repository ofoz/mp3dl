"""音频转码：任意格式 -> MP3（PyAV，纯内存/临时文件，不依赖系统 ffmpeg）"""
import os
import tempfile

import av


def to_mp3(src_path: str, dst_path: str, bitrate: int = 320) -> bool:
    """把 src_path 转成 MP3 写到 dst_path，成功返回 True。"""
    try:
        with av.open(src_path, mode="r") as in_container:
            in_stream = next((s for s in in_container.streams if s.type == "audio"), None)
            if in_stream is None:
                return False
            with av.open(dst_path, mode="w", format="mp3") as out_container:
                codec = av.Codec("libmp3lame", "w")
                rate = in_stream.rate or 44100
                if codec.audio_rates and rate not in codec.audio_rates:
                    rate = codec.audio_rates[0]
                out_stream = out_container.add_stream("libmp3lame", rate=rate)
                out_stream.bit_rate = int(bitrate) * 1000
                resampler = av.AudioResampler(format="s16p", layout=out_stream.layout.name, rate=rate)
                for frame in in_container.decode(in_stream):
                    for out_frame in resampler.resample(frame):
                        for packet in out_stream.encode(out_frame):
                            out_container.mux(packet)
                for packet in out_stream.encode(None):
                    out_container.mux(packet)
        return os.path.exists(dst_path) and os.path.getsize(dst_path) > 1024
    except Exception:
        if os.path.exists(dst_path):
            try:
                os.remove(dst_path)
            except OSError:
                pass
        return False


def probe_duration(path: str) -> int:
    try:
        with av.open(path, mode="r") as container:
            if container.duration:
                return int(container.duration / 1000000)
    except Exception:
        pass
    return 0


def is_lossless(ext: str) -> bool:
    return (ext or "").lstrip(".").lower() in {"flac", "wav", "ape", "alac", "wv", "tta", "dsf", "dff"}


def tmp_path(suffix=""):
    fd, path = tempfile.mkstemp(prefix="mp3dl_", suffix=suffix, dir=tempfile.gettempdir())
    os.close(fd)
    return path
