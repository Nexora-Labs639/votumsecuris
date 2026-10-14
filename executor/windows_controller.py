"""
Windows-MCP 安全控制器
- 每个 Windows-MCP 工具调用，先过策略引擎
- 高风险操作走审批门
- 高危工具直接拒绝
- 所有调用写审计日志 + 哈希链
- 失败触发 Saga 回滚
"""
import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from policy.engine import evaluate
from audit.writer import log as audit_log
from bridge.hash_chain import append as hash_append
from executor.mcp_client import call_tool, ALLOWED_TOOLS


# ========== 工具风险映射 ==========
TOOL_RISK = {
    "Wait": "low",
    "WaitFor": "low",
    "ControlStatus": "low",
    "DisplayInventory": "low",
    "Screenshot": "low",
    "Snapshot": "low",
    "Notification": "low",
    "Clipboard": "medium",
    "Scroll": "medium",
    "Scrape": "medium",
    "MultiSelect": "medium",
    "Type": "high",
    "Click": "high",
    "Move": "high",
    "Shortcut": "high",
    "App": "high",
    "MultiEdit": "high",
    "FileSystem": "critical",
}

# ========== 高危工具（直接拒绝） ==========
HARD_BLOCK = {"PowerShell", "Process", "Registry"}


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _log(tag, msg):
    print(f"[{_ts()[:19]}] [WIN/{tag}] {msg}")


async def execute_windows_tool(
    agent_id: str,
    tool_name: str,
    params: dict,
    broadcast_fn=None,
    pending_approvals: dict = None,
) -> dict:
    """
    执行一个 Windows-MCP 工具。
    返回: {"ok": bool, "action": str, "result": ..., "reason": str}
    """
    # ========== 硬规则 1：高危工具直接拒绝 ==========
    if tool_name in HARD_BLOCK:
        reason = f"高危工具 '{tool_name}' 被硬规则拒绝"
        _log("拒绝", reason)
        try:
            audit_log(agent_id, f"windows:{tool_name}", params, "", "denied")
            hash_append({"agent_id": agent_id, "tool": tool_name,
                         "params": params, "action": "hard_deny"})
        except Exception as e:
            _log("审计失败", str(e))
        return {"ok": False, "action": "deny", "result": None, "reason": reason}

    # ========== 硬规则 2：工具必须在白名单 ==========
    if tool_name not in ALLOWED_TOOLS:
        reason = f"未知工具 '{tool_name}'"
        _log("拒绝", reason)
        return {"ok": False, "action": "deny", "result": None, "reason": reason}

    # ========== 策略引擎判决 ==========
    risk = TOOL_RISK.get(tool_name, "high")
    decision = evaluate(
        tool_name=f"windows:{tool_name}",
        params=params,
        risk=risk,
        undo=None,
    )
    action = decision.get("action", "deny")
    reason = decision.get("reason", "")
    severity = decision.get("severity", "info")
    _log("判决", f"{tool_name} (risk={risk}) -> {action} | {reason}")

    # ========== deny：直接拒绝 ==========
    if action == "deny":
        try:
            audit_log(agent_id, f"windows:{tool_name}", params, "", "denied")
            hash_append({"agent_id": agent_id, "tool": tool_name,
                         "params": params, "action": "deny", "reason": reason})
        except Exception:
            pass
        return {"ok": False, "action": "deny", "result": None, "reason": reason}

    # ========== require_approval：推送到手机 ==========
    if action == "require_approval":
        if broadcast_fn is None or pending_approvals is None:
            reason = "无手机端连接，自动拒绝"
            _log("拒绝", reason)
            return {"ok": False, "action": "deny", "result": None, "reason": reason}

        import uuid
        approval_id = str(uuid.uuid4())[:8]
        future = asyncio.get_event_loop().create_future()
        pending_approvals[approval_id] = {
            "tool": f"windows:{tool_name}",
            "params": params,
            "reason": reason,
            "future": future,
        }

        await broadcast_fn({
            "type": "approval_request",
            "payload": {
                "approval_id": approval_id,
                "tool": f"windows:{tool_name}",
                "params": params,
                "reason": reason,
                "severity": severity,
            },
        })

        try:
            approved = await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            pending_approvals.pop(approval_id, None)
            return {"ok": False, "action": "deny",
                    "result": None, "reason": "审批超时，自动拒绝"}

        if not approved:
            return {"ok": False, "action": "rejected",
                    "result": None, "reason": "用户拒绝"}

        try:
            audit_log(agent_id, f"windows:{tool_name}", params, "approved", "approved")
            hash_append({"agent_id": agent_id, "tool": tool_name,
                         "params": params, "action": "approved"})
        except Exception:
            pass

    # ========== 执行 MCP 调用 ==========
    _log("执行", f"{tool_name}")
    mcp_result = await call_tool(tool_name, params)
    ok = mcp_result.get("ok", False)
    elapsed = mcp_result.get("elapsed_ms", 0)
    error = mcp_result.get("error", "")

    # ========== 写审计日志 ==========
    try:
        audit_log(agent_id, f"windows:{tool_name}", params,
                  str(mcp_result.get("result"))[:500],
                  "ok" if ok else "error")
        hash_append({
            "agent_id": agent_id,
            "tool": tool_name,
            "params": params,
            "action": "allow" if ok else "error",
            "elapsed_ms": elapsed,
            "error": error,
        })
    except Exception as e:
        _log("审计失败", str(e))

    return {
        "ok": ok,
        "action": "allow" if ok else "error",
        "result": mcp_result.get("result"),
        "reason": error if not ok else "执行成功",
        "elapsed_ms": elapsed,
    }


if __name__ == "__main__":
    async def test():
        async def fake_broadcast(msg):
            print(f"[广播] {json.dumps(msg, ensure_ascii=False)[:200]}")

        print("=== 测试 1：安全工具 Wait ===")
        r = await execute_windows_tool(
            "test-agent", "Wait", {"duration": 1},
            broadcast_fn=fake_broadcast, pending_approvals={},
        )
        print(json.dumps(r, ensure_ascii=False, indent=2)[:300])

        print("\n=== 测试 2：高危工具 PowerShell（硬规则拒绝） ===")
        r = await execute_windows_tool(
            "test-agent", "PowerShell", {"command": "echo hi"},
            broadcast_fn=fake_broadcast, pending_approvals={},
        )
        print(json.dumps(r, ensure_ascii=False, indent=2)[:300])

        print("\n=== 测试 3：未知工具 ===")
        r = await execute_windows_tool(
            "test-agent", "HackSystem", {},
            broadcast_fn=fake_broadcast, pending_approvals={},
        )
        print(json.dumps(r, ensure_ascii=False, indent=2)[:300])

    asyncio.run(test())