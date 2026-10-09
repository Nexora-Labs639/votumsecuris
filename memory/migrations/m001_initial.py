"""初始表结构"""
def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            tool_name TEXT NOT NULL,
            params TEXT,
            result TEXT,
            status TEXT NOT NULL,
            undo_of INTEGER,
            FOREIGN KEY (undo_of) REFERENCES audit_log(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON audit_log(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent ON audit_log(agent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status ON audit_log(status)")
    conn.commit()