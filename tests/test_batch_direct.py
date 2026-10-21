"""批量「前端串行直连」自测：通道判定 / 扣费 / 302 可用 / 降级复用不双扣"""
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.services import pricing


app = create_app()
stamp = int(time.time())


def show(name, r):
    print("[%s] %s %s" % (name, r.status_code, json.dumps(r.get_json() or {}, ensure_ascii=False)[:300]))
    return r.get_json() or {}


# 1. 匿名
c = app.test_client()
r = c.post("/api/download/batch/direct", json={"track_keys": ["x"], "quality": "mp3"})
show("anon", r)
assert r.status_code == 401

# 2. 注册登录
email = "bd%d@test.com" % stamp
r = c.post("/api/auth/register", json={"email": email, "password": "123456", "nickname": "直连"})
assert r.status_code == 200, r.get_json()

# 3. 搜 3 首
r = c.get("/api/search?q=稻香 周杰伦&platforms=NeteaseMusicClient")
res = (r.get_json() or {}).get("results") or []
assert res and res[0]["tracks"], "搜索没有结果"
tracks = res[0]["tracks"][:3]
keys = [t["track_key"] for t in tracks]
print("搜到 %d 首，取前 %d 首" % (len(res[0]["tracks"]), len(keys)))

# 4. 批量直连预取：应全部拿到 browser 通道，并扣掉 3 次免费额度
r = c.post("/api/download/batch/direct", json={"track_keys": keys, "quality": "mp3"})
body = show("direct", r)
assert r.status_code == 200, body
ready = body["ready"]
assert len(ready) == 3, body
assert body["need_server"] == [], body["need_server"]
assert body["wallet"]["free_left"] == 7, body["wallet"]

for item in ready:
    assert item["mode"] == "browser", item
    assert item["url"].startswith("/api/dl/"), item
    assert item["filename"].endswith(".mp3"), item
    tags = item["tags"]
    assert tags["title"] and tags["artist"], tags
    assert tags["lyric"], "标签里没有歌词"
    print("  %-28s %-46s credit=%s free=%s cover=%s" % (
        item["filename"][:28], item["track_key"][:46],
        item["charged"]["amount"], item["charged"]["free"], bool(tags["cover"])))

# 5. 签发的直链确实能用（302 到 CDN，不跟随即不耗流量）
resp = c.get(ready[0]["url"])
print("[302] %s -> %s" % (resp.status_code, (resp.headers.get("Location") or "")[:70]))
assert resp.status_code == 302
assert resp.headers.get("Referrer-Policy") == "no-referrer"

# 6. 模拟「浏览器直连失败 → 服务端兜底」：带 reuse_charge_ids 不能重复扣费
with app.app_context():
    uid = db.get_user_by_email(email)["id"]
    before_credits = db.get_credits(uid)
    before_free = pricing.free_left(uid)
reuse = {ready[0]["track_key"]: ready[0]["charge_id"],
         ready[1]["track_key"]: ready[1]["charge_id"]}
r = c.post("/api/download/batch", json={
    "track_keys": [ready[0]["track_key"], ready[1]["track_key"]],
    "quality": "mp3",
    "reuse_charge_ids": reuse,
})
body = show("fallback", r)
assert r.status_code == 200, body
with app.app_context():
    after_credits = db.get_credits(uid)
    after_free = pricing.free_left(uid)
print("  复用前后：积分 %s→%s，免费 %s→%s" % (before_credits, after_credits, before_free, after_free))
assert after_credits == before_credits, "复用被重复扣了积分"
assert after_free == before_free, "复用被重复扣了免费额度"

# 7. 积分不足：额度耗尽 + 零余额 → 402，且一首都不许扣
email2 = "bdb%d@test.com" % stamp
c2 = app.test_client()
r = c2.post("/api/auth/register", json={"email": email2, "password": "123456", "nickname": "穷号"})
assert r.status_code == 200, r.get_json()
with app.app_context():
    uid2 = db.get_user_by_email(email2)["id"]
    db.execute("UPDATE users SET credits=0 WHERE id=?", (uid2,))
    db.execute(
        "INSERT INTO free_quota(user_id,day,used) VALUES(?,?,10) "
        "ON CONFLICT(user_id,day) DO UPDATE SET used=10",
        (uid2, pricing.today()),
    )
r = c2.post("/api/download/batch/direct", json={"track_keys": keys, "quality": "mp3"})
body = show("402", r)
assert r.status_code == 402 and body["code"] == "credits_insufficient", body
assert body["need"] == 30 and body["short"] == 30, body
with app.app_context():
    assert db.get_credits(uid2) == 0
    assert pricing.free_left(uid2) == 0
    pending = db.one("SELECT COUNT(*) c FROM charges WHERE user_id=? AND status!='refunded'", (uid2,))
    assert pending["c"] == 0, "402 时不该留下扣费记录"

# 8. 无损走 302 直连（1 首，50 积分）
with app.app_context():
    db.add_credits(uid2, 50)
r = c2.post("/api/download/batch/direct", json={"track_keys": [keys[0]], "quality": "flac"})
body = show("flac", r)
assert r.status_code == 200, body
if body["ready"]:
    item = body["ready"][0]
    assert item["mode"] == "direct", item
    assert item["charged"]["amount"] == 50, item
    assert body["wallet"]["credits"] == 0, body["wallet"]
    resp = c2.get(item["url"])
    print("[flac302] %s -> %s" % (resp.status_code, (resp.headers.get("Location") or "")[:60]))
    assert resp.status_code == 302
else:
    print("  该曲目源站无无损，走服务端：", body["need_server"])
    assert body["need_server"] and body["need_server"][0]["reason"]

print("ALL OK")
