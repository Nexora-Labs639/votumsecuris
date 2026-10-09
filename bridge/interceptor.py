"""
安全网关
- 拦截 OpenClaw 的所有工具调用
- 调 policy/engine.py 判断 allow / deny / require_approval
- require_approval 时推送到手机，等审批结果
"""
import asyncio
import uuid
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from policy.engine import evaluate
from audit.writer import log


async def check_tool_call(agent_id: str, tool_name: str, params: dict,
                          risk: str = "medium", undo=None,
                          broadcast_fn=None, pending_approvals: dict = None) -> dict:
    """
    拦截一次工具调用。
    返回: {"action": "allow|deny|approved|rejected", "reason": str}
    """
    decision = evaluate(tool_name, params, risk, undo)
    action = decision["action"]
    reason = decision["reason"]
    severity = decision.get("severity", "info")

    # deny：直接拒绝，写日志
    if action == "deny":
        try:
            log(agent_id, tool_name, params, "", "denied")
        except Exception:
            pass
        return {"action": "deny", "reason": reason, "severity": severity}

    # allow：直接放行，写日志
    if action == "allow":
        try:
            log(agent_id, tool_name, params, "allowed", "ok")
        except Exception:
            pass
        return {"action": "allow", "reason": reason, "severity": severity}

    # require_approval：推送到手机，等待审批
    if action == "require_approval":
        if broadcast_fn is None or pending_approvals is None:
            # 没有手机连接时，默认拒绝（安全优先）
            return {"action": "deny", "reason": "无手机端连接，自动拒绝", "severity": "critical"}

        approval_id = str(uuid.uuid4())[:8]
        future = asyncio.get_event_loop().create_future()
        pending_approvals[approval_id] = {
            "tool": tool_name,
            "params": params,
            "reason": reason,
            "future": future,
        }

        await broadcast_fn({
            "type": "approval_request",
            "payload": {
                "approval_id": approval_id,
                "tool": tool_name,
                "params": params,
                "reason": reason,
                "severity": severity,
            },
        })

        try:
            approved = await asyncio.wait_for(future, timeout=300)
        except asyncio.TimeoutError:
            pending_approvals.pop(approval_id, None)
            return {"action": "deny", "reason": "审批超时，自动拒绝", "severity": "warn"}

        if approved:
            try:
                log(agent_id, tool_name, params, "user_approved", "approved")
            except Exception:
                pass
            return {"action": "approved", "reason": "用户已批准", "severity": severity}
        else:
            try:
                log(agent_id, tool_name, params, "user_rejected", "rejected")
            except Exception:
                pass
            return {"action": "rejected", "reason": "用户已拒绝", "severity": severity}

    return {"action": "deny", "reason": "未知决策", "severity": "critical"}
    """
把上面的广播函数适配成 server.py 的广播接口
"""


def make_broadcast_fn(broadcast_coro):
    """
    broadcast_coro: server.py 里的 broadcast 函数（async def broadcast(msg: str)）
    这里包装一下，让它接收 dict 而不是 str
    """
    import json
    from datetime import datetime, timezone

    async def _broadcast(msg_dict: dict):
        wrapped = json.dumps({
            "type": msg_dict.get("type", "log"),
            "ts": datetime.now(timezone.utc).isoformat(),
            "payload": msg_dict.get("payload", {}),
        }, ensure_ascii=False)
        await broadcast_coro(wrapped)

    return _broadcast

if __name__ == "__main__":
    import asyncio

    async def test():
        r1 = await check_tool_call(
            "test-agent", "delete_file", {"path": "D:/tmp/a.tmp"}, "medium"
        )
        print(f"[缓存文件] {r1}")

        r2 = await check_tool_call(
            "test-agent", "delete_file", {"path": "D:/important.docx"}, "medium"
        )
        print(f"[重要文件] {r2}")

        r3 = await check_tool_call(
            "test-agent", "delete_file", {"path": "C:/Windows/x.dll"}, "medium"
        )
        print(f"[系统目录] {r3}")

        r4 = await check_tool_call(
            "test-agent", "run_shell", {"command": "rm -rf /"}, "high"
        )
        print(f"[危险命令] {r4}")

    asyncio.run(test())