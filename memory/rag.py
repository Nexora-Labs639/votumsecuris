"""
RAG 知识库 (通用版 - 终极版)
- 不绑定任何行业
- 用户自己往 knowledge/ 目录放文件
- 全部通过命令行调 ollama, 绕开 HTTP 接口 404
"""
import sys
import os
import re
import json
import math
import sqlite3
import subprocess
import tempfile
import hashlib
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "memory" / "memory.sqlite"
KNOWLEDGE_DIR = ROOT / "knowledge"
OLLAMA_CMD = "ollama"
EMBED_MODEL = "nomic-embed-text:latest"
SUPPORTED_EXTS = {".txt", ".md"}
CHUNK_SIZE = 300
CHUNK_OVERLAP = 50
EMBED_TIMEOUT = 120
MAX_FILE_SIZE = 10 * 1024 * 1024

def _conn():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    return c

def init_rag_table():
    conn = _conn()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS rag_chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                content TEXT NOT NULL,
                embedding TEXT NOT NULL,
                content_hash TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_source ON rag_chunks(source)")
        try:
            conn.execute("ALTER TABLE rag_chunks ADD COLUMN content_hash TEXT")
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()
       
def _clean_output(raw: str) -> str:
    raw = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", raw)
    raw = raw.replace("\x1b", "")
    return raw

def embed(text: str) -> list:
    if not text or not text.strip():
        return []
    in_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                          suffix=".txt", delete=False) as f:
            f.write(text)
            in_path = f.name
        cmd = f'{OLLAMA_CMD} run {EMBED_MODEL} --format json < "{in_path}"'
        result = subprocess.run(
            cmd, capture_output=True, text=True, encoding="utf-8",
            errors="ignore", timeout=EMBED_TIMEOUT, shell=True,
        )
        raw = _clean_output(result.stdout or "")
        m = re.search(r"\[[\s\S]*\]", raw)
        if m:
            try:
                arr = json.loads(m.group(0))
                if isinstance(arr, list) and len(arr) > 10:
                    return [float(x) for x in arr]
            except Exception:
                pass
        nums = re.findall(r"-?\d+\.?\d*(?:[eE][+-]?\d+)?", raw)
        if len(nums) >= 100:
            return [float(x) for x in nums]
        print(f"[embed 失败] 无法提取向量, 输出长度={len(raw)}")
        return []
    except subprocess.TimeoutExpired:
        print(f"[embed 失败] 超时 (>{EMBED_TIMEOUT} 秒)")
        return []
    except Exception as e:
        print(f"[embed 失败] {e}")
        return []
    finally:
        if in_path:
            try:
                os.unlink(in_path)
            except Exception:
                pass
                 
def chunk_text(text: str, chunk_size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list:
    if not text:
        return []
    chunks = []
    i = 0
    step = max(1, chunk_size - overlap)
    while i < len(text):
        piece = text[i:i + chunk_size].strip()
        if piece:
            chunks.append(piece)
        i += step
    return chunks

def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()

def index_file(path: str, source_name: str = None) -> int:
    init_rag_table()
    p = Path(path)
    if not p.exists():
        print(f"[索引失败] 文件不存在: {path}")
        return 0
    if not p.is_file():
        print(f"[索引失败] 不是文件: {path}")
        return 0
    try:
        size = p.stat().st_size
    except Exception:
        return 0
    if size == 0:
        print(f"[跳过] 空文件: {p.name}")
        return 0
    if size > MAX_FILE_SIZE:
        print(f"[跳过] 超过 10MB: {p.name}")
        return 0

    source = source_name or p.name
    try:
        text = p.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        print(f"[读取失败] {p.name}: {e}")
        return 0

    if not text.strip():
        print(f"[跳过] 无内容: {p.name}")
        return 0

    file_hash = _file_hash(p)

    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT content_hash FROM rag_chunks WHERE source=? LIMIT 1",
            (source,)
        )
        row = cur.fetchone()
        if row and row[0] == file_hash:
            print(f"[跳过] 内容未变: {source}")
            return -1
        conn.execute("DELETE FROM rag_chunks WHERE source=?", (source,))
        conn.commit()
    finally:
        conn.close()

    chunks = chunk_text(text)
    print(f"[索引] {source}: {len(chunks)} 块, hash={file_hash[:8]}")

    count = 0
    for i, chunk in enumerate(chunks):
        vec = embed(chunk)
        if not vec:
            print(f"  [{i+1}/{len(chunks)}] 跳过 (embed 失败)")
            continue
        try:
            conn = _conn()
            conn.execute(
                "INSERT INTO rag_chunks (source, chunk_index, content, embedding, content_hash) "
                "VALUES (?, ?, ?, ?, ?)",
                (source, i, chunk, json.dumps(vec), file_hash)
            )
            conn.commit()
            conn.close()
            count += 1
            print(f"  [{i+1}/{len(chunks)}] ok ({len(vec)} 维)")
        except Exception as e:
            print(f"  [{i+1}/{len(chunks)}] 写入失败: {e}")

    print(f"[索引完成] {source}: {count}/{len(chunks)} 块成功")
    return count
    
def scan_knowledge_dir() -> dict:
    init_rag_table()
    try:
        KNOWLEDGE_DIR.mkdir(exist_ok=True)
    except Exception as e:
        return {"indexed": [], "skipped": [], "total_chunks": 0, "error": str(e)}

    indexed = []
    skipped = []
    total_chunks = 0

    try:
        files = sorted(KNOWLEDGE_DIR.iterdir())
    except Exception as e:
        return {"indexed": [], "skipped": [], "total_chunks": 0, "error": str(e)}

    for f in files:
        if not f.is_file():
            continue
        if f.suffix.lower() not in SUPPORTED_EXTS:
            skipped.append(f.name)
            continue
        n = index_file(str(f), f.name)
        if n > 0:
            indexed.append(f.name)
            total_chunks += n
        elif n == 0:
            skipped.append(f.name)

    return {"indexed": indexed, "skipped": skipped, "total_chunks": total_chunks}

def list_knowledge_files() -> list:
    try:
        KNOWLEDGE_DIR.mkdir(exist_ok=True)
    except Exception:
        return []
    result = []
    try:
        for f in sorted(KNOWLEDGE_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTS:
                result.append({"name": f.name, "size": f.stat().st_size})
    except Exception:
        pass
    return result

def remove_from_index(source_name: str) -> int:
    init_rag_table()
    conn = _conn()
    try:
        cur = conn.execute("DELETE FROM rag_chunks WHERE source=?", (source_name,))
        conn.commit()
        return cur.rowcount
    except Exception as e:
        print(f"[删除失败] {e}")
        return 0
    finally:
        conn.close()

def _cosine(a: list, b: list) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    try:
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return dot / (na * nb)
    except Exception:
        return 0.0

def search(query: str, top_k: int = 3) -> list:
    if not query or not query.strip():
        return []
    init_rag_table()
    qvec = embed(query)
    if not qvec:
        return []

    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT id, source, chunk_index, content, embedding FROM rag_chunks"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    scored = []
    for rid, source, idx, content, emb_json in rows:
        try:
            emb = json.loads(emb_json)
            sim = _cosine(qvec, emb)
            scored.append((sim, source, idx, content))
        except Exception:
            continue

    scored.sort(reverse=True)
    return [
        {"similarity": round(s, 4), "source": src, "chunk": idx, "content": c}
        for s, src, idx, c in scored[:top_k]
    ]
    
if __name__ == "__main__":
    print("=== 扫描知识库 ===")
    result = scan_knowledge_dir()
    print(f"已索引: {result['indexed']}")
    print(f"已跳过: {result.get('skipped', [])}")
    print(f"总块数: {result['total_chunks']}")
    if "error" in result:
        print(f"错误: {result['error']}")

    print("\n=== 知识库文件列表 ===")
    files = list_knowledge_files()
    for f in files:
        print(f"  {f['name']}  ({f['size']} 字节)")
    if not files:
        print("  (空)")

    if files:
        print(f"\n=== 检索测试 ===")
        results = search("测试", top_k=2)
        if results:
            for r in results:
                print(f"  相似度 {r['similarity']} | {r['source']} 第{r['chunk']}块")
        else:
            print("  无结果 (可能 embedding 失败)")
    else:
        print("\n[提示] knowledge/ 目录为空, 请放入 .txt 或 .md 文件后重试")
        