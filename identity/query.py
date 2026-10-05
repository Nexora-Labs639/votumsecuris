"""
高级审计查询
- 时间范围过滤
- 多条件组合
- 聚合统计
- 导出 JSON / CSV
"""
import sys
import json
import sqlite3
import csv
from pathlib import Path
from datetime import datetime, timezone, timedelta

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "memory" / "memory.sqlite"


def _conn():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _build_where(agent_uuid=None, user_id=None, tool_name=None,
                 action=None, severity=None, since=None, until=None):
    """构造 WHERE 子句"""
    conds = []
    args = []
    if agent_uuid:
        conds.append("agent_uuid=?")
        args.append(agent_uuid)
    if user_id:
        conds.append("user_id=?")
        args.append(user_id)
    if tool_name:
        conds.append("tool_name=?")
        args.append(tool_name)
    if action:
        conds.append("action=?")
        args.append(action)
    if severity:
        conds.append("severity=?")
        args.append(severity)
    if since:
        conds.append("ts>=?")
        args.append(since)
    if until:
        conds.append("ts<=?")
        args.append(until)
    where = " AND ".join(conds) if conds else "1=1"
    return where, args
    
def search(agent_uuid=None, user_id=None, tool_name=None,
           action=None, severity=None, since=None, until=None,
           limit=200) -> list:
    """多条件组合查询"""
    from identity.audit import init_audit_table
    init_audit_table()

    where, args = _build_where(agent_uuid, user_id, tool_name, action, severity, since, until)
    sql = (f"SELECT ts, agent_uuid, agent_name, user_id, tool_name, "
           f"action, severity, params, result, error "
           f"FROM audit_identity WHERE {where} ORDER BY id DESC LIMIT ?")
    args.append(limit)

    conn = _conn()
    try:
        cur = conn.execute(sql, args)
        return [
            {
                "ts": r[0], "agent_uuid": r[1], "agent_name": r[2],
                "user_id": r[3], "tool_name": r[4], "action": r[5],
                "severity": r[6],
                "params": json.loads(r[7]) if r[7] else {},
                "result": r[8], "error": r[9],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def recent_hours(hours: int = 24, **kwargs) -> list:
    """查最近 N 小时"""
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    kwargs["since"] = since
    return search(**kwargs)


def count_by(agent_uuid=None, user_id=None, hours: int = 24) -> dict:
    """按工具 / 严重度 / 用户统计"""
    from identity.audit import init_audit_table
    init_audit_table()

    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    where, args = _build_where(agent_uuid=agent_uuid, user_id=user_id, since=since)

    conn = _conn()
    try:
        cur = conn.execute(
            f"SELECT tool_name, COUNT(*) FROM audit_identity WHERE {where} GROUP BY tool_name",
            args
        )
        by_tool = {r[0] or "(none)": r[1] for r in cur.fetchall()}

        cur = conn.execute(
            f"SELECT severity, COUNT(*) FROM audit_identity WHERE {where} GROUP BY severity",
            args
        )
        by_severity = {r[0] or "(none)": r[1] for r in cur.fetchall()}

        cur = conn.execute(
            f"SELECT user_id, COUNT(*) FROM audit_identity WHERE {where} GROUP BY user_id",
            args
        )
        by_user = {r[0]: r[1] for r in cur.fetchall()}

        cur = conn.execute(
            f"SELECT COUNT(*) FROM audit_identity WHERE {where}", args
        )
        total = cur.fetchone()[0]

        return {
            "total": total,
            "hours": hours,
            "by_tool": by_tool,
            "by_severity": by_severity,
            "by_user": by_user,
        }
    finally:
        conn.close()
        
def export_json(path: str, **kwargs) -> int:
    """导出为 JSON 文件"""
    rows = search(**kwargs)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)
    return len(rows)


def export_csv(path: str, **kwargs) -> int:
    """导出为 CSV 文件"""
    rows = search(**kwargs)
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return 0
    fields = ["ts", "agent_uuid", "agent_name", "user_id",
              "tool_name", "action", "severity", "result", "error"]
    with open(p, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return len(rows)


def suspicious_activity(hours: int = 24) -> list:
    """找出可疑活动：critical / denied / error"""
    logs = recent_hours(hours)
    suspicious = [
        log for log in logs
        if log["severity"] == "critical"
        or log["action"] in ("deny", "denied", "error")
    ]
    return suspicious


if __name__ == "__main__":
    from identity.agent_id import create_agent
    from identity.audit import record

    print("=== 创建测试数据 ===")
    a1 = create_agent("query-test-A", "测试查询 A")
    a2 = create_agent("query-test-B", "测试查询 B")

    for i in range(3):
        record(a1["uuid"], "read_file", {"path": f"D:/a{i}.txt"},
               action="allow", severity="info", user_id="zhangsan")
    record(a1["uuid"], "delete_file", {"path": "D:/important.docx"},
           action="require_approval", severity="critical", user_id="zhangsan")
    record(a2["uuid"], "run_shell", {"command": "rm -rf /"},
           action="deny", severity="critical", user_id="lisi")
    record(a2["uuid"], "write_file", {"path": "D:/log.txt"},
           action="allow", severity="info", user_id="lisi")

    print("\n=== 查最近 1 小时所有日志 ===")
    logs = recent_hours(1)
    for log in logs[:5]:
        print(f"  {log['ts'][11:19]} | {log['agent_name']} | {log['tool_name']} | {log['action']} | user={log['user_id']}")

    print("\n=== 按用户查询 ===")
    for log in search(user_id="zhangsan", limit=5):
        print(f"  {log['ts'][11:19]} | {log['agent_name']} | {log['tool_name']} | {log['action']}")

    print("\n=== 按严重度查询 ===")
    for log in search(severity="critical", limit=5):
        print(f"  {log['ts'][11:19]} | {log['agent_name']} | {log['tool_name']} | {log['action']}")

    print("\n=== 统计 ===")
    print(json.dumps(count_by(hours=1), ensure_ascii=False, indent=2))

    print("\n=== 可疑活动 ===")
    for s in suspicious_activity(1):
        print(f"  {s['ts'][11:19]} | {s['agent_name']} | {s['tool_name']} | {s['action']} | {s['severity']}")

    print("\n=== 导出 ===")
    n = export_json("evals/reports/audit_export.json")
    print(f"导出 JSON: {n} 条")
    n = export_csv("evals/reports/audit_export.csv")
    print(f"导出 CSV: {n} 条")