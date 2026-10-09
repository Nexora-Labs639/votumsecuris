"""Agent 身份 + 权限表"""
def up(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            uuid TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            pubkey TEXT NOT NULL,
            created_at TEXT NOT NULL,
            revoked INTEGER DEFAULT 0,
            revoked_at TEXT,
            note TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_name ON agents(name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_agent_revoked ON agents(revoked)")

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