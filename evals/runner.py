"""
评测执行器（终级版）
- 100 条测试集，6 个维度
- 多指标：准确率 + 加权分 + 耗时
- 对抗样本单独统计
- 报告可追溯（git commit + timestamp）
"""
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from evals.dataset import load_dataset, stats as dataset_stats

REPORTS_DIR = ROOT / "evals" / "reports"


def _git_commit() -> str:
    try:
        r = subprocess.run(
            "git rev-parse --short HEAD",
            cwd=str(ROOT), capture_output=True, text=True,
            timeout=5, shell=True,
        )
        return r.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def _score_security(case) -> dict:
    try:
        from policy.engine import evaluate
        inp = case["input"]
        r = evaluate(inp.get("tool", ""), inp, "medium", None)
        return {
            "passed": r.get("action") == case["expected"],
            "actual": r.get("action", "unknown"),
            "expected": case["expected"],
        }
    except Exception as e:
        return {"passed": False, "actual": f"异常: {e}", "expected": case["expected"]}


def _score_honesty(case) -> dict:
    try:
        from policy.honesty import check
        r = check(case["input"])
        expected = case["expected"]
        if expected == "blocked":
            ok = r.get("blocked", False)
        elif expected == "rewritten":
            ok = r.get("triggered", False) and not r.get("blocked", False)
        else:
            ok = not r.get("triggered", False)
        actual = "blocked" if r.get("blocked") else ("rewritten" if r.get("triggered") else "pass")
        return {"passed": ok, "actual": actual, "expected": expected}
    except Exception as e:
        return {"passed": False, "actual": f"异常: {e}", "expected": case["expected"]}


def _score_rag(case) -> dict:
    try:
        from memory.rag import search
        results = search(case["input"], top_k=3)
        expected = case["expected"]
        if expected == "has_result":
            ok = len(results) > 0
        else:
            ok = len(results) == 0
        return {"passed": ok, "actual": len(results), "expected": expected}
    except Exception as e:
        return {"passed": False, "actual": f"异常: {e}", "expected": case["expected"]}


def _score_inference(case) -> dict:
    try:
        from executor.llm_control import run_llm
        inp = case["input"]
        preset = inp.get("preset", "balanced")
        base = inp.get("model", "qwen")
        expected = case["expected"]

        if expected == "error":
            r = run_llm("测试", preset=preset, base=base)
            ok = not r.get("ok", False)
            return {"passed": ok, "actual": "error" if not r.get("ok") else "ok",
                    "expected": "error", "elapsed": r.get("elapsed", 0)}

        r = run_llm("用一个词回答: 你是什么", preset=preset, base=base)
        if expected == "fast_enough":
            ok = r.get("ok", False) and r.get("elapsed", 999) < 60
            return {"passed": ok, "actual": f"{r.get('elapsed', 0)}秒",
                    "expected": "<60秒", "elapsed": r.get("elapsed", 0)}

        return {"passed": r.get("ok", False),
                "actual": "ok" if r.get("ok") else "error",
                "expected": "ok", "elapsed": r.get("elapsed", 0)}
    except Exception as e:
        return {"passed": False, "actual": f"异常: {e}", "expected": case["expected"]}


def _score_adversarial(case) -> dict:
    return _score_security(case)


SCORERS = {
    "security": _score_security,
    "honesty": _score_honesty,
    "rag": _score_rag,
    "inference": _score_inference,
    "adversarial": _score_adversarial,
}


def run_eval(category: str = None, verbose: bool = False) -> dict:
    """跑评测，返回完整报告"""
    cases = load_dataset(category)
    if not cases:
        return {
            "ts": datetime.now(timezone.utc).isoformat(),
            "git_commit": _git_commit(),
            "total": 0, "passed": 0, "score": 0.0,
            "weighted_score": 0.0,
            "by_category": {},
            "by_weight": {},
            "elapsed_total": 0.0,
            "results": [],
        }

    results = []
    by_cat = {}
    by_weight = {1: {"total": 0, "passed": 0}, 2: {"total": 0, "passed": 0}, 3: {"total": 0, "passed": 0}}
    start_total = time.time()

    for case in cases:
        cat = case["cat"]
        w = case.get("w", 1)
        scorer = SCORERS.get(cat)

        if not scorer:
            if verbose:
                print(f"  ? [{case['id']}] 未知类别: {cat}")
            continue

        start = time.time()
        r = scorer(case)
        elapsed = round(time.time() - start, 3)

        by_cat.setdefault(cat, {"total": 0, "passed": 0})
        by_cat[cat]["total"] += 1
        if r["passed"]:
            by_cat[cat]["passed"] += 1

        if w in by_weight:
            by_weight[w]["total"] += 1
            if r["passed"]:
                by_weight[w]["passed"] += 1

        results.append({
            "id": case["id"],
            "category": cat,
            "weight": w,
            "passed": r["passed"],
            "actual": r.get("actual"),
            "expected": r.get("expected"),
            "elapsed": elapsed,
        })

        if verbose:
            status = "✓" if r["passed"] else "✗"
            print(f"  {status} [{case['id']}] {cat} 期望={r.get('expected')} 实际={r.get('actual')} ({elapsed}s)")

    total_elapsed = round(time.time() - start_total, 3)
    total = len(results)
    passed = sum(1 for r in results if r["passed"])
    score = round(passed / total * 100, 2) if total else 0.0

    total_w = sum(r["weight"] for r in results)
    passed_w = sum(r["weight"] for r in results if r["passed"])
    weighted_score = round(passed_w / total_w * 100, 2) if total_w else 0.0

    return {
        "ts": datetime.now(timezone.utc).isoformat(),
        "git_commit": _git_commit(),
        "total": total,
        "passed": passed,
        "score": score,
        "weighted_score": weighted_score,
        "by_category": {
            cat: {
                "total": v["total"],
                "passed": v["passed"],
                "score": round(v["passed"] / v["total"] * 100, 2) if v["total"] else 0,
            }
            for cat, v in by_cat.items()
        },
        "by_weight": {
            str(w): {
                "total": v["total"],
                "passed": v["passed"],
                "score": round(v["passed"] / v["total"] * 100, 2) if v["total"] else 0,
            }
            for w, v in by_weight.items()
        },
        "elapsed_total": total_elapsed,
        "results": results,
    }


def save_report(result: dict, filename: str = None) -> str:
    REPORTS_DIR.mkdir(exist_ok=True)
    if not filename:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"eval_{ts}.json"
    path = REPORTS_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return str(path)


def compare_reports(old: dict, new: dict) -> dict:
    """对比两份报告，返回差异"""
    diff = {
        "score_delta": round(new.get("score", 0) - old.get("score", 0), 2),
        "weighted_delta": round(new.get("weighted_score", 0) - old.get("weighted_score", 0), 2),
        "elapsed_delta": round(new.get("elapsed_total", 0) - old.get("elapsed_total", 0), 2),
        "regressed": [],
        "improved": [],
    }
    old_by_id = {r["id"]: r for r in old.get("results", [])}
    for r in new.get("results", []):
        old_r = old_by_id.get(r["id"])
        if not old_r:
            continue
        if old_r["passed"] and not r["passed"]:
            diff["regressed"].append(r["id"])
        elif not old_r["passed"] and r["passed"]:
            diff["improved"].append(r["id"])
    return diff


if __name__ == "__main__":
    print("=== 数据集统计 ===", file=sys.stderr)
    print(json.dumps(dataset_stats(), ensure_ascii=False, indent=2), file=sys.stderr)

    print("\n=== 跑评测 ===", file=sys.stderr)
    result = run_eval(verbose=True)

    print(f"\n=== 结果 ===", file=sys.stderr)
    print(f"总分: {result['score']}% ({result['passed']}/{result['total']})", file=sys.stderr)
    print(f"加权总分: {result['weighted_score']}%", file=sys.stderr)
    print(f"总耗时: {result['elapsed_total']}秒", file=sys.stderr)
    print("\n按类别:", file=sys.stderr)
    for cat, v in result["by_category"].items():
        print(f"  {cat}: {v['score']}% ({v['passed']}/{v['total']})", file=sys.stderr)
    print("\n按难度:", file=sys.stderr)
    for w, v in result["by_weight"].items():
        print(f"  权重{w}: {v['score']}% ({v['passed']}/{v['total']})", file=sys.stderr)

    path = save_report(result)
    print(f"\n报告已保存: {path}", file=sys.stderr)

    # 打印报告 JSON 到 stdout，方便管道
    print(json.dumps({
        "score": result["score"],
        "weighted_score": result["weighted_score"],
        "total": result["total"],
        "passed": result["passed"],
        "by_category": result["by_category"],
        "by_weight": result["by_weight"],
    }, ensure_ascii=False, indent=2))