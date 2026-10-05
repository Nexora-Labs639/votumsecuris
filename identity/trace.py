"""
全链路追溯
- 给每次操作分配一个 trace_id
- 记录从「用户点击」到「执行结果」的完整链路
- 支持按 trace_id 查完整链路
"""
import sys
import json
import uuid
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


def init_trace_table():
    conn = _conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS trace_spans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trace_id TEXT NOT NULL,
                span_id TEXT NOT NULL,
                parent_span TEXT,
                ts TEXT NOT NULL,
                stage TEXT NOT NULL,
                agent_uuid TEXT,
                agent_name TEXT,
                user_id TEXT,
                tool_name TEXT,
                action TEXT,
                severity TEXT,
                detail TEXT,
                elapsed_ms INTEGER
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_id ON trace_spans(trace_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trace_ts ON trace_spans(ts)")
        conn.commit()
    finally:
        conn.close()


def new_trace() -> str:
    """生成一个新的 trace_id"""
    return str(uuid.uuid4())
    
def add_span(trace_id: str, stage: str, agent_uuid: str = "",
             user_id: str = "", tool_name: str = "",
             action: str = "", severity: str = "info",
             detail: dict = None, elapsed_ms: int = 0,
             parent_span: str = "") -> dict:
    """
    添加一个链路节点（span）。
    stage 常见值：
      user_click / policy_check / approval_gate / execute / result / rollback
    """
    from identity.agent_id import get_agent

    init_trace_table()
    span_id = str(uuid.uuid4())
    agent_name = ""
    if agent_uuid:
        info = get_agent(agent_uuid)
        if info.get("ok"):
            agent_name = info.get("name", "")

    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO trace_spans "
            "(trace_id, span_id, parent_span, ts, stage, agent_uuid, agent_name, "
            "user_id, tool_name, action, severity, detail, elapsed_ms) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                trace_id, span_id, parent_span or None,
                datetime.now(timezone.utc).isoformat(),
                stage, agent_uuid or None, agent_name or None,
                user_id or "system", tool_name or None,
                action or None, severity,
                json.dumps(detail or {}, ensure_ascii=False)[:2000],
                elapsed_ms,
            )
        )
        conn.commit()
        return {"ok": True, "trace_id": trace_id, "span_id": span_id, "stage": stage}
    finally:
        conn.close()


def get_trace(trace_id: str) -> list:
    """按 trace_id 拉取整条链路（按时间排序）"""
    init_trace_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT span_id, parent_span, ts, stage, agent_uuid, agent_name, "
            "user_id, tool_name, action, severity, detail, elapsed_ms "
            "FROM trace_spans WHERE trace_id=? ORDER BY id",
            (trace_id,)
        )
        return [
            {
                "span_id": r[0], "parent_span": r[1], "ts": r[2], "stage": r[3],
                "agent_uuid": r[4], "agent_name": r[5], "user_id": r[6],
                "tool_name": r[7], "action": r[8], "severity": r[9],
                "detail": json.loads(r[10]) if r[10] else {},
                "elapsed_ms": r[11],
            }
            for r in cur.fetchall()
        ]
    finally:
        conn.close()
        
def render_trace(trace_id: str) -> str:
    """把链路渲染成可读文本"""
    spans = get_trace(trace_id)
    if not spans:
        return f"未找到 trace_id: {trace_id}"
    lines = [f"Trace ID: {trace_id}", f"共 {len(spans)} 个节点", ""]
    for i, s in enumerate(spans, 1):
        prefix = "  " * (i - 1)
        lines.append(
            f"{prefix}[{i}] {s['ts'][11:19]} | {s['stage']:<15} | "
            f"{s['agent_name'] or '-'} | user={s['user_id']} | "
            f"tool={s['tool_name'] or '-'} | action={s['action'] or '-'} | "
            f"{s['elapsed_ms']}ms"
        )
        if s["detail"]:
            lines.append(f"{prefix}     detail: {json.dumps(s['detail'], ensure_ascii=False)[:200]}")
    return "\n".join(lines)


def list_recent_traces(limit: int = 20) -> list:
    """列出最近的 trace_id"""
    init_trace_table()
    conn = _conn()
    try:
        cur = conn.execute("""
            SELECT trace_id, MIN(ts), MAX(ts), COUNT(*)
            FROM trace_spans GROUP BY trace_id
            ORDER BY MAX(ts) DESC LIMIT ?
        """, (limit,))
        return [
            {"trace_id": r[0], "start": r[1], "end": r[2], "span_count": r[3]}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


if __name__ == "__main__":
    from identity.agent_id import create_agent
    from identity.audit import record

    print("=== 创建测试 Agent ===")
    a = create_agent("trace-test", "测试全链路追溯")
    agent_uuid = a["uuid"]

    print("\n=== 模拟一次完整操作链路 ===")
    trace_id = new_trace()
    print(f"trace_id: {trace_id}")

    add_span(trace_id, "user_click",
             agent_uuid=agent_uuid, user_id="zhangsan",
             detail={"button": "删除文件", "path": "D:/important.docx"})

    add_span(trace_id, "policy_check",
             agent_uuid=agent_uuid, user_id="zhangsan", tool_name="delete_file",
             action="require_approval", severity="critical",
             detail={"reason": "重要文件"})

    add_span(trace_id, "approval_gate",
             agent_uuid=agent_uuid, user_id="zhangsan",
             action="approved", detail={"approver": "zhangsan"})

    add_span(trace_id, "execute",
             agent_uuid=agent_uuid, user_id="zhangsan", tool_name="delete_file",
             action="deleted", elapsed_ms=42,
             detail={"trash_path": "D:/.votumsecuris_trash/..."})

    add_span(trace_id, "result",
             agent_uuid=agent_uuid, user_id="zhangsan",
             action="success", detail={"message": "已删除，可从回收站恢复"})

    record(agent_uuid, "delete_file", {"path": "D:/important.docx"},
           action="deleted", severity="critical",
           result="ok", user_id="zhangsan")

    print("\n=== 渲染链路 ===")
    print(render_trace(trace_id))

    print("\n=== 最近的 trace ===")
    for t in list_recent_traces(limit=3):
        print(f"  {t['trace_id']} | {t['span_count']} 节点 | {t['start'][11:19]} → {t['end'][11:19]}")