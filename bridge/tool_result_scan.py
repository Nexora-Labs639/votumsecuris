"""
工具结果扫描
- 检查工具返回的内容是否被污染
- 参考：Lionguard tool-result validation
"""
import re

# 工具结果里的危险特征
DANGEROUS_PATTERNS = [
    r"<script[^>]*>",
    r"javascript:",
    r"onerror\s*=",
    r"onload\s*=",
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__\s*\(",
    r"subprocess\.(run|call|Popen)",
    r"os\.system\s*\(",
    r"rm\s+-rf\s+/",
    r"curl\s+.*\|\s*(ba)?sh",
    r"wget\s+.*\|\s*(ba)?sh",
]

# 敏感数据特征
SENSITIVE_PATTERNS = [
    r"AKIA[0-9A-Z]{16}",
    r"sk-[a-zA-Z0-9]{32,}",
    r"ghp_[a-zA-Z0-9]{36}",
    r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----",
    r"password\s*[=:]\s*['\"][^'\"]{6,}['\"]",
    r"\b\d{16}\b",
]

_COMPILED_DANGEROUS = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]
_COMPILED_SENSITIVE = [re.compile(p) for p in SENSITIVE_PATTERNS]


def scan(result: str) -> dict:
    """
    扫描工具结果。
    返回: {"safe": bool, "reason": str, "matched": str, "level": str}
    level: info / warn / critical
    """
    if not result or not isinstance(result, str):
        return {"safe": True, "reason": "", "matched": "", "level": "info"}

    for pat in _COMPILED_SENSITIVE:
        m = pat.search(result)
        if m:
            return {
                "safe": False,
                "reason": "工具结果包含敏感数据",
                "matched": m.group(0)[:50],
                "level": "critical",
            }

    for pat in _COMPILED_DANGEROUS:
        m = pat.search(result)
        if m:
            return {
                "safe": False,
                "reason": "工具结果包含危险代码",
                "matched": m.group(0)[:80],
                "level": "warn",
            }

    return {"safe": True, "reason": "", "matched": "", "level": "info"}


if __name__ == "__main__":
    cases = [
        "文件已成功删除，共 3 个",
        "<script>alert('xss')</script>",
        "AWS_KEY=AKIAIOSFODNN7EXAMPLE",
        "exec('import os; os.system(\"rm -rf /\")')",
        "用户密码: password='secret123'",
        "正常的工具返回结果",
    ]
    for c in cases:
        r = scan(c)
        status = "✓ 安全" if r["safe"] else f"✗ {r['level']}: {r['reason']}"
        print(f"{status} | 内容: {c[:50]}")