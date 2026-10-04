"""
B 层：诚实性检查（加固版）
AI 说"保证/绝对/一定能"时，自动改写为诚实表达
"""
import re

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

BLOCK_PATTERNS = [
    r"我保证",
    r"绝对没问题",
    r"包在我身上",
    r"肯定成功",
]

MAX_TEXT_LEN = 100_000


def _normalize(text):
    """统一输入，返回字符串或 None"""
    if text is None:
        return None
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:
            return None
    if len(text) > MAX_TEXT_LEN:
        text = text[:MAX_TEXT_LEN]
    return text


def rewrite(text) -> tuple:
    """
    返回 (改写后的文本, 是否触发过改写)
    任何异常都不会抛出，保证返回元组
    """
    text = _normalize(text)
    if text is None:
        return "", False
    if not text:
        return text, False

    triggered = False

    for pat in BLOCK_PATTERNS:
        try:
            if re.search(pat, text):
                return ("[该回答含不负责任的保证，已拦截]", True)
        except Exception:
            continue

    for bad, good in REWRITE_MAP.items():
        try:
            if bad in text:
                text = text.replace(bad, good)
                triggered = True
        except Exception:
            continue

    return text, triggered


def check(text) -> dict:
    """
    返回检查结果：
    {
        "ok": bool,
        "rewritten": str,
        "triggered": bool,
        "blocked": bool
    }
    任何输入都保证返回上述 4 字段，不抛异常
    """
    try:
        text = _normalize(text)
        if text is None or not text.strip():
            return {
                "ok": True,
                "rewritten": text or "",
                "triggered": False,
                "blocked": False,
            }

        rewritten, triggered = rewrite(text)
        if not isinstance(rewritten, str):
            rewritten = str(rewritten)
        blocked = rewritten.startswith("[该回答含")

        return {
            "ok": not triggered,
            "rewritten": rewritten,
            "triggered": triggered,
            "blocked": blocked,
        }
    except Exception as e:
        return {
            "ok": False,
            "rewritten": "",
            "triggered": False,
            "blocked": False,
            "error": str(e),
        }


if __name__ == "__main__":
    cases = [
        "我一定能帮你删掉所有临时文件",
        "这个操作绝对安全，你放心",
        "我保证能完成任务",
        "我会尽力完成，目前判断风险较低",
        "这个方案99%有效，可以试试",
        None,
        "",
        "   ",
        12345,
        ["list", "input"],
    ]

    for c in cases:
        r = check(c)
        print(f"输入: {repr(c)}")
        print(f"  -> {r['rewritten'][:50]}")
        print(f"  ok={r['ok']}  triggered={r['triggered']}  blocked={r['blocked']}\n")