"""SQLite 数据层：建表 + 轻量 DAO"""
import sqlite3
import time
import json
import secrets
import threading
from pathlib import Path

from .config import Config

_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    nickname TEXT DEFAULT '',
    is_admin INTEGER DEFAULT 0,
    credits INTEGER DEFAULT 0,
    vip_expire_at INTEGER DEFAULT 0,
    status INTEGER DEFAULT 1,
    created_at INTEGER NOT NULL,
    last_login_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    ip TEXT DEFAULT '',
    ua TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    token TEXT,
    sha1 TEXT NOT NULL,
    path TEXT NOT NULL,
    ext TEXT NOT NULL,
    size INTEGER DEFAULT 0,
    quality TEXT DEFAULT 'mp3',
    song_name TEXT DEFAULT '',
    singers TEXT DEFAULT '',
    duration_s INTEGER DEFAULT 0,
    platform TEXT DEFAULT '',
    created_at INTEGER NOT NULL,
    last_access INTEGER NOT NULL,
    hits INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_files_sha1 ON files(sha1);
CREATE INDEX IF NOT EXISTS idx_files_access ON files(last_access);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    user_id INTEGER DEFAULT 0,
    ip TEXT DEFAULT '',
    quality TEXT DEFAULT 'mp3',
    title TEXT DEFAULT '',
    status TEXT DEFAULT 'queued',
    total INTEGER DEFAULT 0,
    finished INTEGER DEFAULT 0,
    failed INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);

CREATE TABLE IF NOT EXISTS job_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    platform TEXT DEFAULT '',
    track_key TEXT DEFAULT '',
    song_name TEXT DEFAULT '',
    singers TEXT DEFAULT '',
    album TEXT DEFAULT '',
    cover_url TEXT DEFAULT '',
    lyric TEXT DEFAULT '',
    quality TEXT DEFAULT 'mp3',
    status TEXT DEFAULT 'pending',
    error TEXT DEFAULT '',
    file_id TEXT DEFAULT '',
    source_used TEXT DEFAULT '',
    updated_at INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_items_job ON job_items(job_id);

CREATE TABLE IF NOT EXISTS rate_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ip TEXT NOT NULL,
    action TEXT NOT NULL,
    amount INTEGER DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rate ON rate_events(ip, action, created_at);

-- 积分卡密：一张卡密固定面额，兑换后直接进余额
CREATE TABLE IF NOT EXISTS credit_codes (
    code TEXT PRIMARY KEY,
    credits INTEGER NOT NULL,
    used_by INTEGER DEFAULT 0,
    used_at INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    note TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_credit_codes_used ON credit_codes(used_by);

-- 每日免费额度（按账号 + 自然日），used 用原子自增守住上限
CREATE TABLE IF NOT EXISTS free_quota (
    user_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    used INTEGER DEFAULT 0,
    PRIMARY KEY (user_id, day)
);

-- 每笔下载权益：kind=free 消耗免费额度，kind=credit 扣积分
-- status: held（已占位，任务未完成） / committed（已交付） / refunded（已退回）
CREATE TABLE IF NOT EXISTS charges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    amount INTEGER DEFAULT 0,
    status TEXT DEFAULT 'held',
    platform TEXT DEFAULT '',
    quality TEXT DEFAULT 'mp3',
    ref TEXT DEFAULT '',
    track TEXT DEFAULT '',
    created_at INTEGER NOT NULL,
    settled_at INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_charges_user ON charges(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_charges_ref ON charges(ref);

-- 积分流水（兑换 / 消费 / 退款 / 后台调整）
CREATE TABLE IF NOT EXISTS credit_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    balance INTEGER NOT NULL,
    kind TEXT NOT NULL,
    ref TEXT DEFAULT '',
    note TEXT DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ledger_user ON credit_ledger(user_id, created_at);

CREATE TABLE IF NOT EXISTS download_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER DEFAULT 0,
    ip TEXT DEFAULT '',
    platform TEXT DEFAULT '',
    song_name TEXT DEFAULT '',
    quality TEXT DEFAULT '',
    size INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL
);
"""


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "conn", None)
    if conn is None:
        Config.ensure_dirs()
        conn = sqlite3.connect(str(Config.DB_PATH), timeout=15, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        _local.conn = conn
    return conn


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.commit()


def _migrate(conn):
    """老库补列：users.credits / files.token 都是后加的。"""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "credits" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN credits INTEGER DEFAULT 0")
    conn.execute("UPDATE users SET credits=0 WHERE credits IS NULL")

    # files.token：对外只暴露随机 token，sha1(id) 不再出现在 URL 里。
    # 否则前端能由 track_key 直接算出 file_id（sha1(平台:曲目id:歌名:音质)），
    # 登录后 GET /api/files/<file_id> 就能白拿别人付过费的缓存文件。
    fcols = {row["name"] for row in conn.execute("PRAGMA table_info(files)")}
    if "token" not in fcols:
        conn.execute("ALTER TABLE files ADD COLUMN token TEXT")
    conn.execute("UPDATE files SET token=lower(hex(randomblob(16))) WHERE token IS NULL OR token=''")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_files_token ON files(token)")

    # 老任务的 job_items.file_id 存的是 sha1，改成随机 token，
    # 否则升级后旧任务点下载会 404、ZIP 也打包不到文件。
    conn.execute(
        """UPDATE job_items
              SET file_id = (SELECT files.token FROM files WHERE files.id = job_items.file_id)
            WHERE file_id != ''
              AND EXISTS (SELECT 1 FROM files WHERE files.id = job_items.file_id)"""
    )


def now() -> int:
    return int(time.time())


# ---------- 通用 ----------
def query(sql, args=()):
    cur = get_conn().execute(sql, args)
    rows = cur.fetchall()
    return [dict(r) for r in rows]


def one(sql, args=()):
    rows = query(sql, args)
    return rows[0] if rows else None


def execute(sql, args=()):
    conn = get_conn()
    cur = conn.execute(sql, args)
    conn.commit()
    return cur


# ---------- 用户 ----------
def create_user(email, password_hash, nickname="", is_admin=0):
    return execute(
        "INSERT INTO users(email,password_hash,nickname,is_admin,created_at) VALUES(?,?,?,?,?)",
        (email.lower().strip(), password_hash, nickname, is_admin, now()),
    )


def get_user_by_email(email):
    return one("SELECT * FROM users WHERE email=?", (email.lower().strip(),))


def get_user(uid):
    return one("SELECT * FROM users WHERE id=?", (uid,))


def list_users(limit=100, offset=0):
    return query("SELECT * FROM users ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))


def touch_login(uid):
    execute("UPDATE users SET last_login_at=? WHERE id=?", (now(), uid))


# ---------- 积分 ----------
def get_credits(uid):
    row = one("SELECT credits FROM users WHERE id=?", (uid,))
    return int(row["credits"] or 0) if row else 0


def add_credits(uid, delta):
    """加减积分（delta 可为负），返回变动后余额。负数不会扣成负数。"""
    if delta < 0:
        if not spend_credits(uid, -delta):
            return None
        return get_credits(uid)
    execute("UPDATE users SET credits=COALESCE(credits,0)+? WHERE id=?", (int(delta), uid))
    return get_credits(uid)


def spend_credits(uid, amount):
    """原子扣积分：余额不足时返回 False，不会扣成负数。"""
    amount = int(amount)
    if amount <= 0:
        return True
    cur = execute(
        "UPDATE users SET credits=credits-? WHERE id=? AND COALESCE(credits,0)>=?",
        (amount, uid, amount),
    )
    return cur.rowcount > 0


def take_free_quota(uid, day, limit):
    """占用一次免费额度；已达上限返回 False（UPDATE 带 WHERE，天然原子）。"""
    limit = int(limit)
    if limit <= 0:
        return False
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO free_quota(user_id,day,used) VALUES(?,?,1)
           ON CONFLICT(user_id,day) DO UPDATE SET used=used+1 WHERE used < ?""",
        (uid, day, limit),
    )
    conn.commit()
    return cur.rowcount > 0


def free_quota_used(uid, day):
    row = one("SELECT used FROM free_quota WHERE user_id=? AND day=?", (uid, day))
    return int(row["used"]) if row else 0


def release_free_quota(uid, day):
    execute("UPDATE free_quota SET used=MAX(0,used-1) WHERE user_id=? AND day=?", (uid, day))


# ---------- 计费记录 ----------
def add_charge(user_id, kind, amount, platform="", quality="mp3", ref="", track="", status="held"):
    cur = execute(
        """INSERT INTO charges(user_id,kind,amount,status,platform,quality,ref,track,created_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (user_id, kind, int(amount), status, platform, quality, ref, track, now()),
    )
    return cur.lastrowid


def get_charge(charge_id):
    return one("SELECT * FROM charges WHERE id=?", (int(charge_id),))


def get_charges_by_ref(ref):
    return query("SELECT * FROM charges WHERE ref=? ORDER BY id ASC", (ref,))


def settle_charge(charge_id, status="committed"):
    execute("UPDATE charges SET status=?, settled_at=? WHERE id=? AND status!='refunded'",
            (status, now(), int(charge_id)))


def claim_refund(charge_id):
    """原子「抢占退款权」：只有把状态翻到 refunded 的那一个调用者才去退钱。

    先查再退会有并发窗口，两次同时退款就是双倍积分。
    """
    cur = execute(
        "UPDATE charges SET status='refunded', settled_at=? WHERE id=? AND status!='refunded'",
        (now(), int(charge_id)),
    )
    return cur.rowcount > 0


def attach_charge_job(charge_id, job_id, idx=0):
    """把一笔已有的扣费挂到任务条目上，任务失败时才能按 ref 退回。

    idx 要跟任务里的条目序号对齐：批量任务逐条按 `job_id:idx` 记账。
    """
    execute("UPDATE charges SET ref=? WHERE id=?", (f"{job_id}:{int(idx)}", int(charge_id)))


def ledger_add(user_id, delta, balance, kind, ref="", note=""):
    execute(
        "INSERT INTO credit_ledger(user_id,delta,balance,kind,ref,note,created_at) VALUES(?,?,?,?,?,?,?)",
        (user_id, int(delta), int(balance), kind, ref, note, now()),
    )


def ledger_list(user_id, limit=30):
    return query("SELECT * FROM credit_ledger WHERE user_id=? ORDER BY id DESC LIMIT ?", (user_id, limit))


# ---------- 会话 ----------
def create_session(token, uid, ttl_days, ip="", ua=""):
    t = now()
    execute(
        "INSERT INTO sessions(token,user_id,created_at,expires_at,ip,ua) VALUES(?,?,?,?,?,?)",
        (token, uid, t, t + ttl_days * 86400, ip, (ua or "")[:300]),
    )


def get_session(token):
    return one("SELECT * FROM sessions WHERE token=? AND expires_at>?", (token, now()))


def delete_session(token):
    execute("DELETE FROM sessions WHERE token=?", (token,))


# ---------- 文件 ----------
def new_file_token():
    """对外可见的文件句柄：随机、不可由曲目信息推导。"""
    return secrets.token_hex(16)


def upsert_file(file_id, sha1, path, ext, size, quality, song_name, singers, duration_s, platform):
    t = now()
    execute(
        """INSERT INTO files(id,token,sha1,path,ext,size,quality,song_name,singers,duration_s,platform,created_at,last_access,hits)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0)
           ON CONFLICT(id) DO UPDATE SET last_access=excluded.last_access""",
        (file_id, new_file_token(), sha1, path, ext, size, quality, song_name, singers,
         duration_s, platform, t, t),
    )


def get_file_by_sha1(sha1, quality):
    return one("SELECT * FROM files WHERE sha1=? AND quality=?", (sha1, quality))


def get_file(file_id):
    return one("SELECT * FROM files WHERE id=?", (file_id,))


def get_file_by_token(token):
    if not token:
        return None
    return one("SELECT * FROM files WHERE token=?", (token,))


def touch_file(file_id):
    execute("UPDATE files SET hits=hits+1, last_access=? WHERE id=?", (now(), file_id))


def expired_files(ttl_hours):
    return query("SELECT * FROM files WHERE last_access<?", (now() - ttl_hours * 3600,))


def delete_file_row(file_id):
    execute("DELETE FROM files WHERE id=?", (file_id,))


def total_cache_size():
    row = one("SELECT COALESCE(SUM(size),0) AS s FROM files")
    return int(row["s"]) if row else 0


# ---------- 任务 ----------
def create_job(job_id, kind, user_id, ip, quality, title, total):
    t = now()
    execute(
        "INSERT INTO jobs(id,kind,user_id,ip,quality,title,status,total,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (job_id, kind, user_id, ip, quality, title, "queued", total, t, t),
    )


def add_job_item(job_id, idx, track, quality):
    return execute(
        """INSERT INTO job_items(job_id,idx,platform,track_key,song_name,singers,album,cover_url,lyric,quality,updated_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
        (
            job_id, idx, track.get("platform", ""), track.get("track_key", ""),
            track.get("song_name", ""), track.get("singers", ""), track.get("album", ""),
            track.get("cover_url", ""), (track.get("lyric") or "")[:20000], quality, now(),
        ),
    )


def get_job(job_id):
    return one("SELECT * FROM jobs WHERE id=?", (job_id,))


def update_job(job_id, **fields):
    if not fields:
        return
    fields["updated_at"] = now()
    keys = ",".join(f"{k}=?" for k in fields)
    execute(f"UPDATE jobs SET {keys} WHERE id=?", (*fields.values(), job_id))


def bump_job(job_id, field):
    """在库里自增计数。

    任务是多线程并发跑的，「读出来 +1 再写回」会丢计数：
    两首同时失败可能只记 1，最后任务状态就判错。
    """
    if field not in ("finished", "failed", "total"):
        raise ValueError("非法字段")
    execute(f"UPDATE jobs SET {field}={field}+1, updated_at=? WHERE id=?", (now(), job_id))


def get_job_items(job_id):
    return query("SELECT * FROM job_items WHERE job_id=? ORDER BY idx ASC", (job_id,))


def update_item(item_id, **fields):
    if not fields:
        return
    fields["updated_at"] = now()
    keys = ",".join(f"{k}=?" for k in fields)
    execute(f"UPDATE job_items SET {keys} WHERE id=?", (*fields.values(), item_id))


def pending_items(job_id):
    return query("SELECT * FROM job_items WHERE job_id=? AND status='pending' ORDER BY idx ASC", (job_id,))


def recent_jobs(ip="", user_id=0, limit=20):
    if user_id:
        return query("SELECT * FROM jobs WHERE user_id=? ORDER BY created_at DESC LIMIT ?", (user_id, limit))
    return query("SELECT * FROM jobs WHERE ip=? ORDER BY created_at DESC LIMIT ?", (ip, limit))


# ---------- 限流 ----------
def rate_add(ip, action, amount=1):
    execute("INSERT INTO rate_events(ip,action,amount,created_at) VALUES(?,?,?,?)", (ip, action, amount, now()))


def rate_sum(ip, action, since_ts):
    row = one("SELECT COALESCE(SUM(amount),0) AS s FROM rate_events WHERE ip=? AND action=? AND created_at>=?", (ip, action, since_ts))
    return int(row["s"]) if row else 0


def rate_gc(older_than_ts):
    execute("DELETE FROM rate_events WHERE created_at<?", (older_than_ts,))


# ---------- 卡密 ----------
def create_credit_code(code, credits, note=""):
    execute("INSERT INTO credit_codes(code,credits,created_at,note) VALUES(?,?,?,?)",
            (code, int(credits), now(), note))


def get_credit_code(code):
    return one("SELECT * FROM credit_codes WHERE code=?", (code,))


def use_credit_code(code, uid):
    """原子占用卡密：已被用掉时 rowcount 为 0。"""
    cur = execute(
        "UPDATE credit_codes SET used_by=?, used_at=? WHERE code=? AND used_by=0",
        (uid, now(), code),
    )
    return cur.rowcount > 0


def list_credit_codes(limit=100):
    return query("SELECT * FROM credit_codes ORDER BY created_at DESC LIMIT ?", (limit,))


def log_download(user_id, ip, platform, song_name, quality, size):
    execute(
        "INSERT INTO download_logs(user_id,ip,platform,song_name,quality,size,created_at) VALUES(?,?,?,?,?,?,?)",
        (user_id, ip, platform, song_name, quality, size, now()),
    )


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False)
