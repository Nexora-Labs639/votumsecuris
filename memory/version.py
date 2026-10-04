"""
知识库版本化
- 每次扫描生成一个版本
- 支持版本列表、回滚、对比
"""
import sys
import json
import sqlite3
import hashlib
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "memory" / "memory.sqlite"


def _conn():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_version_table():
    conn = _conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kb_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version TEXT NOT NULL UNIQUE,
                ts TEXT NOT NULL,
                total_chunks INTEGER NOT NULL,
                file_count INTEGER NOT NULL,
                manifest TEXT NOT NULL,
                note TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ver_ts ON kb_versions(ts)")
        conn.commit()
    finally:
        conn.close()


def _next_version() -> str:
    """生成版本号：v0.1, v0.2, ..."""
    init_version_table()
    conn = _conn()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM kb_versions")
        n = cur.fetchone()[0]
        return f"v0.{n + 1}"
    finally:
        conn.close()


def snapshot(note: str = "") -> dict:
    """
    给当前 RAG 库拍快照，生成版本。
    返回: {"ok": bool, "version": str, "total_chunks": int, "file_count": int, "error": str}
    """
    from memory.rag import init_rag_table

    init_rag_table()
    init_version_table()

    conn = _conn()
    try:
        cur = conn.execute("""
            SELECT source, COUNT(*), COALESCE(content_hash, '')
            FROM rag_chunks
            GROUP BY source
        """)
        rows = cur.fetchall()

        if not rows:
            return {"ok": False, "version": "", "total_chunks": 0,
                    "file_count": 0, "error": "知识库为空，无法生成版本"}

        manifest = {}
        total_chunks = 0
        for source, cnt, chash in rows:
            manifest[source] = {"chunks": cnt, "hash": chash}
            total_chunks += cnt

        version = _next_version()
        ts = datetime.now(timezone.utc).isoformat()

        conn.execute(
            "INSERT INTO kb_versions (version, ts, total_chunks, file_count, manifest, note) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (version, ts, total_chunks, len(manifest),
             json.dumps(manifest, ensure_ascii=False), note)
        )
        conn.commit()

        return {"ok": True, "version": version, "total_chunks": total_chunks,
                "file_count": len(manifest), "error": ""}
    finally:
        conn.close()
        
def list_versions(limit: int = 20) -> list:
    """列出历史版本"""
    init_version_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT version, ts, total_chunks, file_count, note "
            "FROM kb_versions ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [
            {"version": v, "ts": t, "total_chunks": c, "file_count": f, "note": n or ""}
            for v, t, c, f, n in cur.fetchall()
        ]
    finally:
        conn.close()


def diff(version_a: str, version_b: str) -> dict:
    """对比两个版本，返回差异"""
    init_version_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT manifest FROM kb_versions WHERE version=?", (version_a,)
        )
        row_a = cur.fetchone()
        cur = conn.execute(
            "SELECT manifest FROM kb_versions WHERE version=?", (version_b,)
        )
        row_b = cur.fetchone()

        if not row_a or not row_b:
            return {"error": "版本不存在"}

        ma = json.loads(row_a[0])
        mb = json.loads(row_b[0])

        all_files = set(ma.keys()) | set(mb.keys())
        added, removed, changed, unchanged = [], [], [], []

        for f in sorted(all_files):
            in_a = f in ma
            in_b = f in mb
            if not in_a and in_b:
                added.append(f)
            elif in_a and not in_b:
                removed.append(f)
            elif ma[f].get("hash") != mb[f].get("hash"):
                changed.append(f)
            else:
                unchanged.append(f)

        return {
            "version_a": version_a,
            "version_b": version_b,
            "added": added,
            "removed": removed,
            "changed": changed,
            "unchanged_count": len(unchanged),
        }
    finally:
        conn.close()


def rollback(target_version: str) -> dict:
    """
    回滚到指定版本。
    注意：只恢复 manifest 描述的内容，不重新 embedding。
    """
    init_version_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT manifest FROM kb_versions WHERE version=?", (target_version,)
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": f"版本不存在: {target_version}"}

        manifest = json.loads(row[0])
        targets = set(manifest.keys())

        cur = conn.execute("SELECT DISTINCT source FROM rag_chunks")
        current = {r[0] for r in cur.fetchall()}

        removed = current - targets
        for src in removed:
            conn.execute("DELETE FROM rag_chunks WHERE source=?", (src,))
        conn.commit()

        return {
            "ok": True,
            "version": target_version,
            "removed": list(removed),
            "kept": list(targets),
            "note": "已按 manifest 清理；如需完整恢复，请重新扫描 knowledge/ 目录",
        }
    finally:
        conn.close()


def get_version(version: str) -> dict:
    """获取某个版本的详细信息"""
    init_version_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT version, ts, total_chunks, file_count, manifest, note "
            "FROM kb_versions WHERE version=?", (version,)
        )
        row = cur.fetchone()
        if not row:
            return {"error": "版本不存在"}
        return {
            "version": row[0],
            "ts": row[1],
            "total_chunks": row[2],
            "file_count": row[3],
            "manifest": json.loads(row[4]),
            "note": row[5] or "",
        }
    finally:
        conn.close()
        
if __name__ == "__main__":
    print("=== 生成版本 v0.1 ===")
    r = snapshot(note="首次初始化")
    print(json.dumps(r, ensure_ascii=False, indent=2))

    print("\n=== 版本列表 ===")
    for v in list_versions():
        print(f"  {v['version']} | {v['ts'][:19]} | {v['file_count']} 个文件 | {v['total_chunks']} 块 | {v['note']}")

    if r.get("ok"):
        print(f"\n=== 查看版本 {r['version']} ===")
        info = get_version(r["version"])
        print(json.dumps(info, ensure_ascii=False, indent=2))