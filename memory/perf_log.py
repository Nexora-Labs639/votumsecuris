"""
推理性能日志（与新版 llm_control 对齐）
- 记录每次推理的耗时、模型、preset、base
- 支持统计查询
"""
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DB = ROOT / "memory" / "memory.sqlite"


def _conn():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_perf_table():
    conn = _conn()
    try:
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
        try:
            conn.execute("ALTER TABLE perf_log ADD COLUMN base TEXT")
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()


def log_perf(result: dict, prompt: str):
    init_perf_table()
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO perf_log "
            "(ts, model, preset, base, elapsed, prompt_chars, output_chars, ok, error) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                result.get("model", "unknown"),
                result.get("preset", ""),
                result.get("base", ""),
                float(result.get("elapsed", 0.0)),
                len(prompt),
                len(result.get("text", "")),
                1 if result.get("ok") else 0,
                result.get("error", "")[:500],
            )
        )
        conn.commit()
    finally:
        conn.close()


def stats() -> dict:
    init_perf_table()
    conn = _conn()
    try:
        cur = conn.execute("""
            SELECT COUNT(*), AVG(elapsed), MIN(elapsed), MAX(elapsed),
                   SUM(CASE WHEN ok=1 THEN 1 ELSE 0 END)
            FROM perf_log
        """)
        total, avg_e, min_e, max_e, ok_count = cur.fetchone()

        cur = conn.execute("""
            SELECT model, COUNT(*), AVG(elapsed)
            FROM perf_log GROUP BY model ORDER BY COUNT(*) DESC
        """)
        by_model = [
            {"model": m, "count": c, "avg_elapsed": round(a, 3) if a else 0}
            for m, c, a in cur.fetchall()
        ]

        cur = conn.execute("""
            SELECT preset, COUNT(*), AVG(elapsed)
            FROM perf_log GROUP BY preset ORDER BY COUNT(*) DESC
        """)
        by_preset = [
            {"preset": p or "(none)", "count": c, "avg_elapsed": round(a, 3) if a else 0}
            for p, c, a in cur.fetchall()
        ]

        return {
            "total": total or 0,
            "avg_elapsed": round(avg_e, 3) if avg_e else 0,
            "min_elapsed": round(min_e, 3) if min_e else 0,
            "max_elapsed": round(max_e, 3) if max_e else 0,
            "ok_count": ok_count or 0,
            "by_model": by_model,
            "by_preset": by_preset,
        }
    finally:
        conn.close()


def tail(n: int = 10) -> list:
    init_perf_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT ts, model, preset, base, elapsed, ok FROM perf_log "
            "ORDER BY id DESC LIMIT ?",
            (n,)
        )
        return [
            {"ts": t, "model": m, "preset": p, "base": b, "elapsed": e, "ok": bool(o)}
            for t, m, p, b, e, o in cur.fetchall()
        ]
    finally:
        conn.close()


def clear_all():
    """清空性能日志（维护用）"""
    init_perf_table()
    conn = _conn()
    try:
        conn.execute("DELETE FROM perf_log")
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    from executor.llm_control import run_llm

    print("=== 跑 4 次推理并记录性能 ===")
    for preset in ["fast", "balanced", "deep", "creative"]:
        r = run_llm("用一句话描述你的用途", preset=preset)
        log_perf(r, "用一句话描述你的用途")
        status = "ok" if r["ok"] else f"失败({r.get('error','')[:30]})"
        print(f"  {preset}: {r['elapsed']}秒, {status}")

    print("\n=== 性能统计 ===")
    print(json.dumps(stats(), ensure_ascii=False, indent=2))

    print("\n=== 最近 5 条 ===")
    for row in tail(5):
        print(f"  {row['ts'][:19]} | {row['model']} | {row['preset']} | {row['elapsed']}秒 | ok={row['ok']}")