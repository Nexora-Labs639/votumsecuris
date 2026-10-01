import json
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from policy.engine import evaluate
from audit.writer import log
from executor.sandbox_runner import run_sandboxed
from executor.approval import request_approval

# 工具风险/undo 表（从 tools.yaml 读，这里先写死）
TOOL_META = {
    "read_file":   {"risk": "low",    "undo": None},
    "write_file":  {"risk": "medium", "undo": "delete_file"},
    "delete_file": {"risk": "medium", "undo": None},
    "run_shell":   {"risk": "high",   "undo": None},
}

def execute_step(agent_id: str, tool_name: str, params: dict, undo_map: dict) -> bool:
    meta = TOOL_META.get(tool_name, {"risk": "high", "undo": None})
    decision = evaluate(tool_name, params, meta["risk"], meta["undo"])
    action = decision["action"]
    print(f"[策略] {tool_name} -> {action} ({decision['reason']})")

    if action == "deny":
        log(agent_id, tool_name, params, "", "denied")
        return False

    if action == "require_approval":
        if not request_approval(tool_name, params, decision["reason"]):
            log(agent_id, tool_name, params, "", "rejected")
            return False

    if tool_name == "run_shell":
        result = run_sandboxed(params["command"])
        status = result["status"]
        log(agent_id, tool_name, params, result["stdout"] + result["stderr"], status)
        return status == "ok"

    if tool_name == "write_file":
        try:
            p = Path(params["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(params["content"], encoding="utf-8")
            log(agent_id, tool_name, params, f"written {p}", "ok")
            return True
        except Exception as e:
            log(agent_id, tool_name, params, str(e), "error")
            return False

    if tool_name == "read_file":
        try:
            content = Path(params["path"]).read_text(encoding="utf-8")
            log(agent_id, tool_name, params, content, "ok")
            return True
        except Exception as e:
            log(agent_id, tool_name, params, str(e), "error")
            return False

    log(agent_id, tool_name, params, "executed", "ok")
    return True


def run_saga(agent_id: str, steps: list, undo_map: dict):
    done = []
    for i, step in enumerate(steps):
        print(f"\n[Saga] 第 {i+1} 步: {step['tool']}")
        ok = execute_step(agent_id, step["tool"], step["params"], undo_map)
        if not ok:
            print(f"\n[Saga] 第 {i+1} 步失败，开始回滚前 {len(done)} 步...")
            for j, prev in enumerate(reversed(done)):
                undo = undo_map.get(prev["tool"])
                if undo:
                    print(f"[回滚] 撤销第 {len(done)-j} 步: {prev['tool']}")
                    undo(prev["params"])
                    log(agent_id, "undo_" + prev["tool"], prev["params"], "", "rolled_back")
                else:
                    print(f"[回滚] {prev['tool']} 无补偿动作，跳过")
            return False
        done.append(step)
    print("\n[Saga] 全部步骤成功。")
    return True


if __name__ == "__main__":
    # 测试：三步，第三步会失败（rm -rf 危险命令被 deny）
    steps = [
        {"tool": "write_file", "params": {"path": "a.txt", "content": "hi"}},
        {"tool": "write_file", "params": {"path": "b.txt", "content": "hi"}},
        {"tool": "run_shell", "params": {"command": "rm -rf /"}},
    ]

    def undo_write_file(params):
        p = Path(params["path"])
        if p.exists():
            p.unlink()
            print(f"    已删除 {p}")

    undo_map = {
        "write_file": undo_write_file,
    }

    run_saga("agent-test", steps, undo_map)