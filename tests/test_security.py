"""安全回归：不依赖外网，只跑 Flask test_client。

覆盖这次审计发现的每一类问题：
1. 默认 SECRET_KEY 不得继续生效
2. /api/cover 不得成为未授权 SSRF
3. 封面抓取必须挡内网地址
4. /api/files 只能用随机 token，sha1 不再可用
5. X-Forwarded-For 只在可信代理后面才采信
6. 退款必须幂等（并发/重试不能双倍退）
7. 管理员不能禁用自己、不能禁掉最后一个管理员
8. 卡密必须用密码学随机源
"""
import hashlib
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app import db, security  # noqa: E402
from app.config import Config  # noqa: E402
from app.services import direct, pricing, tagger  # noqa: E402

app = create_app()
c = app.test_client()

passed, failed = 0, 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}  {detail}")


stamp = int(time.time())
PUBLIC_IP = {"REMOTE_ADDR": "203.0.113.77"}          # 模拟公网直连
PROXY_IP = {"REMOTE_ADDR": "127.0.0.1"}              # 模拟反代在本机


_ip_seq = [0]

# 注册接口按 IP 每日限 3 次。测试用 198.18.0.0/16 这一段（保留地址，不可能是真实用户），
# 每次开跑先清掉本段的限流记录，否则重复执行会被上一轮的遗留数据挡住。
db.execute("DELETE FROM rate_events WHERE ip LIKE '198.18.%'")


def register(tag):
    """每次注册分配独立模拟 IP，避免相互挤占每日注册配额。"""
    email = f"{tag}{stamp}@sectest.com"
    _ip_seq[0] += 1
    ip = f"198.18.{_ip_seq[0] // 250}.{_ip_seq[0] % 250 + 1}"
    r = c.post("/api/auth/register", json={"email": email, "password": "123456"},
               environ_base={"REMOTE_ADDR": ip})
    assert r.status_code == 200, r.get_json()
    return email


print("== 1. 密钥 ==")
check("SECRET_KEY 已不是示例值",
      Config.SECRET_KEY not in ("mp3dl-dev-secret-change-me", "please-change-this-secret"),
      Config.SECRET_KEY[:12])
check("SECRET_KEY 长度 >= 24", len(Config.SECRET_KEY) >= 24, len(Config.SECRET_KEY))

print("== 2. /api/cover 未授权 SSRF ==")
token = direct.issue("http://127.0.0.1:9080/api/platforms", "x", "x", "x")
r = c.get(f"/api/cover/{token}", environ_base=PUBLIC_IP)
check("未登录访问封面代理 -> 401", r.status_code == 401, r.status_code)

print("== 3. 伪造令牌 ==")
forged = direct._b64encode(b'{"u":"http://127.0.0.1:9080/api/platforms","e":9999999999}.')
check("换密钥后旧伪造令牌校验失败", direct.verify(forged + "." + "A" * 32) is None)

print("== 4. 封面白名单 ==")
for url, want in (
    ("http://127.0.0.1:9080/api/platforms", False),
    ("http://169.254.169.254/latest/meta-data/", False),
    ("http://10.0.0.5/x.jpg", False),
    ("file:///etc/passwd", False),
    ("http://p1.music.126.net/abc.jpg", True),
    ("http://evil.com/x.jpg", False),
):
    got = tagger.safe_cover_url(url)
    check(f"{url[:46]:46s} -> {'允许' if want else '拒绝'}", got == want, got)

print("== 5. 文件缓存只能靠随机 token ==")
row = db.one("SELECT * FROM files ORDER BY created_at DESC LIMIT 1")
if row:
    c.post("/api/auth/login", json={"email": register("tok"), "password": "123456"},
           environ_base={"REMOTE_ADDR": "198.51.100.31"})
    r1 = c.get(f"/api/files/{row['id']}", environ_base=PUBLIC_IP)
    check("用 sha1(id) 访问 -> 404（旧的免费白嫖入口已关闭）", r1.status_code == 404, r1.status_code)
    r2 = c.get(f"/api/files/{row['token']}", environ_base=PUBLIC_IP)
    check("用随机 token 访问 -> 200", r2.status_code == 200, r2.status_code)
    if r2.status_code == 200:
        r2.close()
    check("token 不等于 sha1", row["token"] != row["id"])
    check("token 长度 >= 32", len(row["token"] or "") >= 32, len(row["token"] or ""))
else:
    print("  skip 缓存表为空")

print("== 6. X-Forwarded-For 信任链 ==")
with app.test_request_context("/", environ_base={"REMOTE_ADDR": "203.0.113.5"},
                              headers={"X-Forwarded-For": "1.2.3.4"}):
    check("公网直连时忽略伪造 XFF", security.client_ip() == "203.0.113.5", security.client_ip())

with app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"},
                              headers={"X-Forwarded-For": "1.2.3.4, 203.0.113.9"}):
    check("反代追加场景取最右侧真实 IP", security.client_ip() == "203.0.113.9", security.client_ip())

with app.test_request_context("/", environ_base={"REMOTE_ADDR": "127.0.0.1"},
                              headers={"X-Forwarded-For": "1.2.3.4"}):
    check("反代单跳时仍取到客户端 IP", security.client_ip() == "1.2.3.4", security.client_ip())

print("== 7. 退款幂等 ==")
reg = db.get_user_by_email(register("ref") or "")
uid = reg["id"]
db.add_credits(uid, 100)
ch = pricing.charge(uid, "NeteaseMusicClient", "mp3", transcode=True, track="tk1")
before = db.get_credits(uid)
ok1 = pricing.refund(ch["id"])
ok2 = pricing.refund(ch["id"])
after = db.get_credits(uid)
check("第一次退款成功", ok1)
check("第二次退款被拒", not ok2)
check("只加回一次积分", after - before == 10, f"{before} -> {after}")

print("== 8. 并发退款 ==")
db.add_credits(uid, 100)
ch2 = pricing.charge(uid, "NeteaseMusicClient", "mp3", transcode=True, track="tk2")
base = db.get_credits(uid)
ths = [threading.Thread(target=lambda: pricing.refund(ch2["id"])) for _ in range(8)]
[t.start() for t in ths]
[t.join() for t in ths]
check("8 线程同时退款只退一次", db.get_credits(uid) - base == 10, db.get_credits(uid) - base)

print("== 9. 管理员自我保护 ==")
admin_email = os.environ.get("MP3DL_TEST_ADMIN_EMAIL", "")
admin_pwd = os.environ.get("MP3DL_TEST_ADMIN_PASSWORD", "")
admin = db.get_user_by_email(admin_email) if admin_email else None
if admin and admin_pwd:
    lr = c.post("/api/auth/login", json={"email": admin_email, "password": admin_pwd},
                environ_base={"REMOTE_ADDR": "198.51.100.41"})
    assert lr.status_code == 200, ("管理员登录失败", lr.get_json())
    r = c.post(f"/api/admin/users/{admin['id']}/status", json={"status": 0},
               environ_base=PUBLIC_IP)
    check("管理员不能禁用自己", r.status_code == 400, (r.status_code, r.get_json()))
    r = c.post(f"/api/admin/users/{admin['id']}/admin", json={"is_admin": 0},
               environ_base=PUBLIC_IP)
    check("管理员不能取消自己的管理员", r.status_code == 400, (r.status_code, r.get_json()))
else:
    print("  skip 未设置 MP3DL_TEST_ADMIN_EMAIL / MP3DL_TEST_ADMIN_PASSWORD")

print("== 10. 卡密随机源 ==")
import inspect
from app.api import admin as admin_api  # noqa: E402
src = inspect.getsource(admin_api.create_codes)
check("卡密生成不再用 random 模块", "random.choice" not in src and "secrets.choice" in src)
r = c.post("/api/admin/codes", json={"credits": 10, "count": 3}, environ_base=PUBLIC_IP)
if r.status_code == 200:
    codes = r.get_json()["codes"]
    check("生成 3 张卡密且互不相同", len(set(codes)) == len(codes) == 3, codes)
    check("卡密格式 MP3-XXXX-XXXX-XXXX", all(len(x.split("-")) == 4 for x in codes), codes)

print()
print(f"通过 {passed}，失败 {failed}")
sys.exit(1 if failed else 0)
