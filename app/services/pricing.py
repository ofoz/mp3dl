"""计费：定价 / 每日免费额度 / 积分扣减与退回 / 卡密面额

计费单位是「一条下载权益」= 一首歌的一次交付：

| 场景 | 价格 | 是否吃每日免费额度 |
|---|---|---|
| 普通 MP3（网易云 / 酷狗，浏览器直连） | 免费额度内 0，超出 10 积分/首 | 是 |
| 需服务端转码的平台（QQ） | 10 积分/首 | 否（必然吃服务器带宽 + CPU） |
| 无损 FLAC | 50 积分/首 | 否 |

扣费是「先占位、后结算」：任务型下载在提交时扣，单曲失败会退回；
批量任务逐首扣，失败的曲目各自退回，不让用户为没拿到的文件买单。
"""
import time
from datetime import datetime, timedelta, timezone

from .. import db
from ..config import Config


class InsufficientCredits(Exception):
    """积分不够支付本次下载。"""

    def __init__(self, need, balance, quality="mp3", platform=""):
        self.need = int(need)
        self.balance = int(balance)
        self.short = max(0, self.need - self.balance)
        self.quality = quality
        self.platform = platform
        super().__init__(
            f"积分不足：本次需要 {self.need} 积分，当前余额 {self.balance} 积分，还差 {self.short} 积分"
        )


def today(ts=None) -> str:
    """按配置时区切自然日（免费额度按这个日期重置）。"""
    if ts is None:
        ts = time.time()
    return (datetime.fromtimestamp(ts, timezone.utc) + timedelta(hours=Config.QUOTA_TZ_OFFSET)).strftime("%Y-%m-%d")


def unit_price(quality="mp3", transcode=False):
    """返回该曲目的定价信息。

    free_ok=True 表示「有免费额度时可免费」，额度用完后按 credits 收。
    """
    quality = (quality or "mp3").lower()
    if quality == "flac":
        return {"credits": Config.PRICE_CREDIT_FLAC, "free_ok": False, "label": "无损 FLAC"}
    if transcode:
        return {"credits": Config.PRICE_CREDIT_TRANSCODE, "free_ok": False, "label": "服务端转码"}
    return {"credits": Config.PRICE_CREDIT_MP3, "free_ok": True, "label": "普通 MP3"}


def free_left(user_id) -> int:
    if not user_id or not Config.BILLING_ENABLED:
        return Config.FREE_DAILY_TRACKS
    return max(0, Config.FREE_DAILY_TRACKS - db.free_quota_used(user_id, today()))


def wallet(user_id) -> dict:
    """给前端的钱包快照：余额、今日免费余量、价目表。"""
    return {
        "credits": db.get_credits(user_id) if user_id else 0,
        "free_left": free_left(user_id),
        "free_limit": Config.FREE_DAILY_TRACKS,
        "billing": Config.BILLING_ENABLED,
        "prices": {
            "mp3": Config.PRICE_CREDIT_MP3,
            "transcode": Config.PRICE_CREDIT_TRANSCODE,
            "flac": Config.PRICE_CREDIT_FLAC,
        },
    }


def quote(user_id, items) -> dict:
    """批量预估价：items 为 [{'quality','transcode'}]。

    先按「能用免费额度就用」的顺序分配，再算需要多少积分。
    """
    left = free_left(user_id)
    credits = 0
    frees = 0
    for item in items:
        info = unit_price(item.get("quality"), item.get("transcode"))
        if info["free_ok"] and left > 0:
            left -= 1
            frees += 1
        else:
            credits += info["credits"]
    balance = db.get_credits(user_id) if user_id else 0
    return {
        "free": frees,
        "credits": credits,
        "free_left": left,
        "balance": balance,
        "short": max(0, credits - balance),
        "ok": (not Config.BILLING_ENABLED) or balance >= credits,
    }


def charge(user_id, platform, quality, transcode=False, ref="", track="") -> dict:
    """扣一条下载权益，返回 charge 记录（含 id，用于后续结算 / 复用 / 退回）。

    优先消耗免费额度，其次扣积分；两者都不够时抛 InsufficientCredits。
    """
    quality = (quality or "mp3").lower()
    info = unit_price(quality, transcode)

    if not Config.BILLING_ENABLED:
        cid = db.add_charge(user_id, "free", 0, platform, quality, ref, track, status="committed")
        return {"id": cid, "kind": "free", "amount": 0, "free": True}

    if info["free_ok"] and db.take_free_quota(user_id, today(), Config.FREE_DAILY_TRACKS):
        cid = db.add_charge(user_id, "free", 1, platform, quality, ref, track, status="held")
        return {"id": cid, "kind": "free", "amount": 1, "free": True}

    need = int(info["credits"])
    if need > 0:
        if not db.spend_credits(user_id, need):
            raise InsufficientCredits(need, db.get_credits(user_id), quality=quality, platform=platform)
        balance = db.get_credits(user_id)
        db.ledger_add(user_id, -need, balance, "charge", ref, f"{platform} · {quality}")
    else:
        balance = db.get_credits(user_id)

    cid = db.add_charge(user_id, "credit", need, platform, quality, ref, track, status="held")
    return {"id": cid, "kind": "credit", "amount": need, "free": False, "balance": balance}


def commit(charge_info):
    """标记为「已交付」：单曲直连、任务成功都走这里。"""
    if charge_info and charge_info.get("id"):
        db.settle_charge(charge_info["id"], "committed")


def commit_ref(ref):
    """按 ref 结算（任务里某一首成功）。"""
    for row in db.get_charges_by_ref(ref):
        if row["status"] == "held":
            db.settle_charge(row["id"], "committed")


def refund(charge_id, note="下载未完成，已退回") -> bool:
    """退回一条权益：免费额度还原、积分入账。重复调用不会重复退。"""
    row = db.get_charge(charge_id)
    if not row:
        return False
    # 先原子占位再退钱：并发/重试时只有一个调用者能走到入账那一步
    if not db.claim_refund(charge_id):
        return False
    if row["kind"] == "free":
        db.release_free_quota(row["user_id"], today(row["created_at"]))
    else:
        amount = int(row["amount"] or 0)
        if amount:
            balance = db.add_credits(row["user_id"], amount)
            if balance is not None:
                db.ledger_add(row["user_id"], amount, balance, "refund", str(charge_id), note)
    return True


def refund_ref(ref, note="下载未完成，已退回") -> int:
    """按 ref 退回整组权益（批量任务里的一首），返回退回条数。"""
    count = 0
    for row in db.get_charges_by_ref(ref):
        if row["status"] != "refunded" and refund(row["id"], note):
            count += 1
    return count


def refund_job(job_id, note="任务未完成，已退回") -> int:
    """退回整个任务占用的权益（任务整体失败时用）。"""
    rows = db.query(
        "SELECT id FROM charges WHERE ref LIKE ? AND status!='refunded'", (f"{job_id}:%",)
    )
    count = 0
    for row in rows:
        if refund(row["id"], note):
            count += 1
    return count
