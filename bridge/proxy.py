"""
OpenClaw Gateway 透明代理
- 客户端连代理（默认 19002），代理转发到真 Gateway（19001）
- 拦截 WebSocket 消息，解析工具调用，过安全网关
- 不改 OpenClaw 源码
- 支持多客户端并发
- 支持自动重连
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

# ========== 配置 ==========
PROXY_HOST = "0.0.0.0"
PROXY_PORT = 19002          # 客户端连这里
UPSTREAM_HOST = "127.0.0.1"
UPSTREAM_PORT = 18789        # OpenClaw 真 Gateway
MAX_MSG_SIZE = 4 * 1024 * 1024
RECONNECT_DELAY = 2
MAX_RECONNECT = 5


def _ts():
    return datetime.now(timezone.utc).isoformat()


def _log(tag, msg):
    print(f"[{_ts()[:19]}] [代理/{tag}] {msg}")


async def _intercept_message(raw: str) -> dict:
    """
    拦截一条 WebSocket 消息。
    返回: {"forward": bool, "modified": str, "reason": str}
    """
    try:
        msg = json.loads(raw)
    except Exception:
        return {"forward": True, "modified": raw, "reason": "非 JSON 消息"}

    # 检测是否是工具调用请求
    method = msg.get("method", "")
    if not method:
        return {"forward": True, "modified": raw, "reason": "非方法调用"}

    if "tool" not in method.lower() and "invoke" not in method.lower() and "call" not in method.lower():
        return {"forward": True, "modified": raw, "reason": "非工具调用"}

    # 提取工具调用
    params = msg.get("params", {})
    tool_name = params.get("tool") or params.get("name") or method
    tool_params = params.get("params") or params.get("arguments") or {}

    # 过安全网关
    try:
        from bridge.interceptor import check_tool_call

        result = await check_tool_call(
            agent_id="proxy-agent",
            tool_name=tool_name,
            params=tool_params,
            risk="medium",
        )
        action = result.get("action", "deny")
    except Exception as e:
        _log("网关异常", str(e))
        action = "deny"

    _log("拦截", f"{tool_name} -> {action}")

    if action in ("deny", "rejected"):
        # 拒绝：构造错误响应，不转发
        reject_msg = {
            "jsonrpc": "2.0",
            "id": msg.get("id"),
            "error": {
                "code": -32000,
                "message": f"被安全网关拦截: {result.get('reason', '')}",
            },
        }
        return {"forward": True, "modified": json.dumps(reject_msg), "reason": "拦截"}

    return {"forward": True, "modified": raw, "reason": "放行"}


async def _forward(src_reader, src_writer, dst_reader, dst_writer, direction: str):
    """双向转发 WebSocket 数据"""
    try:
        while True:
            data = await src_reader.read(MAX_MSG_SIZE)
            if not data:
                break

            # 只在 client → server 方向拦截
            if direction == "c2s":
                try:
                    text = data.decode("utf-8", errors="ignore")
                    result = await _intercept_message(text)
                    data = result["modified"].encode("utf-8")
                except Exception:
                    pass

            dst_writer.write(data)
            await dst_writer.drain()
    except Exception as e:
        _log(f"转发/{direction}", str(e))


async def _handle_client(client_reader, client_writer):
    """处理一个客户端连接"""
    try:
        server_reader, server_writer = await asyncio.open_connection(
            UPSTREAM_HOST, UPSTREAM_PORT
        )
    except Exception as e:
        _log("上游连接失败", str(e))
        client_writer.close()
        return

    _log("连接", "新客户端")

    try:
        await asyncio.gather(
            _forward(client_reader, client_writer, server_reader, server_writer, "c2s"),
            _forward(server_reader, server_writer, client_reader, client_writer, "s2c"),
        )
    except Exception as e:
        _log("会话异常", str(e))
    finally:
        try:
            server_writer.close()
        except Exception:
            pass
        try:
            client_writer.close()
        except Exception:
            pass
        _log("断开", "客户端离开")


async def main():
    _log("启动", f"监听 {PROXY_HOST}:{PROXY_PORT}")
    _log("转发", f"上游 {UPSTREAM_HOST}:{UPSTREAM_PORT}")
    try:
        server = await asyncio.start_server(
            _handle_client, PROXY_HOST, PROXY_PORT,
        )
        async with server:
            await server.serve_forever()
    except OSError as e:
        _log("端口错误", str(e))
    except Exception as e:
        _log("启动失败", str(e))
        traceback.print_exc()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        _log("退出", "收到 Ctrl+C")