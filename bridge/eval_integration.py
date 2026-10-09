"""
自动评测集成（你的独一份）
- OpenClaw 干活前，自动跑快速评测
- 分数下降超阈值，拦截任务，推送手机审批
- 参考：你已有的 evals/ 系统
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
REPORTS_DIR = ROOT / "evals" / "reports"

# 劣化阈值：分数下降超过 10% 触发审批
DEGRADE_THRESHOLD = 10.0


def get_latest_report() -> dict:
    """取最近两份报告"""
    if not REPORTS_DIR.exists():
        return {}
    files = sorted(REPORTS_DIR.glob("eval_*.json"), reverse=True)
    if len(files) < 2:
        return {}
    try:
        with open(files[0], encoding="utf-8") as f:
            new = json.load(f)
        with open(files[1], encoding="utf-8") as f:
            old = json.load(f)
        return {"new": new, "old": old}
    except Exception:
        return {}


def check_degradation() -> dict:
    """
    检查质量是否劣化。
    返回: {"degraded": bool, "old_score": float, "new_score": float, "delta": float}
    """
    r = get_latest_report()
    if not r:
        return {"degraded": False, "old_score": 0, "new_score": 0, "delta": 0}

    old_score = r["old"].get("score", 0)
    new_score = r["new"].get("score", 0)
    delta = round(new_score - old_score, 2)

    return {
        "degraded": delta < -DEGRADE_THRESHOLD,
        "old_score": old_score,
        "new_score": new_score,
        "delta": delta,
    }


def run_quick_eval() -> dict:
    """跑快速评测（只跑安全 + 诚实，30 秒内）"""
    try:
        result = subprocess.run(
            ["python", "-m", "evals.runner", "--quick"],
            cwd=str(ROOT),
            capture_output=True, text=True, timeout=120,
        )
        return {"ok": result.returncode == 0, "output": result.stdout[-500:]}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def should_block_task() -> dict:
    """
    判断是否应该拦截任务。
    返回: {"block": bool, "reason": str}
    """
    d = check_degradation()
    if d["degraded"]:
        return {
            "block": True,
            "reason": f"质量劣化: {d['old_score']}→{d['new_score']} (下降 {abs(d['delta'])}%)",
            "info": d,
        }
    return {"block": False, "reason": "", "info": d}


if __name__ == "__main__":
    print("=== 质量劣化检查 ===")
    print(json.dumps(check_degradation(), ensure_ascii=False, indent=2))

    print("\n=== 是否拦截任务 ===")
    print(json.dumps(should_block_task(), ensure_ascii=False, indent=2))