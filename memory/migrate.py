"""
数据库迁移系统
- 编号脚本
- 执行记录表
- 自动备份
- 幂等
- 并发安全
"""
import sqlite3
import shutil
import importlib
import traceback
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
DB = ROOT / "memory" / "memory.sqlite"
MIGRATIONS_DIR = ROOT / "memory" / "migrations"
BACKUP_DIR = ROOT / "memory" / "backups"


def _conn():
    c = sqlite3.connect(DB, timeout=60)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    return c


def _ensure_migrations_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS _migrations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            applied_at TEXT NOT NULL
        )
    """)
    conn.commit()


def _applied_migrations(conn) -> set:
    cur = conn.execute("SELECT name FROM _migrations ORDER BY id")
    return {row[0] for row in cur.fetchall()}


def _backup_db() -> str:
    """迁移前备份 SQLite 文件"""
    if not DB.exists():
        return ""
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = BACKUP_DIR / f"memory_{ts}.sqlite"
    try:
        shutil.copy2(DB, backup_path)
        return str(backup_path)
    except Exception:
        return ""


def _discover_migrations() -> list:
    """发现所有迁移脚本，按文件名排序"""
    if not MIGRATIONS_DIR.exists():
        return []
    files = sorted(MIGRATIONS_DIR.glob("m*.py"))
    return [f for f in files if f.stem != "__init__"]


def run_migrations(verbose: bool = True) -> dict:
    """
    执行所有未跑的迁移。
    返回: {"applied": [...], "skipped": [...], "error": str, "backup": str}
    """
    result = {"applied": [], "skipped": [], "error": "", "backup": ""}

    if not DB.parent.exists():
        DB.parent.mkdir(parents=True, exist_ok=True)

    # 备份
    if DB.exists():
        result["backup"] = _backup_db()

    conn = _conn()
    try:
        _ensure_migrations_table(conn)
        applied_set = _applied_migrations(conn)

        files = _discover_migrations()
        for f in files:
            name = f.stem
            if name in applied_set:
                result["skipped"].append(name)
                continue

            # 加载脚本
            try:
                module_path = f"memory.migrations.{name}"
                mod = importlib.import_module(module_path)
                importlib.reload(mod)
            except Exception as e:
                result["error"] = f"加载 {name} 失败: {e}"
                traceback.print_exc()
                return result

            # 执行
            try:
                if verbose:
                    print(f"[迁移] 执行 {name}")
                mod.up(conn)
                conn.execute(
                    "INSERT INTO _migrations (name, applied_at) VALUES (?, ?)",
                    (name, datetime.now(timezone.utc).isoformat())
                )
                conn.commit()
                result["applied"].append(name)
            except Exception as e:
                result["error"] = f"执行 {name} 失败: {e}"
                traceback.print_exc()
                return result

    finally:
        conn.close()

    return result


if __name__ == "__main__":
    print("=== 开始迁移 ===")
    r = run_migrations(verbose=True)
    print()
    print(f"已执行: {r['applied']}")
    print(f"已跳过: {r['skipped']}")
    if r['backup']:
        print(f"备份: {r['backup']}")
    if r['error']:
        print(f"错误: {r['error']}")