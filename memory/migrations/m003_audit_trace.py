"""审计 trace 表"""
def up(conn):
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aid_agent ON audit_identity(agent_uuid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_aid_ts ON audit_identity(ts)")
    conn.commit()