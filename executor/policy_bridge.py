"""
策略桥接层
UI 通过这个模块调策略引擎 + 执行器，不直接调底层
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from policy.engine import evaluate
from policy.honesty import check as honesty_check
from audit.writer import log
from executor.safe_delete import safe_delete


def request_delete(agent_id: str, path: str, user_approved: bool = False) -> dict:
    decision = evaluate("delete_file", {"path": path}, risk="medium", undo=None)
    action = decision["action"]

    if action == "deny":
        log(agent_id, "delete_file", {"path": path}, "", "denied")
        return {
            "status": "denied",
            "reason": decision["reason"],
            "severity": decision.get("severity", "warn"),
        }

    if action == "allow":
        result = safe_delete(agent_id, path)
        return {
            "status": "deleted" if result["ok"] else "error",
            "reason": decision["reason"],
            "severity": "info",
            "detail": result["msg"],
            "trash_path": result.get("trash_path", ""),
        }

    if action == "require_approval":
        if not user_approved:
            return {
                "status": "need_approval",
                "reason": decision["reason"],
                "severity": decision.get("severity", "warn"),
                "path": path,
            }
        log(agent_id, "delete_file", {"path": path}, "user_approved", "approved")
        result = safe_delete(agent_id, path)
        return {
            "status": "deleted" if result["ok"] else "error",
            "reason": decision["reason"],
            "severity": decision.get("severity", "warn"),
            "detail": result["msg"],
            "trash_path": result.get("trash_path", ""),
        }

    return {"status": "error", "reason": "未知判决", "severity": "error"}


def check_output(text: str) -> dict:
    return honesty_check(text)


if __name__ == "__main__":
    print("=== 测试1：缓存文件（自动删） ===")
    tmp = ROOT / "test_cache.tmp"
    tmp.write_text("cache", encoding="utf-8")
    print(request_delete("agent-test", str(tmp)))

    print("\n=== 测试2：重要文件（不审批） ===")
    docx = ROOT / "important.docx"
    docx.write_text("data", encoding="utf-8")
    print(request_delete("agent-test", str(docx), user_approved=False))

    print("\n=== 测试3：重要文件（已审批） ===")
    print(request_delete("agent-test", str(docx), user_approved=True))

    for f in [tmp, docx]:
        if f.exists():
            f.unlink()