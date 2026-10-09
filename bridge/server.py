"""
WebSocket 服务端（终级版）
- 加固运行时错误
- 支持多客户端并发
- 支持心跳 + 超时清理
- 支持消息大小限制
"""
import asyncio
import json
import uuid
import time
import traceback
from pathlib import Path
from datetime import datetime, timezone
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from bridge.protocol import (
    make_msg, parse_msg, make_task,
    MSG_NEW_TASK, MSG_APPROVE, MSG_REJECT,
    MSG_QUERY_TASKS, MSG_PING, MSG_PONG,
    MSG_TASK_LIST, MSG_TASK_UPDATE,
    MSG_APPROVAL_REQUEST, MSG_PROGRESS, MSG_LOG, MSG_ERROR,
    MSG_CHAT, MSG_CHAT_REPLY,
)

PORT = 8521
MAX_CLIENTS = 50
MAX_MSG_SIZE = 1024 * 1024
HEARTBEAT_TIMEOUT = 120
CLEANUP_INTERVAL = 30

clients = {}
tasks = {}
pending_approvals = {}


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _log(tag, msg):
    print(f"[{_ts()[:19]}] [{tag}] {msg}")


async def broadcast(msg):
    if not clients:
        return
    dead = []
    for ws in list(clients.keys()):
        try:
            await ws.send(msg)
            clients[ws]["last_seen"] = time.time()
        except Exception as e:
            _log("广播失败", str(e))
            dead.append(ws)
    for ws in dead:
        clients.pop(ws, None)


def make_broadcast_fn(broadcast_coro):
    async def _broadcast(msg_dict):
        try:
            wrapped = json.dumps({
                "type": msg_dict.get("type", "log"),
                "ts": _ts(),
                "payload": msg_dict.get("payload", {}),
            }, ensure_ascii=False)
            if len(wrapped) > MAX_MSG_SIZE:
                _log("警告", "广播消息过大，已截断")
                wrapped = wrapped[:MAX_MSG_SIZE]
            await broadcast_coro(wrapped)
        except Exception as e:
            _log("广播适配失败", str(e))
    return _broadcast


async def cleanup_dead_clients():
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL)
        now = time.time()
        dead = []
        for ws, info in list(clients.items()):
            if now - info["last_seen"] > HEARTBEAT_TIMEOUT:
                dead.append(ws)
        for ws in dead:
            clients.pop(ws, None)
            try:
                await ws.close()
            except Exception:
                pass
        if dead:
            _log("清理", f"清理 {len(dead)} 个超时连接")


async def handle_new_task(payload):
    """处理新任务：走聊天逻辑，交给安全网关"""
    try:
        from bridge.chat import handle_chat as _chat
    except Exception as e:
        _log("导入失败", str(e))
        return {"reply": f"系统错误: {e}", "task_id": "", "status": "error"}

    broadcast_fn = make_broadcast_fn(broadcast)
    try:
        return await _chat(
            payload,
            broadcast_fn=broadcast_fn,
            pending_approvals=pending_approvals,
        )
    except Exception as e:
        _log("任务失败", str(e))
        traceback.print_exc()
        return {"reply": f"任务执行失败: {e}", "task_id": "", "status": "error"}


async def handle_approve(payload):
    approval_id = payload.get("approval_id", "")
    if not approval_id:
        return None
    info = pending_approvals.pop(approval_id, None)
    if not info:
        return None
    future = info.get("future")
    if future and not future.done():
        future.set_result(True)
    return None


async def handle_reject(payload):
    approval_id = payload.get("approval_id", "")
    if not approval_id:
        return None
    info = pending_approvals.pop(approval_id, None)
    if not info:
        return None
    future = info.get("future")
    if future and not future.done():
        future.set_result(False)
    return None


async def handle_query_tasks(payload):
    return make_msg(MSG_TASK_LIST, {"tasks": list(tasks.values())})


async def handle_client(websocket):
    if len(clients) >= MAX_CLIENTS:
        _log("拒绝", f"连接数超过 {MAX_CLIENTS}")
        try:
            await websocket.close(code=1013, reason="server busy")
        except Exception:
            pass
        return

    client_id = str(uuid.uuid4())[:8]
    clients[websocket] = {"last_seen": time.time(), "id": client_id}
    _log("连接", f"{client_id}，当前 {len(clients)} 个")

    try:
        await websocket.send(make_msg(MSG_TASK_LIST, {"tasks": list(tasks.values())}))

        async for raw in websocket:
            if len(raw) > MAX_MSG_SIZE:
                _log("警告", f"{client_id} 消息过大，已忽略")
                continue

            clients[websocket]["last_seen"] = time.time()
            msg = parse_msg(raw)
            if not msg:
                continue

            msg_type = msg["type"]
            payload = msg.get("payload", {})

            try:
                if msg_type == MSG_PING:
                    await websocket.send(make_msg(MSG_PONG))
                elif msg_type in (MSG_NEW_TASK, MSG_CHAT):
                    reply = await handle_new_task(payload)
                    if reply:
                        await websocket.send(make_msg(MSG_CHAT_REPLY, reply))
                elif msg_type == MSG_APPROVE:
                    await handle_approve(payload)
                elif msg_type == MSG_REJECT:
                    await handle_reject(payload)
                elif msg_type == MSG_QUERY_TASKS:
                    reply = await handle_query_tasks(payload)
                    if reply:
                        await websocket.send(reply)
            except Exception as e:
                _log("处理失败", f"{msg_type}: {e}")
                traceback.print_exc()

    except Exception as e:
        _log("连接异常", f"{client_id}: {e}")
    finally:
        clients.pop(websocket, None)
        _log("断开", f"{client_id}，当前 {len(clients)} 个")


async def main():
    try:
        import websockets
    except ImportError:
        print("[错误] 缺少 websockets，请运行: pip install websockets")
        return

    asyncio.create_task(cleanup_dead_clients())

    _log("启动", f"WebSocket 服务端，端口 {PORT}")
    try:
        async with websockets.serve(
            handle_client, "0.0.0.0", PORT,
            max_size=MAX_MSG_SIZE,
            ping_interval=30,
            ping_timeout=60,
        ):
            await asyncio.Future()
    except OSError as e:
        _log("端口错误", f"端口 {PORT} 被占用或权限不足: {e}")
    except Exception as e:
        _log("启动失败", str(e))
        traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _log("退出", "收到 Ctrl+C，正常退出")