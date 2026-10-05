"""
Agent 权限系统
- 按 Agent ID 分配工具权限
- 支持 allow / deny / require_approval 三级
- 默认拒绝（白名单制）
"""
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "memory" / "memory.sqlite"

# 默认权限（所有 Agent 共用）
DEFAULT_PERMISSION = {
    "read_file": "allow",
    "write_file": "require_approval",
    "delete_file": "require_approval",
    "run_shell": "require_approval",
    "network": "deny",
}


def _conn():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_permission_table():
    conn = _conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agent_permissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_uuid TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                action TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                note TEXT,
                UNIQUE(agent_uuid, tool_name)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_agent ON agent_permissions(agent_uuid)")
        conn.commit()
    finally:
        conn.close()
        
def grant(agent_uuid: str, tool_name: str, action: str, note: str = "") -> dict:
    """
    给某个 Agent 分配某个工具的权限。
    action: allow / deny / require_approval
    """
    if action not in ("allow", "deny", "require_approval"):
        return {"ok": False, "error": f"无效 action: {action}"}

    init_permission_table()
    conn = _conn()
    try:
        ts = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO agent_permissions (agent_uuid, tool_name, action, updated_at, note) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(agent_uuid, tool_name) DO UPDATE SET "
            "action=excluded.action, updated_at=excluded.updated_at, note=excluded.note",
            (agent_uuid, tool_name, action, ts, note)
        )
        conn.commit()
        return {"ok": True, "agent_uuid": agent_uuid, "tool_name": tool_name,
                "action": action, "updated_at": ts}
    finally:
        conn.close()


def revoke_permission(agent_uuid: str, tool_name: str) -> dict:
    """删除某条权限，回落到默认值"""
    init_permission_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "DELETE FROM agent_permissions WHERE agent_uuid=? AND tool_name=?",
            (agent_uuid, tool_name)
        )
        conn.commit()
        return {"ok": True, "deleted": cur.rowcount}
    finally:
        conn.close()


def get_permission(agent_uuid: str, tool_name: str) -> dict:
    """
    查询某个 Agent 对某个工具的权限。
    优先级：Agent 专属 > 默认
    """
    init_permission_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT action, note FROM agent_permissions WHERE agent_uuid=? AND tool_name=?",
            (agent_uuid, tool_name)
        )
        row = cur.fetchone()
        if row:
            return {
                "agent_uuid": agent_uuid,
                "tool_name": tool_name,
                "action": row[0],
                "source": "agent_specific",
                "note": row[1] or "",
            }
        action = DEFAULT_PERMISSION.get(tool_name, "deny")
        return {
            "agent_uuid": agent_uuid,
            "tool_name": tool_name,
            "action": action,
            "source": "default",
            "note": "使用默认权限",
        }
    finally:
        conn.close()


def list_permissions(agent_uuid: str = None) -> list:
    """列出权限（可按 Agent 过滤）"""
    init_permission_table()
    conn = _conn()
    try:
        if agent_uuid:
            cur = conn.execute(
                "SELECT agent_uuid, tool_name, action, updated_at, note "
                "FROM agent_permissions WHERE agent_uuid=? ORDER BY tool_name",
                (agent_uuid,)
            )
        else:
            cur = conn.execute(
                "SELECT agent_uuid, tool_name, action, updated_at, note "
                "FROM agent_permissions ORDER BY agent_uuid, tool_name"
            )
        return [
            {"agent_uuid": r[0], "tool_name": r[1], "action": r[2],
             "updated_at": r[3], "note": r[4]}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def check(agent_uuid: str, tool_name: str) -> dict:
    """
    检查某个 Agent 能不能用某个工具。
    返回：{"allowed": bool, "action": str, "reason": str}
    """
    from identity.agent_id import is_agent_valid

    if not is_agent_valid(agent_uuid):
        return {"allowed": False, "action": "deny", "reason": "Agent 无效或已注销"}

    p = get_permission(agent_uuid, tool_name)
    action = p["action"]
    return {
        "allowed": action != "deny",
        "action": action,
        "reason": f"权限来源: {p['source']}",
    }
    
def init_default_permissions_for_all():
    """给所有 Agent 初始化为默认权限（空表即默认）"""
    init_permission_table()
    return {"ok": True, "note": "默认权限已内置，无需显式初始化"}


if __name__ == "__main__":
    from identity.agent_id import create_agent, list_agents

    print("=== 创建一个测试 Agent ===")
    r = create_agent("permission-test", "测试权限系统")
    agent_uuid = r["uuid"]
    print(f"UUID: {agent_uuid}")

    print("\n=== 默认权限（未显式分配时） ===")
    for tool in ["read_file", "write_file", "delete_file", "run_shell", "network"]:
        p = get_permission(agent_uuid, tool)
        print(f"  {tool}: {p['action']} (来源: {p['source']})")

    print("\n=== 给这个 Agent 分配专属权限 ===")
    grant(agent_uuid, "delete_file", "deny", "该 Agent 不允许删文件")
    grant(agent_uuid, "run_shell", "deny", "该 Agent 不允许执行命令")
    grant(agent_uuid, "read_file", "allow", "只读权限")
    for a in list_permissions(agent_uuid):
        print(f"  {a['tool_name']}: {a['action']}")

    print("\n=== 再查一次权限 ===")
    for tool in ["read_file", "write_file", "delete_file", "run_shell", "network"]:
        p = get_permission(agent_uuid, tool)
        print(f"  {tool}: {p['action']} (来源: {p['source']})")

    print("\n=== check() 综合判断 ===")
    for tool in ["read_file", "delete_file", "run_shell"]:
        c = check(agent_uuid, tool)
        print(f"  {tool}: allowed={c['allowed']} action={c['action']} | {c['reason']}")

    print("\n=== 注销 Agent 后再 check ===")
    from identity.agent_id import revoke_agent
    revoke_agent(agent_uuid, "测试完注销")
    c = check(agent_uuid, "read_file")
    print(f"  read_file: allowed={c['allowed']} | {c['reason']}")