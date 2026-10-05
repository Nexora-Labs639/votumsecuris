"""
并发压测
- 模拟多 Agent 同时干活
- 测吞吐量、响应时间、错误率
"""
import sys
import time
import json
import threading
import statistics
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def _worker_policy(n: int) -> dict:
    """单个 worker：跑 n 次策略判断"""
    from policy.engine import evaluate
    times = []
    errors = 0
    for i in range(n):
        start = time.perf_counter()
        try:
            evaluate("delete_file", {"path": f"D:/tmp/x{i}.tmp"}, "medium", None)
        except Exception:
            errors += 1
        times.append((time.perf_counter() - start) * 1000)
    return {"times": times, "errors": errors}
    
def load_test_policy(concurrency: int = 10, per_worker: int = 50) -> dict:
    """并发跑策略引擎"""
    print(f"[策略引擎压测] 并发={concurrency}, 每 worker={per_worker} 次")
    start = time.perf_counter()
    all_times = []
    total_errors = 0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_worker_policy, per_worker) for _ in range(concurrency)]
        for future in as_completed(futures):
            r = future.result()
            all_times.extend(r["times"])
            total_errors += r["errors"]

    total_elapsed = time.perf_counter() - start
    total_requests = concurrency * per_worker

    return {
        "concurrency": concurrency,
        "per_worker": per_worker,
        "total_requests": total_requests,
        "total_elapsed_s": round(total_elapsed, 3),
        "qps": round(total_requests / total_elapsed, 2) if total_elapsed > 0 else 0,
        "avg_ms": round(statistics.mean(all_times), 3) if all_times else 0,
        "min_ms": round(min(all_times), 3) if all_times else 0,
        "max_ms": round(max(all_times), 3) if all_times else 0,
        "p95_ms": round(sorted(all_times)[int(len(all_times) * 0.95)], 3) if all_times else 0,
        "errors": total_errors,
    }


def _worker_audit(n: int) -> dict:
    """单个 worker：写 n 条审计日志"""
    from identity.audit import record
    from identity.agent_id import create_agent
    a = create_agent(f"load-test-{threading.get_ident()}", "压测用")
    errors = 0
    for i in range(n):
        try:
            record(a["uuid"], "read_file", {"path": f"D:/x{i}.txt"},
                   action="allow", severity="info", user_id="loadtest")
        except Exception:
            errors += 1
    return {"errors": errors}


def load_test_audit(concurrency: int = 10, per_worker: int = 50) -> dict:
    """并发跑审计写入"""
    print(f"[审计写入压测] 并发={concurrency}, 每 worker={per_worker} 次")
    start = time.perf_counter()
    total_errors = 0

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(_worker_audit, per_worker) for _ in range(concurrency)]
        for future in as_completed(futures):
            total_errors += future.result()["errors"]

    total_elapsed = time.perf_counter() - start
    total_requests = concurrency * per_worker

    return {
        "concurrency": concurrency,
        "per_worker": per_worker,
        "total_requests": total_requests,
        "total_elapsed_s": round(total_elapsed, 3),
        "qps": round(total_requests / total_elapsed, 2) if total_elapsed > 0 else 0,
        "errors": total_errors,
    }
    
def run_all_load_tests() -> dict:
    """跑所有压测"""
    results = {}
    print("=== 并发压测 ===\n")

    for conc in [1, 5, 10, 20]:
        results[f"policy_conc_{conc}"] = load_test_policy(concurrency=conc, per_worker=50)

    print()
    for conc in [1, 5, 10]:
        results[f"audit_conc_{conc}"] = load_test_audit(concurrency=conc, per_worker=30)

    results["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    return results


if __name__ == "__main__":
    r = run_all_load_tests()
    print("\n=== 结果 ===")
    print(json.dumps(r, ensure_ascii=False, indent=2))

    reports_dir = ROOT / "bench" / "reports"
    reports_dir.mkdir(exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S")
    path = reports_dir / f"load_{ts}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
    print(f"\n报告已保存: {path}")