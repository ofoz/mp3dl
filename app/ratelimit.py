"""IP 维度限流：滑动时间窗，落 SQLite，多 worker 也准确"""
import time

from flask import jsonify

from . import db
from .config import Config


class RateLimited(Exception):
    def __init__(self, message="操作过于频繁，请稍后再试", retry_after=60):
        self.message = message
        self.retry_after = retry_after


def check(ip: str, action: str, limit: int, window_seconds: int = 60, amount: int = 1):
    if limit <= 0:
        return
    since = int(time.time()) - window_seconds
    used = db.rate_sum(ip, action, since)
    if used + amount > limit:
        raise RateLimited(retry_after=window_seconds)
    db.rate_add(ip, action, amount)


def check_search(ip):
    check(ip, "search", Config.RL_SEARCH_PER_MIN, 60)


def check_download(ip, tracks=1):
    """下载请求：按「请求数」限频，按「曲目数」限日总量。

    批量下一整张歌单只算 1 次请求，但曲目数照样计入日上限，
    免得一个请求就把几百首打包带走。
    """
    check(ip, "download", Config.RL_DOWNLOAD_PER_MIN, 60, 1)
    check(ip, "daily_tracks", Config.RL_DAILY_TRACKS, 86400, max(1, int(tracks)))


def check_auth(ip):
    check(ip, "auth", Config.RL_AUTH_PER_MIN, 60)


def check_register(ip):
    """同 IP 每日注册上限：防止刷小号领每日免费额度。"""
    check(ip, "register", Config.RL_REGISTER_PER_DAY, 86400)


def error_response(err: RateLimited):
    resp = jsonify({"error": err.message, "code": "rate_limited"})
    resp.status_code = 429
    resp.headers["Retry-After"] = str(err.retry_after)
    return resp
