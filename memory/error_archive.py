"""
A 层：错误档案
AI 每次犯错写一条，下次遇到类似场景先查档案
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import sqlite3
import re
from datetime import datetime, timezone

DB = ROOT / "memory" / "memory.sqlite"


def _conn():
    c = sqlite3.connect(DB)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init():
    """确保 error_archive 表存在"""
    from memory.store import init_db
    init_db()
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS error_archive (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            scenario TEXT NOT NULL,
            mistake TEXT NOT NULL,
            lesson TEXT NOT NULL,
            hit_count INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_err_scenario ON error_archive(scenario)")
    conn.commit()
    conn.close()


def record_error(agent_id: str, scenario: str, mistake: str, lesson: str):
    """记录一次犯错"""
    init()
    conn = _conn()
    conn.execute(
        "INSERT INTO error_archive (ts, agent_id, scenario, mistake, lesson) "
        "VALUES (?, ?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(),
         agent_id, scenario, mistake, lesson)
    )
    conn.commit()
    conn.close()


def _keywords(text: str) -> set:
    """提取中文 2-gram + 英文单词，做简单相似度"""
    tokens = set()
    # 中文 2-gram
    zh = re.findall(r'[\u4e00-\u9fff]', text)
    for i in range(len(zh) - 1):
        tokens.add(zh[i] + zh[i+1])
    # 英文单词
    for w in re.findall(r'[a-zA-Z_]{3,}', text):
        tokens.add(w.lower())
    return tokens


def check_before(scenario: str, top_k: int = 3) -> list:
    """
    执行前查档案。返回相似场景的历史错误，供 AI 参考。
    """
    init()
    conn = _conn()
    cur = conn.execute("SELECT id, scenario, mistake, lesson, hit_count FROM error_archive")
    rows = cur.fetchall()
    conn.close()

    target = _keywords(scenario)
    if not target:
        return []

    scored = []
    for r in rows:
        rid, sc, mk, ls, hc = r
        s = _keywords(sc)
        if not s:
            continue
        # Jaccard 相似度
        inter = len(target & s)
        union = len(target | s)
        sim = inter / union if union else 0
        if sim > 0.15:
            scored.append((sim, rid, sc, mk, ls, hc))

    scored.sort(reverse=True)
    results = []
    for sim, rid, sc, mk, ls, hc in scored[:top_k]:
        results.append({
            "similarity": round(sim, 3),
            "scenario": sc,
            "mistake": mk,
            "lesson": ls,
            "hit_count": hc,
        })
        # 命中计数 +1
        conn = _conn()
        conn.execute("UPDATE error_archive SET hit_count = hit_count + 1 WHERE id = ?", (rid,))
        conn.commit()
        conn.close()

    return results


if __name__ == "__main__":
    init()
    # 测试：写两条错误
    record_error("agent-A", "整理 D 盘下载文件夹",
                 "把用户重要文件一起删了",
                 "删文件前必须先读一遍文件名，含'重要'或'备份'的一律不动")
    record_error("agent-B", "审核日志",
                 "把 error 级别日志当成信息删了",
                 "error 级别必须保留，只能归档不能删")

    # 测试：查一个相似场景
    print("=== 场景1：整理下载文件夹 ===")
    for r in check_before("整理文件"):
        print(r)

    print("\n=== 场景2：清理日志 ===")
    for r in check_before("处理日志"):
        print(r)