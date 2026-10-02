"""
B 层：诚实性检查
AI 说"保证/绝对/一定能"时，自动改写为诚实表达
"""
import re

# 绝对化词 -> 诚实改写
REWRITE_MAP = {
    "一定能": "我会尽力",
    "绝对能": "目前判断是",
    "保证能": "我争取",
    "肯定会": "大概率会",
    "100%": "目前有把握",
    "百分百": "目前有把握",
    "包治": "可能有效",
    "万无一失": "目前判断风险较低",
    "绝对安全": "目前没发现明显风险",
    "绝对不会": "目前判断不太可能",
    "永远不": "在当前条件下不",
    "肯定不": "大概率不",
}

# 这些是危险信号，直接拦截，不改写
BLOCK_PATTERNS = [
    r"我保证",
    r"绝对没问题",
    r"包在我身上",
    r"肯定成功",
]


def rewrite(text: str) -> tuple:
    """
    返回 (改写后的文本, 是否触发过改写)
    """
    if not text:
        return text, False

    triggered = False

    # 先检查是否命中拦截词
    for pat in BLOCK_PATTERNS:
        if re.search(pat, text):
            return ("[该回答含不负责任的保证，已拦截]", True)

    # 再做改写
    for bad, good in REWRITE_MAP.items():
        if bad in text:
            text = text.replace(bad, good)
            triggered = True

    return text, triggered


def check(text: str) -> dict:
    """
    返回检查结果：
    {
        "ok": bool,          # 是否通过
        "rewritten": str,    # 改写后的文本
        "triggered": bool,   # 是否触发过改写/拦截
        "blocked": bool      # 是否被拦截
    }
    """
    rewritten, triggered = rewrite(text)
    blocked = rewritten.startswith("[该回答含")
    return {
        "ok": not triggered,
        "rewritten": rewritten,
        "triggered": triggered,
        "blocked": blocked,
    }


if __name__ == "__main__":
    cases = [
        "我一定能帮你删掉所有临时文件",
        "这个操作绝对安全，你放心",
        "我保证能完成任务",
        "我会尽力完成，目前判断风险较低",
        "这个方案99%有效，可以试试",
    ]

    for c in cases:
        r = check(c)
        print(f"原文: {c}")
        print(f"  -> {r['rewritten']}")
        print(f"  ok={r['ok']}  blocked={r['blocked']}\n")