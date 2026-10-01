"""
多智能体并发
每个 Agent 独立进程，共享 SQLite 记忆和消息
"""
import sys
import time
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import threading

from memory.store import (
    init_db, remember, recall, all_memories,
    send_message, read_messages
)


def agent_worker(agent_id: str, task: str, rounds: int = 3):
    """一个 Agent 的工作循环"""
    print(f"[{agent_id}] 启动，任务：{task}")
    remember(agent_id, "task", task)

    for i in range(1, rounds + 1):
        # 干活
        print(f"[{agent_id}] 第 {i} 步执行中...")
        remember(agent_id, "progress", i)
        time.sleep(0.5)

        # 发消息给另一个 Agent
        other = "agent-B" if agent_id == "agent-A" else "agent-A"
        send_message(agent_id, other, f"我完成第 {i} 步了")

        # 收消息
        msgs = read_messages(agent_id)
        for m in msgs:
            print(f"[{agent_id}] 收到来自 {m['from']} 的消息: {m['content']}")

    print(f"[{agent_id}] 任务完成，记忆：{all_memories(agent_id)}")


if __name__ == "__main__":
    init_db()
    print("=== 多智能体并发测试 ===\n")

    t1 = threading.Thread(target=agent_worker, args=("agent-A", "整理文件"))
    t2 = threading.Thread(target=agent_worker, args=("agent-B", "审核日志"))

    t1.start()
    t2.start()

    t1.join()
    t2.join()

    print("\n=== 全部完成 ===")
    print("agent-A 记忆:", all_memories("agent-A"))
    print("agent-B 记忆:", all_memories("agent-B"))