"""
自动回滚机制
- 对比最近两份评测报告
- 分数下降超阈值 → 告警
- --auto-rollback → 回滚知识库版本
"""
import sys
import json
import argparse
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

REPORTS_DIR = ROOT / "evals" / "reports"
ROLLBACK_LOG = ROOT / "evals" / "rollback_history.json"
DEFAULT_THRESHOLD = 5.0

def list_reports() -> list:
    """按时间倒序列出所有评测报告"""
    if not REPORTS_DIR.exists():
        return []
    files = sorted(REPORTS_DIR.glob("eval_*.json"), reverse=True)
    return files


def load_report(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        return {"error": str(e), "path": str(path)}


def get_last_two() -> tuple:
    """取最近两份报告：返回 (最新, 上一份)"""
    files = list_reports()
    if len(files) < 2:
        return None, None
    return load_report(files[0]), load_report(files[1])


def compare_reports(old: dict, new: dict) -> dict:
    """对比两份报告"""
    old_score = old.get("score", 0)
    new_score = new.get("score", 0)
    delta = round(new_score - old_score, 2)

    # 按分类对比
    by_cat = {}
    old_cats = old.get("by_category", {})
    new_cats = new.get("by_category", {})
    all_cats = set(old_cats.keys()) | set(new_cats.keys())
    for c in sorted(all_cats):
        old_v = old_cats.get(c, {}).get("score", 0)
        new_v = new_cats.get(c, {}).get("score", 0)
        by_cat[c] = {
            "old": old_v,
            "new": new_v,
            "delta": round(new_v - old_v, 2),
        }

    # 回归（原来过，现在挂）
    old_pass = {r["id"] for r in old.get("results", []) if r.get("passed")}
    new_pass = {r["id"] for r in new.get("results", []) if r.get("passed")}
    regressed = sorted(old_pass - new_pass)
    improved = sorted(new_pass - old_pass)

    return {
        "old_score": old_score,
        "new_score": new_score,
        "delta": delta,
        "by_category": by_cat,
        "regressed": regressed,
        "improved": improved,
    }
    
def load_history() -> list:
    if not ROLLBACK_LOG.exists():
        return []
    try:
        with open(ROLLBACK_LOG, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(history: list):
    ROLLBACK_LOG.parent.mkdir(exist_ok=True)
    with open(ROLLBACK_LOG, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)


def append_history(entry: dict):
    history = load_history()
    history.append(entry)
    save_history(history)


def trigger_rollback(reason: str, target_version: str = None) -> dict:
    """
    触发知识库回滚。
    优先回滚到 target_version；没指定则回滚到上一个版本。
    """
    from memory.version import list_versions, rollback

    if not target_version:
        versions = list_versions(limit=2)
        if len(versions) < 2:
            return {"ok": False, "error": "版本不足 2 个，无法回滚"}
        target_version = versions[1]["version"]

    r = rollback(target_version)

    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "target_version": target_version,
        "result": r,
    }
    append_history(entry)
    return entry


def rollback_from_file(history_entry: dict) -> bool:
    """判断一条历史记录是否是回滚动作"""
    return "target_version" in history_entry and history_entry.get("target_version")
    
def main():
    parser = argparse.ArgumentParser(description="评测对比 + 自动回滚")
    parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD,
                        help=f"分数下降阈值（默认 {DEFAULT_THRESHOLD}）")
    parser.add_argument("--auto-rollback", action="store_true",
                        help="分数下降超阈值时自动回滚")
    parser.add_argument("--history", action="store_true",
                        help="打印回滚历史")
    args = parser.parse_args()

    if args.history:
        history = load_history()
        if not history:
            print("无回滚历史")
            return
        print(f"共 {len(history)} 条回滚记录：")
        for h in history:
            print(f"  {h['ts']} | 原因: {h['reason']} | 目标版本: {h['target_version']}")
        return

    new, old = get_last_two()
    if not new or not old:
        print("[跳过] 评测报告不足 2 份，无法对比")
        return

    diff = compare_reports(old, new)

    print("=== 评测对比 ===")
    print(f"上一份: {diff['old_score']}%")
    print(f"最新份: {diff['new_score']}%")
    print(f"变化: {diff['delta']:+.2f}%")
    print()
    print("按分类：")
    for c, v in diff["by_category"].items():
        print(f"  {c}: {v['old']}% → {v['new']}% ({v['delta']:+.2f}%)")

    if diff["regressed"]:
        print(f"\n回归（原来是过的，现在挂）: {diff['regressed']}")
    if diff["improved"]:
        print(f"改善: {diff['improved']}")

    # 判断是否要回滚
    if diff["delta"] < -args.threshold:
        print(f"\n[告警] 分数下降 {-diff['delta']:.2f}% 超过阈值 {args.threshold}%")
        if args.auto_rollback:
            print("[自动回滚] 触发知识库回滚...")
            r = trigger_rollback(reason=f"评测分数下降 {diff['delta']}%")
            print(json.dumps(r, ensure_ascii=False, indent=2))
        else:
            print("[提示] 加 --auto-rollback 参数可自动回滚")
    else:
        print(f"\n[通过] 分数变化在允许范围内（阈值 {args.threshold}%）")


if __name__ == "__main__":
    main()
    