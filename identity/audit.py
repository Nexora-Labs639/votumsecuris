"""
审计日志（身份绑定版）
- 记录每个动作：谁（agent_uuid + user_id）在什么时间做了什么
- 支持按 agent / user / 时间段查询
- 与 audit/writer.py 互补：这个模块更结构化
"""
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "memory" / "memory.sqlite"


def _conn():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_audit_table():
    conn = _conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_identity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                agent_uuid TEXT NOT NULL,
                agent_name TEXT,
                user_id TEXT,
                tool_name TEXT NOT NULL,
                params TEXT,
                action TEXT,
                severity TEXT,
                result TEXT,
                error TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_identity(agent_uuid)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_identity(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_identity(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_tool ON audit_identity(tool_name)")
        conn.commit()
    finally:
        conn.close()
        
def record(agent_uuid: str, tool_name: str, params: dict = None,
           action: str = "", severity: str = "info",
           result: str = "", error: str = "", user_id: str = "") -> int:
    """
    记录一条审计日志。
    params 会被 JSON 序列化。
    """
    from identity.agent_id import get_agent

    init_audit_table()
    agent_info = get_agent(agent_uuid)
    agent_name = agent_info.get("name", "unknown") if agent_info.get("ok") else "unknown"

    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO audit_identity "
            "(ts, agent_uuid, agent_name, user_id, tool_name, params, action, severity, result, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                agent_uuid,
                agent_name,
                user_id or "system",
                tool_name,
                json.dumps(params or {}, ensure_ascii=False),
                action,
                severity,
                result[:1000] if result else "",
                error[:1000] if error else "",
            )
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def query(agent_uuid: str = None, user_id: str = None,
          tool_name: str = None, limit: int = 100) -> list:
    """按条件查询审计日志"""
    init_audit_table()
    sql = "SELECT ts, agent_uuid, agent_name, user_id, tool_name, action, severity, result, error FROM audit_identity WHERE 1=1"
    args = []
    if agent_uuid:
        sql += " AND agent_uuid=?"
        args.append(agent_uuid)
    if user_id:
        sql += " AND user_id=?"
        args.append(user_id)
    if tool_name:
        sql += " AND tool_name=?"
        args.append(tool_name)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)

    conn = _conn()
    try:
        cur = conn.execute(sql, args)
        return [
            {
                "ts": r[0], "agent_uuid": r[1], "agent_name": r[2],
                "user_id": r[3], "tool_name": r[4], "action": r[5],
                "severity": r[6], "result": r[7], "error": r[8],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()
        
def who_did(tool_name: str = None, limit: int = 20) -> list:
    """
    查「谁干了什么」。
    回答：某次删文件是谁下的命令。
    """
    logs = query(tool_name=tool_name, limit=limit)
    return [
        {
            "ts": log["ts"],
            "who": f"{log['agent_name']} ({log['agent_uuid'][:8]}...)",
            "user": log["user_id"],
            "tool": log["tool_name"],
            "action": log["action"],
            "result": log["result"][:100] if log["result"] else "",
        }
        for log in logs
    ]


def stats() -> dict:
    """审计统计"""
    init_audit_table()
    conn = _conn()
    try:
        cur = conn.execute("SELECT COUNT(*) FROM audit_identity")
        total = cur.fetchone()[0]

        cur = conn.execute(
            "SELECT agent_name, COUNT(*) FROM audit_identity GROUP BY agent_name"
        )
        by_agent = {r[0]: r[1] for r in cur.fetchall()}

        cur = conn.execute(
            "SELECT tool_name, COUNT(*) FROM audit_identity GROUP BY tool_name"
        )
        by_tool = {r[0]: r[1] for r in cur.fetchall()}

        cur = conn.execute(
            "SELECT severity, COUNT(*) FROM audit_identity GROUP BY severity"
        )
        by_severity = {r[0]: r[1] for r in cur.fetchall()}

        return {
            "total": total,
            "by_agent": by_agent,
            "by_tool": by_tool,
            "by_severity": by_severity,
        }
    finally:
        conn.close()


if __name__ == "__main__":
    from identity.agent_id import create_agent, revoke_agent

    print("=== 创建 2 个 Agent ===")
    a1 = create_agent("audit-test-A", "测试 Agent A")
    a2 = create_agent("audit-test-B", "测试 Agent B")
    print(f"A: {a1['uuid'][:8]}...")
    print(f"B: {a2['uuid'][:8]}...")

    print("\n=== 记录几条审计日志 ===")
    record(a1["uuid"], "read_file", {"path": "D:/a.txt"},
           action="allow", severity="info", result="ok", user_id="zhangsan")
    record(a1["uuid"], "delete_file", {"path": "D:/doc.docx"},
           action="require_approval", severity="warn", user_id="zhangsan")
    record(a2["uuid"], "run_shell", {"command": "rm -rf /"},
           action="deny", severity="critical", user_id="lisi")
    record(a2["uuid"], "delete_file", {"path": "D:/old.tmp"},
           action="allow", severity="info", result="deleted", user_id="lisi")

    print("\n=== 按 Agent 查询 ===")
    for log in query(agent_uuid=a1["uuid"], limit=5):
        print(f"  {log['ts'][:19]} | {log['agent_name']} | {log['tool_name']} | {log['action']} | {log['user_id']}")

    print("\n=== 查「谁删了文件」 ===")
    for w in who_did(tool_name="delete_file"):
        print(f"  {w['ts'][:19]} | 谁: {w['who']} | 用户: {w['user']} | 动作: {w['action']}")

    print("\n=== 审计统计 ===")
    print(json.dumps(stats(), ensure_ascii=False, indent=2))

    print("\n=== 清理测试 Agent ===")
    revoke_agent(a1["uuid"], "测试完注销")
    revoke_agent(a2["uuid"], "测试完注销")