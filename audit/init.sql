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
);
CREATE INDEX IF NOT EXISTS idx_ts ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_agent ON audit_log(agent_id);
CREATE INDEX IF NOT EXISTS idx_status ON audit_log(status);

CREATE TABLE IF NOT EXISTS error_archive (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    agent_id TEXT NOT NULL,
    scenario TEXT NOT NULL,
    mistake TEXT NOT NULL,
    lesson TEXT NOT NULL,
    hit_count INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_err_scenario ON error_archive(scenario);