"""冒烟：重启后走一遍真实链路（搜索 -> 直连下载 -> 封面代理）

需要真实账号：先设置 MP3DL_TEST_ADMIN_EMAIL / MP3DL_TEST_ADMIN_PASSWORD，
再对已启动的服务执行本脚本。
"""
import os
import sys
import time

import requests

BASE = "http://127.0.0.1:9080"
H = {"X-Forwarded-For": "198.51.100.90"}

EMAIL = os.environ.get("MP3DL_TEST_ADMIN_EMAIL", "")
PASSWORD = os.environ.get("MP3DL_TEST_ADMIN_PASSWORD", "")
if not (EMAIL and PASSWORD):
    print("未设置 MP3DL_TEST_ADMIN_EMAIL / MP3DL_TEST_ADMIN_PASSWORD，跳过登录后的冒烟")
    sys.exit(0)

s = requests.Session()
print("首页:", s.get(BASE + "/", timeout=10).status_code)
print("admin 页:", s.get(BASE + "/admin", timeout=10).status_code)
print("平台列表:", s.get(BASE + "/api/platforms", timeout=10).status_code)

r = s.post(BASE + "/api/auth/login",
           json={"email": EMAIL, "password": PASSWORD}, headers=H, timeout=15)
print("登录:", r.status_code)
me = s.get(BASE + "/api/auth/me", timeout=10).json()["user"]
print("钱包:", me["wallet"]["credits"], "积分 / 免费", me["wallet"]["free_left"])

r = s.get(BASE + "/api/search", params={"q": "稻香", "platforms": "NeteaseMusicClient"},
          headers=H, timeout=90)
data = r.json()
tracks = [t for x in data.get("results", []) for t in x.get("tracks", [])]
print("搜索结果:", len(tracks), "首")

mp3 = [t for t in tracks if t["ext"] == "mp3"]
if not mp3:
    print("没有 mp3 曲目，跳过下载冒烟（音源此刻不稳）")
    sys.exit(0)

t = mp3[0]
print("选用:", t["song_name"], "|", t["platform"], "| 价格", t["price"]["mp3"])
d = s.post(BASE + "/api/download", json={"track_key": t["track_key"], "quality": "mp3"},
           headers=H, timeout=60).json()
print("下载响应 mode:", d.get("mode"), "| charge:", d.get("charge_id"), "| 扣费:", d.get("charged"))

if d.get("mode") == "browser":
    print("  文件名:", d.get("filename"))
    print("  直连令牌 URL:", d.get("url")[:28], "...")
    head = s.head(BASE + d["url"], headers=H, allow_redirects=False, timeout=20)
    print("  HEAD /api/dl:", head.status_code, "(302 表示直连可用)")
    cover = (d.get("tags") or {}).get("cover") or ""
    if cover.startswith("/api/cover/"):
        rc = s.get(BASE + cover, headers=H, timeout=20)
        print("  封面代理:", rc.status_code, rc.headers.get("content-type"), len(rc.content), "字节")
    elif cover.startswith("http"):
        print("  封面走 CDN 直连（不经过本站）:", cover[:50])
else:
    print("  服务端任务:", d.get("job_id"))

w2 = s.get(BASE + "/api/auth/wallet", timeout=10).json()["wallet"]
print("下载后: 积分", w2["credits"], "/ 今日免费剩", w2["free_left"])
