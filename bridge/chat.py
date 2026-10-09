"""
聊天式交互
- 手机发自然语言
- PC 调 OpenClaw 干活
- 全程推回手机（进度 + 结果 + 审批）
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from bridge.openclaw_adapter import run_task


async def handle_chat(payload: dict, agent_id: str = "openclaw-agent",
                      broadcast_fn=None, pending_approvals: dict = None) -> dict:
    """
    处理一条聊天消息。
    返回: {"reply": str, "task_id": str, "status": str}
    """
    text = (payload.get("text") or "").strip()
    if not text:
        return {"reply": "消息为空", "task_id": "", "status": "error"}

    # 发任务给 OpenClaw
    task_id = payload.get("task_id") or "chat-" + str(abs(hash(text)))[:8]

    if broadcast_fn:
        await broadcast_fn({
            "type": "log",
            "payload": {"text": f"收到指令: {text}"},
        })

    result = await run_task(
        task_id=task_id,
        content=text,
        broadcast_fn=broadcast_fn,
        pending_approvals=pending_approvals,
    )

    # 生成回复
    if result["status"] == "done":
        reply = f"任务完成。执行了 {len(result['steps'])} 步。"
    elif result["status"] == "blocked":
        reply = f"任务被拦截。最后一步：{result['steps'][-1]['result']['reason']}"
    else:
        reply = f"任务状态: {result['status']}"

    if broadcast_fn:
        await broadcast_fn({
            "type": "chat_reply",
            "payload": {"task_id": task_id, "reply": reply, "status": result["status"]},
        })

    return {"reply": reply, "task_id": task_id, "status": result["status"]}


if __name__ == "__main__":
    import asyncio

    async def test():
        async def fake_broadcast(msg):
            print(f"[广播] {msg}")

        r = await handle_chat(
            {"text": "整理 D 盘下载文件夹"},
            broadcast_fn=fake_broadcast,
            pending_approvals={},
        )
        print(f"\n[回复] {r}")

    asyncio.run(test())