"""
同步客户端：拉取/推送其他设备的记忆
"""
import sys
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from memory.store import all_memories, remember


def _http_get(url: str, timeout: int = 5) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def _http_post(url: str, data: dict, timeout: int = 5) -> dict:
    try:
        body = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(
            url, data=body,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def ping(ip: str, port: int = 8520) -> dict:
    return _http_get(f"http://{ip}:{port}/ping")


def pull_memory(ip: str, agent_id: str, port: int = 8520) -> dict:
    """从远程设备拉取记忆，合并到本地"""
    data = _http_get(f"http://{ip}:{port}/memory?agent={agent_id}")
    if "error" in data:
        return data
    remote = data.get("memories", {})
    for k, v in remote.items():
        remember(agent_id, k, v)
    return {"ok": True, "pulled": len(remote), "from": ip}


def push_memory(ip: str, agent_id: str, port: int = 8520) -> dict:
    """把本地记忆推给远程设备"""
    local = all_memories(agent_id)
    return _http_post(
        f"http://{ip}:{port}/memory",
        {"agent": agent_id, "memories": local}
    )


def sync_both(ip: str, agent_id: str = "agent-A", port: int = 8520) -> dict:
    """双向同步"""
    pull = pull_memory(ip, agent_id, port)
    push = push_memory(ip, agent_id, port)
    return {"pull": pull, "push": push}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--ip", required=True, help="对方设备 IP")
    parser.add_argument("--agent", default="agent-A")
    parser.add_argument("--port", type=int, default=8520)
    parser.add_argument("--mode", choices=["ping", "pull", "push", "sync"], default="ping")
    args = parser.parse_args()

    if args.mode == "ping":
        print(ping(args.ip, args.port))
    elif args.mode == "pull":
        print(pull_memory(args.ip, args.agent, args.port))
    elif args.mode == "push":
        print(push_memory(args.ip, args.agent, args.port))
    elif args.mode == "sync":
        print(sync_both(args.ip, args.agent, args.port))