"""
Windows-MCP 客户端（调试版）
- 完整打印错误
"""
import asyncio
import json
import time
import traceback
from pathlib import Path
from datetime import datetime, timezone
import sys

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import mcp
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client as streamablehttp_client

HAS_MCP = True

MCP_URL = "http://127.0.0.1:8000/mcp"
DEFAULT_TIMEOUT = 30

BLOCKED_TOOLS = {"PowerShell", "Process", "Registry"}

ALLOWED_TOOLS = {
    "Click", "Type", "Scroll", "Move", "Shortcut",
    "Wait", "WaitFor", "ControlStatus", "DisplayInventory",
    "Screenshot", "Snapshot", "App", "FileSystem", "Scrape",
    "MultiSelect", "MultiEdit", "Clipboard", "Notification",
}


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _log(tag, msg):
    print(f"[{_ts()[:19]}] [MCP/{tag}] {msg}")


async def list_tools() -> dict:
    """获取工具列表（带完整错误）"""
    try:
        async with streamablehttp_client(MCP_URL) as streams:
            print(f"[DEBUG] streams 类型: {type(streams)}, 长度: {len(streams) if hasattr(streams, '__len__') else '?'}")
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                tools = [{"name": t.name, "description": t.description}
                         for t in result.tools]
                return {"ok": True, "result": tools, "error": ""}
    except BaseException as e:
        print("=" * 60)
        print("[完整错误堆栈]")
        traceback.print_exc()
        print("=" * 60)
        # 解 ExceptionGroup
        def _flatten(exc, depth=0):
            prefix = "  " * depth
            print(f"{prefix}{type(exc).__name__}: {exc}")
            if hasattr(exc, "exceptions"):
                for sub in exc.exceptions:
                    _flatten(sub, depth + 1)
        _flatten(e)
        return {"ok": False, "result": None,
                "error": f"{type(e).__name__}: {e}"}


async def call_tool(tool_name: str, params: dict = None,
                    timeout: int = DEFAULT_TIMEOUT) -> dict:
    start = time.time()
    params = params or {}

    if tool_name in BLOCKED_TOOLS:
        return {"ok": False, "result": None,
                "error": f"工具 '{tool_name}' 被安全策略禁用", "elapsed_ms": 0}
    if tool_name not in ALLOWED_TOOLS:
        return {"ok": False, "result": None,
                "error": f"未知工具 '{tool_name}'", "elapsed_ms": 0}

    try:
        async with streamablehttp_client(MCP_URL) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await asyncio.wait_for(
                    session.call_tool(tool_name, arguments=params),
                    timeout=timeout,
                )
                elapsed = int((time.time() - start) * 1000)
                content = []
                for c in result.content:
                    if hasattr(c, "text"):
                        content.append(c.text)
                    else:
                        content.append(str(c))
                return {"ok": True, "result": content,
                        "error": "", "elapsed_ms": elapsed}
    except BaseException as e:
        print("=" * 60)
        print(f"[{tool_name} 完整错误]")
        traceback.print_exc()
        print("=" * 60)
        elapsed = int((time.time() - start) * 1000)
        return {"ok": False, "result": None,
                "error": f"{type(e).__name__}: {e}",
                "elapsed_ms": elapsed}


if __name__ == "__main__":
    print("=== 环境检查 ===")
    print(f"mcp 库: {mcp}")
    print(f"streamable_http 可用")
    print()

    async def test():
        print("=== 测试 1：列出工具 ===")
        r = await list_tools()
        print(json.dumps(r, ensure_ascii=False, indent=2)[:1500])

    asyncio.run(test())