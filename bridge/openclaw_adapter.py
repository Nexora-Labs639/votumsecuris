"""
OpenClaw 适配层
- 接收任务
- 调 OpenClaw 执行
- 工具调用经过安全网关
"""
import sys
import asyncio
import subprocess
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from bridge.interceptor import check_tool_call


def is_openclaw_available() -> bool:
    """检查 openclaw 命令是否可用"""
    return shutil.which("openclaw") is not None


async def run_task(task_id: str, content: str,
                   broadcast_fn=None, pending_approvals: dict = None) -> dict:
    """
    执行任务。
    当前用 OpenClaw 命令行 + 安全网关拦截。
    """
    result = {"task_id": task_id, "steps": [], "status": "running"}

    if broadcast_fn:
        await broadcast_fn({
            "type": "log",
            "payload": {"text": f"OpenClaw 接收任务: {content}"},
        })

    # Step 1: 先规划（用 OpenClaw 命令行）
    if is_openclaw_available():
        try:
            r = subprocess.run(
                ["openclaw", "--version"],
                capture_output=True, text=True, timeout=10, shell=True,
            )
            version = (r.stdout or r.stderr).strip()
            if broadcast_fn:
                await broadcast_fn({
                    "type": "log",
                    "payload": {"text": f"OpenClaw 版本: {version}"},
                })
        except Exception as e:
            if broadcast_fn:
                await broadcast_fn({
                    "type": "log",
                    "payload": {"text": f"OpenClaw 调用失败: {e}"},
                })

    # Step 2: 模拟龙虾规划出的工具调用（经安全网关）
    # 真实版本：从 OpenClaw 输出解析出工具调用，逐个过网关
    planned_tools = [
        {"tool": "read_file", "params": {"path": "D:/temp/target.txt"}, "risk": "low"},
        {"tool": "delete_file", "params": {"path": "D:/temp/important.docx"}, "risk": "medium"},
    ]

    for i, step in enumerate(planned_tools, 1):
        res = await check_tool_call(
            agent_id="openclaw-agent",
            tool_name=step["tool"],
            params=step["params"],
            risk=step["risk"],
            broadcast_fn=broadcast_fn,
            pending_approvals=pending_approvals,
        )
        result["steps"].append({"step": i, "tool": step["tool"], "result": res})

        if broadcast_fn:
            await broadcast_fn({
                "type": "progress",
                "payload": {
                    "task_id": task_id,
                    "step": i,
                    "tool": step["tool"],
                    "action": res["action"],
                },
            })

        if res["action"] in ("deny", "rejected"):
            result["status"] = "blocked"
            return result

    result["status"] = "done"
    return result


if __name__ == "__main__":
    async def test():
        async def fake_broadcast(msg):
            print(f"[广播] {msg}")

        print("=== OpenClaw 是否可用 ===")
        print(f"  {is_openclaw_available()}")

        print("\n=== 模拟任务执行 ===")
        r = await run_task(
            "test-001", "整理 D 盘下载文件夹",
            broadcast_fn=fake_broadcast,
            pending_approvals={},
        )
        print(f"\n[最终结果] {r}")

    asyncio.run(test())