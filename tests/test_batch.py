"""搜索结果批量下载自测：登录 / 额度 / 上限 / 积分不足 / 任务列表带曲目"""
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
    print("[%s] %s %s" % (name, r.status_code, json.dumps(r.get_json(), ensure_ascii=False)[:260]))
    return r.get_json()


# 1. 匿名
c = app.test_client()
r = c.post("/api/download/batch", json={"track_keys": ["x"], "quality": "mp3"})
show("anon", r)
assert r.status_code == 401

# 2. 注册登录
email = "batch%d@test.com" % stamp
r = c.post("/api/auth/register", json={"email": email, "password": "123456", "nickname": "批量"})
assert r.status_code == 200, r.get_json()

# 3. 搜 3 首
r = c.get("/api/search?q=稻香 周杰伦&platforms=NeteaseMusicClient")
res = (r.get_json() or {}).get("results") or []
assert res and res[0]["tracks"], "搜索没有结果"
tracks = res[0]["tracks"][:3]
keys = [t["track_key"] for t in tracks]
print("搜到 %d 首，取前 %d 首批量" % (len(res[0]["tracks"]), len(keys)))

# 4. 批量提交
r = c.post("/api/download/batch", json={"track_keys": keys, "quality": "mp3"})
body = show("batch", r)
assert r.status_code == 200, body
job_id = body["job_id"]
assert body["total"] == 3, body
assert body["plan"]["free"] == 3, body["plan"]          # 新号 10 首额度，3 首全免费
assert body["wallet"]["free_left"] == 7, body["wallet"]

# 5. 任务列表要带每一首（供逐首下载），且批量任务不给 ZIP
r = c.get("/api/jobs")
jobs = (r.get_json() or {}).get("jobs") or []
job = [j for j in jobs if j["id"] == job_id]
assert job, "任务列表里找不到刚建的任务"
job = job[0]
print("任务 kind=%s items=%d zip=%s status=%s" % (job["kind"], len(job["items"]), job["zip"], job["status"]))
assert job["kind"] == "batch"
assert len(job["items"]) == 3
assert job["zip"] is False

# 6. 上限
too_many = ["k%d" % i for i in range(500)]
r = c.post("/api/download/batch", json={"track_keys": too_many, "quality": "mp3"})
print("上限:", r.status_code, r.get_json().get("error"))
assert r.status_code == 400 and r.get_json()["code"] == "too_many"

# 7. 全部过期
r = c.post("/api/download/batch", json={"track_keys": ["NeteaseMusicClient:none"], "quality": "mp3"})
print("过期:", r.status_code, r.get_json().get("error"))
assert r.status_code == 404

# 8. 积分不足：额度用尽 + 余额 0
email2 = "batchb%d@test.com" % stamp
c2 = app.test_client()
r = c2.post("/api/auth/register", json={"email": email2, "password": "123456", "nickname": "穷号"})
assert r.status_code == 200, r.get_json()
with app.app_context():
    uid = db.get_user_by_email(email2)["id"]
    db.execute("UPDATE users SET credits=0 WHERE id=?", (uid,))
    db.execute(
        "INSERT INTO free_quota(user_id,day,used) VALUES(?,?,10) "
        "ON CONFLICT(user_id,day) DO UPDATE SET used=10",
        (uid, pricing.today()),
    )
r = c2.post("/api/download/batch", json={"track_keys": keys, "quality": "mp3"})
body = show("402", r)
assert r.status_code == 402 and body["code"] == "credits_insufficient"
assert body["need"] == 30 and body["short"] == 30, body

# 9. 充 50 积分后成功，且按 10/首 扣
with app.app_context():
    db.add_credits(uid, 50)
r = c2.post("/api/download/batch", json={"track_keys": keys, "quality": "mp3"})
body = show("paid", r)
assert r.status_code == 200, body
assert body["plan"]["credits"] == 30 and body["plan"]["free"] == 0, body["plan"]
assert body["wallet"]["credits"] == 20, body["wallet"]

# 10. 无损按 50/首：余额 20 不够 3 首（150）
r = c2.post("/api/download/batch", json={"track_keys": keys, "quality": "flac"})
body = show("flac402", r)
assert r.status_code == 402 and body["need"] == 150, body

print("ALL OK")
