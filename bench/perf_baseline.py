"""
性能基准
- 测策略引擎、RAG 检索、推理引擎的耗时
- 每个测试跑 N 次，取平均/最小/最大
"""
import sys
import time
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _bench(func, iterations: int = 10, warmup: int = 2) -> dict:
    """通用基准测试"""
    # 预热
    for _ in range(warmup):
        try:
            func()
        except Exception:
            pass

    times = []
    errors = 0
    for _ in range(iterations):
        start = time.perf_counter()
        try:
            func()
        except Exception:
            errors += 1
        elapsed = (time.perf_counter() - start) * 1000  # ms
        times.append(elapsed)

    if not times:
        return {"iterations": 0, "errors": errors}

    return {
        "iterations": iterations,
        "errors": errors,
        "avg_ms": round(statistics.mean(times), 3),
        "min_ms": round(min(times), 3),
        "max_ms": round(max(times), 3),
        "median_ms": round(statistics.median(times), 3),
        "stdev_ms": round(statistics.stdev(times), 3) if len(times) > 1 else 0,
    }
    
def bench_policy_engine(iterations: int = 100) -> dict:
    """策略引擎基准"""
    from policy.engine import evaluate

    def run():
        evaluate("delete_file", {"path": "D:/tmp/a.tmp"}, "medium", None)

    return _bench(run, iterations=iterations)


def bench_honesty(iterations: int = 100) -> dict:
    """诚实性检查基准"""
    from policy.honesty import check

    def run():
        check("我一定能完成任务")

    return _bench(run, iterations=iterations)


def bench_rag_search(iterations: int = 5) -> dict:
    """RAG 检索基准（含 embedding，慢）"""
    from memory.rag import search

    def run():
        search("测试", top_k=3)

    return _bench(run, iterations=iterations, warmup=1)


def bench_llm_inference(iterations: int = 2) -> dict:
    """推理基准（最慢）"""
    from executor.llm_control import run_llm

    def run():
        run_llm("用一句话回答: 你是什么", preset="fast")

    return _bench(run, iterations=iterations, warmup=0)


def run_all() -> dict:
    """跑所有基准"""
    results = {}
    print("[1/4] 策略引擎...")
    results["policy_engine"] = bench_policy_engine()
    print("[2/4] 诚实性检查...")
    results["honesty"] = bench_honesty()
    print("[3/4] RAG 检索（较慢）...")
    results["rag_search"] = bench_rag_search()
    print("[4/4] 推理引擎（最慢）...")
    results["llm_inference"] = bench_llm_inference()

    results["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return results
    
if __name__ == "__main__":
    print("=== 性能基准 ===")
    r = run_all()
    print("\n=== 结果 ===")
    print(json.dumps(r, ensure_ascii=False, indent=2))

    # 保存报告
    reports_dir = ROOT / "bench" / "reports"
    reports_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = reports_dir / f"perf_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {path}")