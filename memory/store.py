"""
持久记忆 + Agent 消息通信
所有数据存在本地 SQLite，重启不丢
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
DB = ROOT / "memory" / "memory.sqlite"
INIT = ROOT / "memory" / "init.sql"


def _conn():
    c = sqlite3.connect(DB)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db():
    with open(INIT, encoding="utf-8") as f:
        sql = f.read()
    conn = _conn()
    conn.executescript(sql)
    conn.commit()
    conn.close()


def remember(agent_id: str, key: str, value):
    """写一条记忆"""
    conn = _conn()
    conn.execute(
        "INSERT INTO agent_memory (agent_id, key, value, updated_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(agent_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (agent_id, key, json.dumps(value, ensure_ascii=False),
         datetime.now(timezone.utc).isoformat())
    )
    conn.commit()
    conn.close()


def recall(agent_id: str, key: str, default=None):
    """读一条记忆"""
    conn = _conn()
    cur = conn.execute(
        "SELECT value FROM agent_memory WHERE agent_id=? AND key=?",
        (agent_id, key)
    )
    row = cur.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return default


def all_memories(agent_id: str) -> dict:
    """读一个 Agent 的全部记忆"""
    conn = _conn()
    cur = conn.execute(
        "SELECT key, value FROM agent_memory WHERE agent_id=?", (agent_id,)
    )
    rows = cur.fetchall()
    conn.close()
    return {k: json.loads(v) for k, v in rows}


def send_message(from_agent: str, to_agent: str, content: str):
    """给另一个 Agent 发消息"""
    conn = _conn()
    conn.execute(
        "INSERT INTO agent_messages (ts, from_agent, to_agent, content) "
        "VALUES (?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), from_agent, to_agent, content)
    )
    conn.commit()
    conn.close()


def read_messages(agent_id: str) -> list:
    """读发给我的未读消息"""
    conn = _conn()
    cur = conn.execute(
        "SELECT id, ts, from_agent, content FROM agent_messages "
        "WHERE to_agent=? AND read=0 ORDER BY id",
        (agent_id,)
    )
    rows = cur.fetchall()
    if rows:
        ids = [r[0] for r in rows]
        conn.execute(
            f"UPDATE agent_messages SET read=1 WHERE id IN ({','.join('?'*len(ids))})",
            ids
        )
        conn.commit()
    conn.close()
    return [{"id": r[0], "ts": r[1], "from": r[2], "content": r[3]} for r in rows]


if __name__ == "__main__":
    init_db()
    remember("agent-A", "task", "整理文件")
    remember("agent-A", "progress", 3)
    send_message("agent-A", "agent-B", "我整理到第 3 步了")
    print("agent-A 记忆:", all_memories("agent-A"))
    print("agent-B 收到:", read_messages("agent-B"))