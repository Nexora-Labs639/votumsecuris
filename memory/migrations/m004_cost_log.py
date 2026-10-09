"""成本表（含 user_id + degraded_from）"""
def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cost_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            user_id TEXT,
            task_id TEXT,
            model TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            elapsed_ms INTEGER DEFAULT 0,
            power_cost REAL DEFAULT 0.0,
            degraded_from TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_agent ON cost_log(agent_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_ts ON cost_log(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cost_model ON cost_log(model)")
    conn.commit()