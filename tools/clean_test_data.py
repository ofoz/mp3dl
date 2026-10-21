"""清理测试数据：保留管理员账号，清掉其余业务数据。

用法：
    python tools/clean_test_data.py            # 只预览，不落盘
    python tools/clean_test_data.py --yes      # 备份后真删
    python tools/clean_test_data.py --yes --keep-cache   # 保留音频缓存文件

保留项：
    users 中 is_admin=1 的账号（管理员本人）
    管理员自己当前的登录会话（避免清理后被踢下线）

清除项：
    users（非管理员）、sessions（非管理员）、credit_codes、vip_codes、
    charges、credit_ledger、download_logs、free_quota、jobs、job_items、
    files、rate_events，以及 storage/cache 下已无记录的音频、
    storage/tmp/zip 下的打包残留。
"""
import argparse
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config import Config  # noqa: E402

DB = Path(Config.DB_PATH)
CACHE = Path(Config.CACHE_DIR)
ZIP_DIR = Path(Config.TMP_DIR) / "zip"
BACKUP_DIR = Path(Config.STORAGE_DIR) / "backups"

# 直接清空的表（顺序按依赖从子到父，虽然库里没有外键约束）
WIPE_TABLES = [
    "job_items",
    "jobs",
    "charges",
    "credit_ledger",
    "download_logs",
    "free_quota",
    "credit_codes",
    "vip_codes",
    "files",
    "rate_events",
]
# 需要保留管理员数据的表（按 user_id 过滤）
USER_SCOPED = ["sessions"]


# 每个管理员保留最近几次登录会话，避免清理把当前正在用的登录状态踢掉
KEEP_SESSIONS_PER_ADMIN = 5


def human(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def dir_size(path, pattern="*"):
    """递归统计：缓存按 sha1 前两位分桶，不是平铺的。"""
    root = Path(path)
    if not root.exists():
        return 0, 0
    files = [p for p in root.rglob(pattern) if p.is_file()]
    return sum(p.stat().st_size for p in files), len(files)


def admins(conn):
    return [r[0] for r in conn.execute("SELECT id FROM users WHERE is_admin=1")]


# 保留每个管理员最近 KEEP_SESSIONS_PER_ADMIN 条会话
_KEEP_SESS = (
    "SELECT token FROM ("
    "  SELECT token, ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY created_at DESC) rn"
    "  FROM sessions"
    ") WHERE rn <= ?"
)


def plan(conn):
    """返回 [(说明, SQL, 参数)]，预览与执行共用同一份逻辑。"""
    ids = admins(conn)
    marks = ",".join("?" * len(ids)) or "0"
    steps = []
    for t in WIPE_TABLES:
        steps.append((f"{t} 全部清空", f"DELETE FROM {t}", ()))
    # 非管理员会话全删；管理员只留最近几条（用户最后一次登录必然在其中）
    steps.append((
        "sessions 清掉测试会话",
        f"DELETE FROM sessions WHERE user_id NOT IN ({marks}) OR token NOT IN ({_KEEP_SESS})",
        tuple(ids) + (KEEP_SESSIONS_PER_ADMIN,),
    ))
    steps.append(("users 清掉非管理员账号",
                  "DELETE FROM users WHERE is_admin=0", ()))
    return steps, ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="真正执行（否则只预览）")
    ap.add_argument("--keep-cache", action="store_true", help="保留音频缓存文件")
    args = ap.parse_args()

    if not DB.exists():
        sys.exit(f"数据库不存在：{DB}")

    conn = sqlite3.connect(str(DB), timeout=15)
    conn.row_factory = sqlite3.Row

    ids = admins(conn)
    print(f"数据库：{DB}")
    print(f"保留管理员：{ids} "
          + ", ".join(r["email"] for r in conn.execute(
              f"SELECT email FROM users WHERE id IN ({','.join('?'*len(ids))})", tuple(ids))))
    print()

    steps, _ = plan(conn)
    print("== 计划删除 ==")
    total = 0
    for label, sql, params in steps:
        n = conn.execute(sql.replace("DELETE FROM", "SELECT COUNT(*) FROM", 1), params).fetchone()[0]
        total += n
        print(f"  {label:34} {n:>5} 行")

    csize, cnum = dir_size(CACHE)
    gsize, gnum = dir_size(ZIP_DIR, "*.zip")
    print(f"  {'storage/cache 音频缓存':34} {cnum:>5} 个 / {human(csize)}")
    print(f"  {'storage/tmp/zip 打包残留':34} {gnum:>5} 个 / {human(gsize)}")
    print(f"  合计待删：{total} 行")
    print()

    if not args.yes:
        print("预览模式，未做任何修改。确认无误后加 --yes 执行。")
        return

    # 1) 在线备份（backup API 在 WAL 下也能得到一致快照）
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    bak = BACKUP_DIR / f"mp3dl-before-clean-{stamp}.db"
    dst = sqlite3.connect(str(bak))
    with dst:
        conn.backup(dst)
    dst.close()
    print(f"已备份：{bak}  ({human(bak.stat().st_size)})")

    # 2) 单事务删除
    deleted = {}
    try:
        with conn:
            for label, sql, params in steps:
                cur = conn.execute(sql, params)
                deleted[label.split(" ")[0]] = cur.rowcount
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"删除失败，已回滚：{exc}")

    print("\n== 实际删除 ==")
    for k, v in deleted.items():
        print(f"  {k:20} {v:>5} 行")

    # 3) 重置自增序列，避免新数据从 169 这种大号开始
    with conn:
        conn.execute("DELETE FROM sqlite_sequence WHERE name IN (%s)"
                     % ",".join(f"'{t}'" for t in WIPE_TABLES + ["users"]))
    conn.execute("VACUUM")
    conn.close()
    print("已重置自增序列并 VACUUM")

    # 4) 清缓存文件（此时 files 表已空，全部是无主垃圾）
    if not args.keep_cache:
        removed, freed = 0, 0
        if CACHE.exists():
            for p in CACHE.rglob("*"):
                if p.is_file():
                    freed += p.stat().st_size
                    p.unlink()
                    removed += 1
            # 顺手清掉空的分桶目录；写入时 _cache_path 会自己 mkdir
            for d in sorted((p for p in CACHE.rglob("*") if p.is_dir()),
                            key=lambda x: len(x.parts), reverse=True):
                try:
                    d.rmdir()
                except OSError:
                    pass
        zremoved = 0
        if ZIP_DIR.exists():
            for p in ZIP_DIR.glob("*.zip"):
                freed += p.stat().st_size
                p.unlink()
                zremoved += 1
        print(f"已删缓存文件 {removed} 个、ZIP {zremoved} 个，释放 {human(freed)}")
    else:
        print("按参数保留缓存文件")

    # 5) 复核
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    print("\n== 复核 ==")
    ok = True
    for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        n = r["name"]
        try:
            c = conn.execute(f'SELECT COUNT(*) FROM "{n}"').fetchone()[0]
        except sqlite3.Error:
            continue
        print(f"  {n:18} {c}")
    left = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin=0").fetchone()[0]
    if left:
        ok = False
        print(f"  !! 仍残留 {left} 个非管理员账号")
    print("\n完成" if ok else "\n异常")


if __name__ == "__main__":
    main()
