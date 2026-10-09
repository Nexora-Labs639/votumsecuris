"""测试客户端（聊天式）"""
import asyncio
import json
import websockets

async def test():
    uri = "ws://127.0.0.1:8521"
    async with websockets.connect(uri) as ws:
        print("[已连接]")

        msg = await ws.recv()
        print(f"[收到] {msg[:100]}...")

        # 发聊天消息
        await ws.send(json.dumps({
            "type": "chat",
            "payload": {"text": "整理 D 盘下载文件夹"},
        }, ensure_ascii=False))
        print("[已发送] 聊天消息")

        # 等 30 秒
        print("[等待] 30 秒...")
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=30.0)
                data = json.loads(msg)
                msg_type = data.get("type")
                payload = data.get("payload", {})

                if msg_type == "approval_request":
                    print(f"\n[审批请求]")
                    print(f"  工具: {payload.get('tool')}")
                    print(f"  参数: {payload.get('params')}")
                    print(f"  原因: {payload.get('reason')}")
                    approval_id = payload.get("approval_id")
                    await ws.send(json.dumps({
                        "type": "approve",
                        "payload": {"approval_id": approval_id},
                    }, ensure_ascii=False))
                    print(f"[已批准] {approval_id}")

                elif msg_type == "chat_reply":
                    print(f"[回复] {payload.get('reply')}")

                elif msg_type == "log":
                    print(f"[日志] {payload.get('text')}")

                else:
                    print(f"[收到] {msg_type}")

        except asyncio.TimeoutError:
            print("[超时] 退出")

if __name__ == "__main__":
    asyncio.run(test())