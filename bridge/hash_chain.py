"""
不可篡改审计链
- 每条日志带前一条的哈希（链式）
- 修改任何一条，后续全部失效
- 参考：Google Trillian / 区块链
"""
import sqlite3
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
DB = ROOT / "memory" / "memory.sqlite"


def _conn():
    c = sqlite3.connect(DB, timeout=60)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=30000")
    return c


def init_hash_chain_table():
    conn = _conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS hash_chain (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                data TEXT NOT NULL,
                prev_hash TEXT NOT NULL,
                self_hash TEXT NOT NULL UNIQUE
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_hc_ts ON hash_chain(ts)")
        conn.commit()
    finally:
        conn.close()


def _compute_hash(ts: str, data: str, prev_hash: str) -> str:
    """计算 self_hash = sha256(ts + data + prev_hash)"""
    content = f"{ts}|{data}|{prev_hash}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def append(data: dict) -> str:
    """
    追加一条记录到哈希链。
    返回 self_hash。
    """
    init_hash_chain_table()
    conn = _conn()
    try:
        # 拿最新一条
        cur = conn.execute("SELECT self_hash FROM hash_chain ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
        prev_hash = row[0] if row else "0" * 64

        ts = datetime.now(timezone.utc).isoformat()
        data_str = json.dumps(data, ensure_ascii=False, sort_keys=True)
        self_hash = _compute_hash(ts, data_str, prev_hash)

        conn.execute(
            "INSERT INTO hash_chain (ts, data, prev_hash, self_hash) VALUES (?, ?, ?, ?)",
            (ts, data_str, prev_hash, self_hash)
        )
        conn.commit()
        return self_hash
    finally:
        conn.close()


def verify() -> dict:
    """
    验证整条链是否完整。
    返回: {"valid": bool, "total": int, "broken_at": int or None}
    """
    init_hash_chain_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT id, ts, data, prev_hash, self_hash FROM hash_chain ORDER BY id"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return {"valid": True, "total": 0, "broken_at": None}

    prev = "0" * 64
    for r in rows:
        rid, ts, data, prev_hash, self_hash = r
        if prev_hash != prev:
            return {"valid": False, "total": len(rows), "broken_at": rid}
        expected = _compute_hash(ts, data, prev_hash)
        if expected != self_hash:
            return {"valid": False, "total": len(rows), "broken_at": rid}
        prev = self_hash

    return {"valid": True, "total": len(rows), "broken_at": None}


def get_chain(limit: int = 100) -> list:
    """拿最近 N 条"""
    init_hash_chain_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT id, ts, data, prev_hash, self_hash FROM hash_chain ORDER BY id DESC LIMIT ?",
            (limit,)
        )
        return [
            {"id": r[0], "ts": r[1], "data": r[2], "prev_hash": r[3], "self_hash": r[4]}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


if __name__ == "__main__":
    print("=== 写入 3 条 ===")
    h1 = append({"action": "read_file", "path": "D:/a.txt"})
    h2 = append({"action": "delete_file", "path": "D:/b.tmp"})
    h3 = append({"action": "run_shell", "command": "echo hello"})
    print(f"h1: {h1[:16]}...")
    print(f"h2: {h2[:16]}...")
    print(f"h3: {h3[:16]}...")

    print("\n=== 验证链 ===")
    print(verify())

    print("\n=== 模拟篡改第 2 条 ===")
    conn = _conn()
    conn.execute("UPDATE hash_chain SET data='{\"action\": \"tampered\"}' WHERE id=2")
    conn.commit()
    conn.close()

    print("=== 再次验证 ===")
    print(verify())