import re
from pathlib import Path
import yaml

ROOT = Path(__file__).parent.parent

def load_rules():
    with open(ROOT / "policy" / "rules.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["rules"]

def evaluate(tool_name: str, params: dict, risk: str, undo=None) -> dict:
    """
    返回: {"action": "allow|deny|require_approval", "reason": str}
    undo: 该工具的补偿动作名，None 表示不可撤销
    """
    for rule in load_rules():
        match = rule.get("match", "*")
        if match != "*" and match != tool_name:
            continue
        cond = rule.get("condition", "True")
        ctx = {
            "command": params.get("command", ""),
            "path": params.get("path", ""),
            "risk": risk,
            "tool": tool_name,
            "params": params,
            "undo": undo,
        }
        try:
            ok = eval(cond, {"__builtins__": {}}, ctx)
        except Exception:
            ok = False
        if ok:
            return {"action": rule["action"], "reason": rule.get("reason", "")}
    return {"action": "allow", "reason": "no rule matched"}


if __name__ == "__main__":
    cases = [
        ("read_file", {"path": "a.txt"}, "low", None),
        ("write_file", {"path": "a.txt", "content": "hi"}, "medium", "delete_file"),
        ("write_file", {"path": "C:\\\\Windows\\\\x.txt", "content": "hi"}, "medium", "delete_file"),
        ("run_shell", {"command": "echo hello"}, "high", None),
        ("run_shell", {"command": "rm -rf /"}, "high", None),
    ]
    for name, params, risk, undo in cases:
        r = evaluate(name, params, risk, undo)
        print(f"{name:12s} {str(params):45s} undo={str(undo):12s} -> {r['action']:18s} {r['reason']}")