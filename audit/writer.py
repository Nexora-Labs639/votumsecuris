import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
DB = ROOT / "audit" / "log.sqlite"

def _conn():
    c = sqlite3.connect(DB)
    c.execute("PRAGMA journal_mode=WAL")
    return c

def log(agent_id: str, tool_name: str, params: dict,
        result: str = "", status: str = "ok", undo_of: int = None) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO audit_log (ts, agent_id, tool_name, params, result, status, undo_of) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(),
         agent_id, tool_name,
         json.dumps(params, ensure_ascii=False),
         result, status, undo_of)
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id

def tail(n: int = 10):
    conn = _conn()
    cur = conn.execute(
        "SELECT id, ts, agent_id, tool_name, status FROM audit_log ORDER BY id DESC LIMIT ?", (n,))
    rows = cur.fetchall()
    conn.close()
    return rows

if __name__ == "__main__":
    log("agent-001", "read_file", {"path": "test.txt"}, "hello world", "ok")
    log("agent-001", "run_shell", {"command": "rm -rf /"}, "", "denied")
    print("最近日志：")
    for r in tail(5):
        print(" ", r)