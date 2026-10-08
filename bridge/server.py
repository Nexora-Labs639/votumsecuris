"""
WebSocket 服务端
- 接收手机端的任务、审批
- 推送任务进度、审批请求给手机
"""
import asyncio
import json
import uuid
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from bridge.protocol import (
    make_msg, parse_msg, make_task,
    MSG_NEW_TASK, MSG_APPROVE, MSG_REJECT,
    MSG_QUERY_TASKS, MSG_PING, MSG_PONG,
    MSG_TASK_LIST, MSG_TASK_UPDATE,
    MSG_APPROVAL_REQUEST, MSG_PROGRESS, MSG_LOG, MSG_ERROR,
)

PORT = 8521

# 全局状态
clients = set()          # 所有连接的手机端
tasks = {}               # 任务表 {task_id: task_dict}
pending_approvals = {}   # 待审批 {approval_id: {task_id, tool, params, future}}


async def broadcast(msg: str):
    """向所有手机端广播消息"""
    if not clients:
        return
    dead = []
    for ws in clients:
        try:
            await ws.send(msg)
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)
async def handle_new_task(payload: dict):
    """处理新任务"""
    content = payload.get("content", "").strip()
    if not content:
        return make_msg(MSG_ERROR, {"reason": "任务内容为空"})

    task_id = str(uuid.uuid4())[:8]
    task = make_task(task_id, content)
    tasks[task_id] = task

    # 广播任务列表更新
    await broadcast(make_msg(MSG_TASK_UPDATE, task))
    await broadcast(make_msg(MSG_LOG, {"text": f"新任务: {content}"}))

    # TODO Day 3：把任务派发给 OpenClaw
    return None


async def handle_approve(payload: dict):
    """处理审批通过"""
    approval_id = payload.get("approval_id", "")
    if approval_id in pending_approvals:
        info = pending_approvals.pop(approval_id)
        future = info.get("future")
        if future and not future.done():
            future.set_result(True)
    return None


async def handle_reject(payload: dict):
    """处理审批拒绝"""
    approval_id = payload.get("approval_id", "")
    if approval_id in pending_approvals:
        info = pending_approvals.pop(approval_id)
        future = info.get("future")
        if future and not future.done():
            future.set_result(False)
    return None


async def handle_query_tasks(payload: dict):
    """查任务列表"""
    return make_msg(MSG_TASK_LIST, {"tasks": list(tasks.values())})
async def handle_client(websocket):
    """处理单个手机端连接"""
    clients.add(websocket)
    print(f"[连接] 新客户端，当前 {len(clients)} 个")
    try:
        # 连接时先推送任务列表
        await websocket.send(make_msg(MSG_TASK_LIST, {"tasks": list(tasks.values())}))

        async for raw in websocket:
            msg = parse_msg(raw)
            if not msg:
                continue

            msg_type = msg["type"]
            payload = msg.get("payload", {})

            if msg_type == MSG_PING:
                await websocket.send(make_msg(MSG_PONG))
            elif msg_type == MSG_NEW_TASK:
                reply = await handle_new_task(payload)
                if reply:
                    await websocket.send(reply)
            elif msg_type == MSG_APPROVE:
                await handle_approve(payload)
            elif msg_type == MSG_REJECT:
                await handle_reject(payload)
            elif msg_type == MSG_QUERY_TASKS:
                reply = await handle_query_tasks(payload)
                if reply:
                    await websocket.send(reply)

    except Exception as e:
        print(f"[错误] {e}")
    finally:
        clients.discard(websocket)
        print(f"[断开] 客户端离开，当前 {len(clients)} 个")


async def main():
    import websockets
    print(f"[启动] WebSocket 服务端，端口 {PORT}")
    async with websockets.serve(handle_client, "0.0.0.0", PORT):
        await asyncio.Future()  # 永久运行


if __name__ == "__main__":
    asyncio.run(main())
