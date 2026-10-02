"""
RAG 知识库（通用版）
- 不绑定任何行业
- 用户自己往 knowledge/ 目录放文件
- 自动扫描、索引、检索
"""
import sys
import json
import math
import urllib.request
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "memory" / "memory.sqlite"
KNOWLEDGE_DIR = ROOT / "knowledge"
OLLAMA_URL = "http://127.0.0.1:11434/api/embeddings"
EMBED_MODEL = "nomic-embed-text:latest"
SUPPORTED_EXTS = {".txt", ".md"}


def _conn():
    c = sqlite3.connect(DB)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_rag_table():
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rag_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            content TEXT NOT NULL,
            embedding TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_source ON rag_chunks(source)")
    conn.commit()
    conn.close()


def embed(text: str) -> list:
    payload = {"model": EMBED_MODEL, "prompt": text}
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        OLLAMA_URL, data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8")).get("embedding", [])
    except Exception as e:
        print(f"[embed 失败] {e}")
        return []


def chunk_text(text: str, chunk_size: int = 300, overlap: int = 50) -> list:
    chunks = []
    i = 0
    while i < len(text):
        chunks.append(text[i:i+chunk_size])
        i += chunk_size - overlap
    return [c.strip() for c in chunks if c.strip()]


def index_file(path: str, source_name: str = None) -> int:
    """索引一个文件到 RAG 库"""
    init_rag_table()
    p = Path(path)
    if not p.exists():
        print(f"[索引失败] 文件不存在: {path}")
        return 0

    text = p.read_text(encoding="utf-8", errors="ignore")
    chunks = chunk_text(text)
    source = source_name or p.name

    conn = _conn()
    conn.execute("DELETE FROM rag_chunks WHERE source = ?", (source,))
    conn.commit()
    conn.close()

    count = 0
    for i, chunk in enumerate(chunks):
        vec = embed(chunk)
        if not vec:
            continue
        conn = _conn()
        conn.execute(
            "INSERT INTO rag_chunks (source, chunk_index, content, embedding) VALUES (?, ?, ?, ?)",
            (source, i, chunk, json.dumps(vec))
        )
        conn.commit()
        conn.close()
        count += 1

    print(f"[索引完成] {source}: {count} 块")
    return count


def scan_knowledge_dir() -> dict:
    """扫描 knowledge/ 目录，索引所有支持的文件的"""
    init_rag_table()
    KNOWLEDGE_DIR.mkdir(exist_ok=True)

    indexed = []
    skipped = []
    total_chunks = 0

    for f in sorted(KNOWLEDGE_DIR.iterdir()):
        if not f.is_file():
            continue
        if f.suffix.lower() not in SUPPORTED_EXTS:
            skipped.append(f.name)
            continue
        n = index_file(str(f), f.name)
        if n > 0:
            indexed.append(f.name)
            total_chunks += n

    return {"indexed": indexed, "skipped": skipped, "total_chunks": total_chunks}


def list_knowledge_files() -> list:
    KNOWLEDGE_DIR.mkdir(exist_ok=True)
    return [
        {"name": f.name, "size": f.stat().st_size}
        for f in sorted(KNOWLEDGE_DIR.iterdir())
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS
    ]


def remove_from_index(source_name: str) -> int:
    init_rag_table()
    conn = _conn()
    cur = conn.execute("DELETE FROM rag_chunks WHERE source = ?", (source_name,))
    conn.commit()
    n = cur.rowcount
    conn.close()
    return n


def _cosine(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x*y for x, y in zip(a, b))
    na = math.sqrt(sum(x*x for x in a))
    nb = math.sqrt(sum(x*x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def search(query: str, top_k: int = 3) -> list:
    init_rag_table()
    qvec = embed(query)
    if not qvec:
        return []

    conn = _conn()
    cur = conn.execute("SELECT id, source, chunk_index, content, embedding FROM rag_chunks")
    rows = cur.fetchall()
    conn.close()

    scored = []
    for rid, source, idx, content, emb_json in rows:
        emb = json.loads(emb_json)
        sim = _cosine(qvec, emb)
        scored.append((sim, source, idx, content))

    scored.sort(reverse=True)
    return [
        {"similarity": round(s, 4), "source": src, "chunk": idx, "content": c}
        for s, src, idx, c in scored[:top_k]
    ]


if __name__ == "__main__":
    print("=== 扫描知识库 ===")
    result = scan_knowledge_dir()
    print(f"已索引: {result['indexed']}")
    print(f"总块数: {result['total_chunks']}")

    print("\n=== 知识库文件列表 ===")
    for f in list_knowledge_files():
        print(f"  {f['name']}  ({f['size']} 字节)")

    files = list_knowledge_files()
    if files:
        print(f"\n=== 检索测试 ===")
        for r in search("测试查询", top_k=2):
            print(f"  相似度 {r['similarity']} | {r['source']}")
    else:
        print("\n[提示] knowledge/ 目录为空，请放入 .txt 或 .md 文件后重试")