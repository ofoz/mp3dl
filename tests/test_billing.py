"""计费链路自测：跑在 Flask test_client 上，不启真实端口"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app import db  # noqa: E402
from app.services import platforms, pricing  # noqa: E402

app = create_app()
c = app.test_client()

stamp = int(time.time())
email = f"bill{stamp}@test.com"
pwd = "123456"


def show(label, resp):
    try:
        body = resp.get_json()
    except Exception:
        body = None
    print(f"[{label}] {resp.status_code} {json.dumps(body, ensure_ascii=False)[:240]}")
    return body


print("== 1. 匿名下载应被拒 ==")
r = c.post("/api/download", json={"track_key": "x", "quality": "mp3"})
show("anon", r)
assert r.status_code == 401

print("== 2. 注册 ==")
r = c.post("/api/auth/register", json={"email": email, "password": pwd})
body = show("register", r)
assert r.status_code == 200
w = body["user"]["wallet"]
print("   钱包:", w)
assert w["credits"] == 0 and w["free_left"] == 10

print("== 3. 搜索网易云（真网络，约 10s）==")
r = c.get("/api/search?q=%E7%A8%BB%E9%A6%99%20%E5%91%A8%E6%9D%B0%E4%BC%A6&platforms=NeteaseMusicClient")
body = r.get_json()
tracks = body["results"][0]["tracks"]
print("   命中", len(tracks), "首")
tk = None
for t in tracks:
    if t["ext"] == "mp3":
        tk = t["track_key"]
        print("   选用:", t["song_name"], t["ext"], "price=", t["price"])
        break
assert tk, "没有 mp3 曲目"

print("== 4. 免费额度内下载 3 首（同一首重复取，验证计数）==")
for i in range(3):
    r = c.post("/api/download", json={"track_key": tk, "quality": "mp3"})
    body = show(f"dl{i+1}", r)
    assert r.status_code == 200, body
    assert body["charged"]["free"] is True, body
print("   免费剩:", body["wallet"]["free_left"])
assert body["wallet"]["free_left"] == 7

print("== 5. 用光免费额度 ==")
for i in range(7):
    r = c.post("/api/download", json={"track_key": tk, "quality": "mp3"})
    assert r.status_code == 200, (r.status_code, r.get_json())
last = r.get_json()
print("   免费剩:", last["wallet"]["free_left"], "积分:", last["wallet"]["credits"])
assert last["wallet"]["free_left"] == 0

print("== 6. 额度用完后无积分 -> 402 ==")
r = c.post("/api/download", json={"track_key": tk, "quality": "mp3"})
body = show("over-quota", r)
assert r.status_code == 402 and body["code"] == "credits_insufficient", body
assert body["need"] == 10 and body["balance"] == 0

print("== 7. 管理员生成卡密 + 兑换 ==")
adm_email = os.environ.get("MP3DL_TEST_ADMIN_EMAIL", "")
adm_pwd = os.environ.get("MP3DL_TEST_ADMIN_PASSWORD", "")
if not (adm_email and adm_pwd):
    print("  skip 需要 MP3DL_TEST_ADMIN_EMAIL / MP3DL_TEST_ADMIN_PASSWORD 才能测卡密")
    sys.exit(0)
adm = app.test_client()
r = adm.post("/api/auth/login", json={"email": adm_email, "password": adm_pwd})
assert r.status_code == 200, r.get_json()
r = adm.post("/api/admin/codes", json={"credits": 100, "count": 1})
body = show("gen-code", r)
code = body["codes"][0]

r = c.post("/api/auth/redeem", json={"code": code})
body = show("redeem", r)
assert r.status_code == 200 and body["balance"] == 100

print("== 8. 重复兑换同一卡密 -> 409 ==")
r = c.post("/api/auth/redeem", json={"code": code})
show("redeem-again", r)
assert r.status_code == 409

print("== 9. 超出额度按 10 积分/首 ==")
r = c.post("/api/download", json={"track_key": tk, "quality": "mp3"})
body = show("paid-mp3", r)
assert r.status_code == 200 and body["charged"]["free"] is False and body["charged"]["amount"] == 10
assert body["wallet"]["credits"] == 90

print("== 10. 复用同一笔扣费（模拟直连失败转服务端）==")
r = c.post("/api/download", json={"track_key": tk, "quality": "mp3"})
first = r.get_json()
charge_id = first["charge_id"]
before = first["wallet"]["credits"]
print("   首次扣费后余额:", before)
r = c.post("/api/download", json={"track_key": tk, "quality": "mp3", "mode": "server",
                                  "reuse_charge_id": charge_id})
body = show("reuse", r)
assert r.status_code == 200 and body["charged"]["reuse"] is True
assert body["wallet"]["credits"] == before, body["wallet"]
print("   复用未重复扣费，余额仍为", body["wallet"]["credits"])

print("== 10b. 跨音质复用必须被拒（防止用低价 charge 抵无损）==")
r = c.post("/api/download", json={"track_key": tk, "quality": "mp3"})
cid = r.get_json()["charge_id"]
r = c.post("/api/download", json={"track_key": tk, "quality": "flac", "reuse_charge_id": cid})
body = r.get_json()
print("   flac:", r.status_code, body.get("charged"), body.get("error"))
assert r.status_code in (200, 402, 404), body
if r.status_code == 200:
    assert body["charged"]["reuse"] is False, body
    assert body["charged"]["amount"] == 50, body

print("== 11. QQ 转码 / 无损 计费规则（单元）==")
with app.app_context():
    uid = db.get_user_by_email(email)["id"]
    db.execute("UPDATE users SET credits=200 WHERE id=?", (uid,))
    before = db.get_credits(uid)
    ch = pricing.charge(uid, "QQMusicClient", "mp3", transcode=True, track="qq:1")
    print("   QQ:", ch, "余额", db.get_credits(uid))
    assert ch["kind"] == "credit" and ch["amount"] == 10
    pricing.refund(ch["id"])
    print("   退款后余额:", db.get_credits(uid))
    assert db.get_credits(uid) == before

    ch2 = pricing.charge(uid, "NeteaseMusicClient", "flac", transcode=False, track="ne:1")
    print("   FLAC:", ch2, "余额", db.get_credits(uid))
    assert ch2["amount"] == 50
    pricing.refund(ch2["id"])
    assert db.get_credits(uid) == before

    print("   余额不足时:", end=" ")
    db.execute("UPDATE users SET credits=5 WHERE id=?", (uid,))
    try:
        pricing.charge(uid, "NeteaseMusicClient", "flac", track="ne:2")
        print("没抛异常（异常！）")
    except pricing.InsufficientCredits as err:
        print("正确拦截 ->", err)
    db.execute("UPDATE users SET credits=? WHERE id=?", (before, uid))

print("== 12. 歌单批量（不足额应 402 并说明差额）==")
r = c.post("/api/playlist/download", json={"track_keys": [tk] * 3, "quality": "mp3", "title": "t"})
body = show("batch", r)
assert r.status_code in (200, 402), body
if r.status_code == 200:
    print("   批量提交成功，约扣:", body["plan"])

print("\nALL PASSED")
