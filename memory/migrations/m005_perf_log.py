"""性能表"""
def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS perf_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            model TEXT NOT NULL,
            preset TEXT,
            base TEXT,
            elapsed REAL NOT NULL,
            prompt_chars INTEGER,
            output_chars INTEGER,
            ok INTEGER,
            error TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_perf_ts ON perf_log(ts)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_perf_model ON perf_log(model)")
    conn.commit()