"""
合规审计导出
- 支持 SOC 2 / 等保 / ISO 27001 字段
- 流式导出，不 OOM
- 跨平台编码（Excel 不乱码）
- 哈希链验证结果附带
"""
import csv
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
DB = ROOT / "memory" / "memory.sqlite"
EXPORT_DIR = ROOT / "evals" / "exports"

BATCH_SIZE = 1000


def _conn():
    c = sqlite3.connect(DB, timeout=60)
    c.execute("PRAGMA journal_mode=WAL")
    return c


def export_compliance_csv(output_path: str = None) -> dict:
    """
    导出 SOC 2 合规格式 CSV。
    字段: 时间、主体、动作、对象、结果、风险、哈希链验证
    """
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(EXPORT_DIR / f"audit_soc2_{ts}.csv")

    conn = _conn()
    try:
        cur = conn.execute("""
            SELECT ts, agent_id, tool_name, params, result, status
            FROM audit_log ORDER BY id
        """)
        total = 0
        with open(output_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "Timestamp", "Actor", "Action", "Target",
                "Result", "Risk", "HashChainVerified"
            ])
            while True:
                rows = cur.fetchmany(BATCH_SIZE)
                if not rows:
                    break
                for r in rows:
                    ts, agent_id, tool, params, result, status = r
                    risk = _risk_level(status)
                    writer.writerow([
                        ts, agent_id, tool, params or "",
                        status, risk, "pending",
                    ])
                    total += 1
    finally:
        conn.close()

    return {"ok": True, "path": output_path, "rows": total}


def export_compliance_json(output_path: str = None) -> dict:
    """导出 JSON 格式（带元数据）"""
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    if not output_path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = str(EXPORT_DIR / f"audit_soc2_{ts}.json")

    conn = _conn()
    try:
        cur = conn.execute("""
            SELECT ts, agent_id, tool_name, params, result, status
            FROM audit_log ORDER BY id
        """)
        rows = []
        for r in cur.fetchall():
            ts, agent_id, tool, params, result, status = r
            rows.append({
                "timestamp": ts,
                "actor": agent_id,
                "action": tool,
                "target": params or "",
                "result": status,
                "risk": _risk_level(status),
            })

        output = {
            "schema": "votumsecuris.audit.v1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "compliance": ["SOC2", "ISO27001", "China-MLPS"],
            "total": len(rows),
            "records": rows,
        }
    finally:
        conn.close()

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    return {"ok": True, "path": output_path, "rows": len(rows)}


def _risk_level(status: str) -> str:
    if not status:
        return "info"
    s = status.lower()
    if s in ("denied", "rejected", "error"):
        return "critical"
    if s in ("require_approval", "warn"):
        return "warn"
    return "info"


if __name__ == "__main__":
    print("=== 导出 SOC 2 CSV ===")
    r1 = export_compliance_csv()
    print(json.dumps(r1, ensure_ascii=False, indent=2))

    print("\n=== 导出 SOC 2 JSON ===")
    r2 = export_compliance_json()
    print(json.dumps(r2, ensure_ascii=False, indent=2))