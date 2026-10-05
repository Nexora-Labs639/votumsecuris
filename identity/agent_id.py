"""
Agent 身份系统
- 每个 Agent 一个 UUID
- 每个 Agent 一对密钥（用于签名验证）
- 支持创建、查询、注销
"""
import sys
import os
import json
import uuid
import hashlib
import hmac
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "memory" / "memory.sqlite"
SECRET_FILE = ROOT / "identity" / ".master_key"


def _conn():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_identity_table():
    conn = _conn()
    try:
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
        conn.commit()
    finally:
        conn.close()


def _get_master_key() -> bytes:
    """获取或生成本机主密钥"""
    SECRET_FILE.parent.mkdir(exist_ok=True)
    if SECRET_FILE.exists():
        return SECRET_FILE.read_bytes()
    key = os.urandom(32)
    SECRET_FILE.write_bytes(key)
    try:
        os.chmod(SECRET_FILE, 0o600)
    except Exception:
        pass
    return key
    
def _derive_keypair(agent_uuid: str) -> tuple:
    """从 UUID 派生密钥对（确定性）"""
    master = _get_master_key()
    secret = hmac.new(master, agent_uuid.encode("utf-8"), hashlib.sha256).digest()
    pubkey = hashlib.sha256(secret).hexdigest()
    return secret.hex(), pubkey


def create_agent(name: str, note: str = "") -> dict:
    """创建一个新 Agent"""
    if not name or not name.strip():
        return {"ok": False, "error": "name 不能为空"}

    init_identity_table()
    agent_uuid = str(uuid.uuid4())
    secret, pubkey = _derive_keypair(agent_uuid)
    ts = datetime.now(timezone.utc).isoformat()

    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO agents (uuid, name, pubkey, created_at, note) "
            "VALUES (?, ?, ?, ?, ?)",
            (agent_uuid, name.strip(), pubkey, ts, note)
        )
        conn.commit()
        return {
            "ok": True,
            "uuid": agent_uuid,
            "name": name,
            "pubkey": pubkey,
            "created_at": ts,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def get_agent(agent_uuid: str) -> dict:
    """按 UUID 查询 Agent"""
    init_identity_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT uuid, name, pubkey, created_at, revoked, revoked_at, note "
            "FROM agents WHERE uuid = ?", (agent_uuid,)
        )
        row = cur.fetchone()
        if not row:
            return {"ok": False, "error": "Agent 不存在"}
        return {
            "ok": True,
            "uuid": row[0],
            "name": row[1],
            "pubkey": row[2],
            "created_at": row[3],
            "revoked": bool(row[4]),
            "revoked_at": row[5],
            "note": row[6],
        }
    finally:
        conn.close()


def list_agents(include_revoked: bool = False) -> list:
    """列出所有 Agent"""
    init_identity_table()
    conn = _conn()
    try:
        if include_revoked:
            cur = conn.execute("SELECT uuid, name, pubkey, created_at, revoked FROM agents ORDER BY created_at")
        else:
            cur = conn.execute("SELECT uuid, name, pubkey, created_at, revoked FROM agents WHERE revoked=0 ORDER BY created_at")
        return [
            {"uuid": r[0], "name": r[1], "pubkey": r[2], "created_at": r[3], "revoked": bool(r[4])}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def revoke_agent(agent_uuid: str, reason: str = "") -> dict:
    """注销 Agent"""
    init_identity_table()
    conn = _conn()
    try:
        ts = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            "UPDATE agents SET revoked=1, revoked_at=?, note=? WHERE uuid=? AND revoked=0",
            (ts, reason, agent_uuid)
        )
        conn.commit()
        if cur.rowcount == 0:
            return {"ok": False, "error": "Agent 不存在或已注销"}
        return {"ok": True, "uuid": agent_uuid, "revoked_at": ts}
    finally:
        conn.close()
        
def verify_signature(agent_uuid: str, payload: str, signature: str) -> bool:
    """验证签名"""
    secret, _ = _derive_keypair(agent_uuid)
    expected = hmac.new(
        bytes.fromhex(secret),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def sign(agent_uuid: str, payload: str) -> str:
    """用 Agent 密钥签名"""
    secret, _ = _derive_keypair(agent_uuid)
    return hmac.new(
        bytes.fromhex(secret),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def is_agent_valid(agent_uuid: str) -> bool:
    """检查 Agent 是否有效（存在且未注销）"""
    r = get_agent(agent_uuid)
    return r.get("ok", False) and not r.get("revoked", True)


if __name__ == "__main__":
    print("=== 创建 3 个 Agent ===")
    a1 = create_agent("agent-A", "负责文件整理")
    a2 = create_agent("agent-B", "负责日志审核")
    a3 = create_agent("agent-C", "负责数据抓取")
    print(json.dumps([a1, a2, a3], ensure_ascii=False, indent=2))

    print("\n=== 列出所有 Agent ===")
    for a in list_agents():
        print(f"  {a['name']} | {a['uuid'][:8]}... | pubkey={a['pubkey'][:16]}...")

    print("\n=== 签名与验证 ===")
    payload = "delete_file:D:/tmp/a.tmp"
    sig = sign(a1["uuid"], payload)
    print(f"签名: {sig[:32]}...")
    print(f"验证: {verify_signature(a1['uuid'], payload, sig)}")

    print("\n=== 注销 agent-C ===")
    r = revoke_agent(a3["uuid"], "任务完成，不再使用")
    print(json.dumps(r, ensure_ascii=False, indent=2))

    print("\n=== 注销后再列出 ===")
    for a in list_agents():
        print(f"  {a['name']} | revoked={a['revoked']}")