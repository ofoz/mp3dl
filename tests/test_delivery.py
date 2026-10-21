"""端到端：ZIP 打包 + 文件交付（验证 token 改造没有破坏下载链路）"""
import io
import os
import sqlite3
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402

app = create_app()
c = app.test_client()

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "mp3dl.db")
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

job = conn.execute(
    "SELECT * FROM jobs WHERE finished>0 ORDER BY created_at DESC LIMIT 1").fetchone()
if not job:
    print("没有已完成的任务，跳过")
    sys.exit(0)

owner = conn.execute("SELECT * FROM users WHERE id=?", (job["user_id"],)).fetchone()
print(f"任务 {job['id']}  owner={owner['email'] if owner else '?'}  finished={job['finished']}")

r = c.post("/api/auth/login", json={"email": owner["email"], "password": "123456"},
           environ_base={"REMOTE_ADDR": "198.51.100.61"})
if r.status_code != 200:
    # 测试账号密码可能不是 123456，改用环境变量里的管理员
    admin_email = os.environ.get("MP3DL_TEST_ADMIN_EMAIL", "")
    admin_pwd = os.environ.get("MP3DL_TEST_ADMIN_PASSWORD", "")
    if not (admin_email and admin_pwd):
        print("跳过：需要 MP3DL_TEST_ADMIN_EMAIL / MP3DL_TEST_ADMIN_PASSWORD 才能以管理员身份验证")
        sys.exit(0)
    r = c.post("/api/auth/login", json={"email": admin_email, "password": admin_pwd},
               environ_base={"REMOTE_ADDR": "198.51.100.61"})
    print("  用管理员身份:", r.status_code)
assert r.status_code == 200, r.get_json()

zip_dir = Config.TMP_DIR / "zip"
zip_dir.mkdir(parents=True, exist_ok=True)
before = {p.name for p in zip_dir.glob("*.zip")}
r = c.get(f"/api/jobs/{job['id']}/zip", environ_base={"REMOTE_ADDR": "198.51.100.61"})
print("  ZIP 状态:", r.status_code, "| 大小:", len(r.data))
assert r.status_code == 200, r.get_data(as_text=True)[:200]

zf = zipfile.ZipFile(io.BytesIO(r.data))
names = zf.namelist()
print("  ZIP 内文件:", names)
assert names, "ZIP 为空（JOIN files ON token 可能没生效）"
for n in names:
    assert "/" not in n and "\\" not in n and not n.startswith(".."), f"异常路径 {n}"

r.close()
after = {p.name for p in zip_dir.glob("*.zip")}
leaked = after - before - {f"{job['id']}.zip"}
# 同名覆盖不算泄漏；只有出现「别的任务名」或同任务多个副本才说明没控制住
dup = [p for p in zip_dir.glob("*.zip") if p.name.startswith(job["id"])]
print("  打包目录内本任务文件数:", len(dup), "| 其他残留:", leaked or "无")
assert len(dup) <= 1 and not leaked, (dup, leaked)

# 交付单个文件
item = conn.execute("SELECT file_id,song_name FROM job_items WHERE job_id=? AND status='done' LIMIT 1",
                    (job["id"],)).fetchone()
r = c.get(f"/api/files/{item['file_id']}", environ_base={"REMOTE_ADDR": "198.51.100.61"})
print(f"  单文件 {item['song_name']}: {r.status_code}  {len(r.data)} 字节")
if r.status_code == 200:
    r.close()
assert r.status_code == 200

print("\nZIP / 文件交付 全部正常")
