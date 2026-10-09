"""
成本治理（大厂对标版）
- 实时计量：每次调用记账，精度到 token
- 四级预算：正常 / 警告 / 降级 / 熔断
- 超预算自动降级到更便宜的模型
- 成本归因：按 Agent、任务、用户、模型拆分
- 报表导出：CFO 能看懂
"""
import json
import time
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
DB = ROOT / "memory" / "memory.sqlite"

# ========== 预算配置 ==========
DEFAULT_BUDGET = {
    "max_tokens_per_month": 1_000_000,   # 每月最多 100 万 token
    "max_calls_per_month": 10_000,       # 每月最多 1 万次调用
    "max_concurrent": 3,                 # 最多 3 个并发 Agent
}

# ========== 四级阈值 ==========
THRESHOLD_WARNING = 0.70
THRESHOLD_DEGRADE = 0.90
THRESHOLD_BLOCK = 1.00

# ========== 降级映射 ==========
DEGRADE_MAP = {
    "deepseek-r1:7b": "qwen2.5:7b",
    "qwen2.5:7b": "qwen2.5:3b",
    "qwen2.5:3b": None,  # 无法降级
    "default": None,
}

# ========== 电费估算（元/小时） ==========
GPU_POWER_COST = 0.5   # RTX 5060 满载约 0.5 元/小时


def _conn():
    c = sqlite3.connect(DB, timeout=30)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_cost_table():
    conn = _conn()
    try:
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
    finally:
        conn.close()


def record_cost(agent_id: str, model: str, prompt_tokens: int,
                completion_tokens: int, elapsed_ms: int = 0,
                user_id: str = "", task_id: str = "",
                degraded_from: str = ""):
    """记录一次调用"""
    init_cost_table()
    power_cost = (elapsed_ms / 1000.0 / 3600.0) * GPU_POWER_COST
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO cost_log "
            "(ts, agent_id, user_id, task_id, model, prompt_tokens, completion_tokens, "
            "elapsed_ms, power_cost, degraded_from) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (datetime.now(timezone.utc).isoformat(), agent_id,
             user_id or "system", task_id, model,
             prompt_tokens, completion_tokens, elapsed_ms, power_cost,
             degraded_from or None)
        )
        conn.commit()
    finally:
        conn.close()


def usage(agent_id: str = None, user_id: str = None) -> dict:
    """本月用量统计"""
    init_cost_table()
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()

    where = ["ts >= ?"]
    args = [month_start]
    if agent_id:
        where.append("agent_id = ?")
        args.append(agent_id)
    if user_id:
        where.append("user_id = ?")
        args.append(user_id)
    where_sql = " AND ".join(where)

    conn = _conn()
    try:
        cur = conn.execute(
            f"SELECT COUNT(*), "
            f"SUM(prompt_tokens + completion_tokens), "
            f"SUM(power_cost) "
            f"FROM cost_log WHERE {where_sql}",
            args
        )
        calls, tokens, power = cur.fetchone()
        calls = calls or 0
        tokens = tokens or 0
        power = power or 0.0

        tokens_ratio = tokens / DEFAULT_BUDGET["max_tokens_per_month"]
        calls_ratio = calls / DEFAULT_BUDGET["max_calls_per_month"]
        ratio = max(tokens_ratio, calls_ratio)

        return {
            "period": now.strftime("%Y-%m"),
            "calls": calls,
            "tokens": tokens,
            "power_cost": round(power, 4),
            "budget_tokens": DEFAULT_BUDGET["max_tokens_per_month"],
            "budget_calls": DEFAULT_BUDGET["max_calls_per_month"],
            "usage_ratio": round(ratio, 4),
            "level": _level(ratio),
        }
    finally:
        conn.close()


def _level(ratio: float) -> str:
    if ratio >= THRESHOLD_BLOCK:
        return "block"
    if ratio >= THRESHOLD_DEGRADE:
        return "degrade"
    if ratio >= THRESHOLD_WARNING:
        return "warning"
    return "normal"


def check(agent_id: str = None, model: str = None) -> dict:
    """
    检查是否允许调用，并给出建议。
    返回: {"allowed": bool, "level": str, "suggested_model": str, "reason": str, "usage": dict}
    """
    u = usage(agent_id=agent_id)
    level = u["level"]

    if level == "block":
        return {
            "allowed": False,
            "level": "block",
            "suggested_model": None,
            "reason": f"预算已耗尽（{u['usage_ratio']*100:.1f}%），拒绝执行，请审批",
            "usage": u,
        }

    if level == "degrade":
        suggested = DEGRADE_MAP.get(model, DEGRADE_MAP["default"])
        if suggested:
            return {
                "allowed": True,
                "level": "degrade",
                "suggested_model": suggested,
                "reason": f"预算使用 {u['usage_ratio']*100:.1f}%，自动降级到 {suggested}",
                "usage": u,
            }
        else:
            return {
                "allowed": False,
                "level": "block",
                "suggested_model": None,
                "reason": f"预算使用 {u['usage_ratio']*100:.1f}%，已无可降级模型",
                "usage": u,
            }

    return {
        "allowed": True,
        "level": level,
        "suggested_model": model,
        "reason": f"预算正常（{u['usage_ratio']*100:.1f}%）",
        "usage": u,
    }


def report_by_model() -> list:
    """按模型拆分成本"""
    init_cost_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT model, COUNT(*), SUM(prompt_tokens + completion_tokens), SUM(power_cost) "
            "FROM cost_log GROUP BY model ORDER BY COUNT(*) DESC"
        )
        return [
            {"model": r[0], "calls": r[1], "tokens": r[2] or 0, "power_cost": round(r[3] or 0, 4)}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def report_by_agent() -> list:
    """按 Agent 拆分成本"""
    init_cost_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT agent_id, COUNT(*), SUM(prompt_tokens + completion_tokens), SUM(power_cost) "
            "FROM cost_log GROUP BY agent_id ORDER BY COUNT(*) DESC"
        )
        return [
            {"agent_id": r[0], "calls": r[1], "tokens": r[2] or 0, "power_cost": round(r[3] or 0, 4)}
            for r in cur.fetchall()
        ]
    finally:
        conn.close()


def export_csv(path: str = None) -> str:
    """导出 CFO 能看懂的 CSV"""
    import csv
    if not path:
        path = str(ROOT / "evals" / "reports" / "cost_report.csv")
    Path(path).parent.mkdir(parents=True, exist_ok=True)

    init_cost_table()
    conn = _conn()
    try:
        cur = conn.execute(
            "SELECT ts, agent_id, user_id, task_id, model, "
            "prompt_tokens, completion_tokens, elapsed_ms, power_cost, degraded_from "
            "FROM cost_log ORDER BY id DESC LIMIT 10000"
        )
        rows = cur.fetchall()
    finally:
        conn.close()

    fields = ["ts", "agent_id", "user_id", "task_id", "model",
              "prompt_tokens", "completion_tokens", "elapsed_ms",
              "power_cost", "degraded_from"]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(fields)
        w.writerows(rows)
    return path


if __name__ == "__main__":
    print("=== 记录几笔调用 ===")
    record_cost("agent-A", "qwen2.5:7b", 1500, 800, 3200, "user1", "task-1")
    record_cost("agent-A", "qwen2.5:7b", 2000, 1200, 4500, "user1", "task-2")
    record_cost("agent-B", "deepseek-r1:7b", 3000, 1500, 8000, "user2", "task-3")

    print("\n=== 本月用量 ===")
    print(json.dumps(usage(), ensure_ascii=False, indent=2))

    print("\n=== 按模型拆分 ===")
    print(json.dumps(report_by_model(), ensure_ascii=False, indent=2))

    print("\n=== 按 Agent 拆分 ===")
    print(json.dumps(report_by_agent(), ensure_ascii=False, indent=2))

    print("\n=== 预算检查（模拟高用量） ===")
    # 临时改预算来看降级效果
    DEFAULT_BUDGET["max_tokens_per_month"] = 5000
    print(json.dumps(check("agent-A", "qwen2.5:7b"), ensure_ascii=False, indent=2))

    print("\n=== 导出 CSV ===")
    p = export_csv()
    print(f"已导出: {p}")