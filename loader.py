import yaml
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent

def load_yaml(p):
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_tools():
    return load_yaml(ROOT / "registry" / "tools.yaml")["tools"]

def load_rules():
    return load_yaml(ROOT / "policy" / "rules.yaml")["rules"]

def init_db():
    db = ROOT / "audit" / "log.sqlite"
    with open(ROOT / "audit" / "init.sql", encoding="utf-8") as f:
        sql = f.read()
    conn = sqlite3.connect(db)
    conn.executescript(sql)
    conn.commit()
    return conn

if __name__ == "__main__":
    tools = load_tools()
    rules = load_rules()
    print(f"[OK] 工具 {len(tools)} 个：")
    for t in tools:
        print(f"     - {t['name']:12s} risk={t['risk']:6s} approval={t['requires_approval']} undo={t['undo']}")
    print(f"[OK] 规则 {len(rules)} 条：")
    for r in rules:
        print(f"     - {r['id']:24s} -> {r['action']}")
    conn = init_db()
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row[0] for row in cur.fetchall()]
    print(f"[OK] 数据库表：{tables}")
    conn.close()
    print("\nDay 1 done.")