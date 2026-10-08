"""
简易测试客户端
模拟手机端连接、发任务、收消息
"""
import asyncio
import json
import websockets

async def test():
    uri = "ws://127.0.0.1:8521"
    async with websockets.connect(uri) as ws:
        print("[已连接]")

        # 收初始消息
        msg = await ws.recv()
        print(f"[收到] {msg}")

        # 发一个任务
        await ws.send(json.dumps({
            "type": "new_task",
            "payload": {"content": "整理 D 盘下载文件夹"},
        }, ensure_ascii=False))
        print("[已发送] 新任务")

        # 收回复
        for _ in range(2):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
                print(f"[收到] {msg}")
            except asyncio.TimeoutError:
                break

if __name__ == "__main__":
    asyncio.run(test())