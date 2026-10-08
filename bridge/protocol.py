"""
消息协议定义
所有手机 ↔ PC 的消息都用这个格式
"""
import json
from datetime import datetime, timezone


# ========== 消息类型 ==========
# 手机 → PC
MSG_NEW_TASK = "new_task"           # 发新任务
MSG_APPROVE = "approve"             # 审批通过
MSG_REJECT = "reject"               # 审批拒绝
MSG_QUERY_TASKS = "query_tasks"     # 查任务列表
MSG_PING = "ping"                   # 心跳

# PC → 手机
MSG_TASK_LIST = "task_list"         # 任务列表
MSG_TASK_UPDATE = "task_update"     # 任务状态更新
MSG_APPROVAL_REQUEST = "approval_request"  # 审批请求
MSG_PROGRESS = "progress"           # 进度汇报
MSG_LOG = "log"                     # 日志
MSG_PONG = "pong"                   # 心跳响应
MSG_ERROR = "error"                 # 错误


def make_msg(msg_type: str, payload: dict = None) -> str:
    """构造消息（JSON 字符串）"""
    return json.dumps({
        "type": msg_type,
        "ts": datetime.now(timezone.utc).isoformat(),
        "payload": payload or {},
    }, ensure_ascii=False)


def parse_msg(raw: str) -> dict:
    """解析消息，异常返回 None"""
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        if "type" not in data:
            return None
        return data
    except Exception:
        return None


def make_task(task_id: str, content: str, status: str = "pending") -> dict:
    """构造任务对象"""
    return {
        "id": task_id,
        "content": content,
        "status": status,   # pending / running / done / failed / need_approval
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    print(make_msg(MSG_NEW_TASK, {"content": "整理 D 盘"}))
    print(parse_msg('{"type": "ping", "payload": {}}'))