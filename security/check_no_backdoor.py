"""
后门检测
- 静态扫描所有 Python 文件
- 检查：外网请求、反向 shell、动态执行、隐藏定时任务
- 参考：苹果「无远程控制通道」原则
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

# 扫描排除的目录
EXCLUDE_DIRS = {".git", "__pycache__", "build", "dist", "node_modules", ".venv", "venv", "backups"}

# 扫描时排除的文件（扫描器自己 + 测试文件）
EXCLUDE_FILES = {
    "check_no_backdoor.py",
    "tool_result_scan.py",
    "test_client.py",
    "test_interceptor.py",
}

# 后门特征（正则）
BACKDOOR_PATTERNS = [
    # 外网请求
    (r"requests\.(post|put|get)\(['\"]https?://(?!127\.0\.0\.1|localhost)", "外网 HTTP 请求"),
    (r"urllib\.request\.urlopen\(['\"]https?://(?!127\.0\.0\.1|localhost)", "外网 urllib 请求"),
    (r"socket\.connect\(\(['\"](?!127\.0\.0\.1|localhost)", "外网 socket 连接"),
    # 反向 shell
    (r"subprocess\.(run|call|Popen)\(.*(nc|netcat|bash\s+-i|/dev/tcp)", "反向 shell"),
    (r"os\.system\(.*(nc|netcat|bash\s+-i|/dev/tcp)", "反向 shell"),
    # 动态执行
    (r"\beval\s*\(", "动态执行 eval"),
    (r"\bexec\s*\(", "动态执行 exec"),
    (r"__import__\s*\(\s*['\"](?!os|sys|json|sqlite3|hashlib|hmac|re|time|datetime|pathlib|subprocess|asyncio|threading|collections|typing|uuid|math|random|shutil|tempfile|csv|sqlite)", "动态导入可疑模块"),
    # 隐藏定时任务
    (r"crontab", "crontab 操作"),
    (r"schtasks", "Windows 计划任务"),
    (r"launchctl", "macOS 定时任务"),
    # 敏感数据外发
    (r"telegram.*bot.*token", "Telegram bot 外发"),
    (r"webhook", "Webhook 外发"),
    (r"pastebin", "Pastebin 外发"),
]

# 允许的白名单（本机内网通信）
WHITELIST = [
    r"127\.0\.0\.1",
    r"localhost",
    r"0\.0\.0\.0",
    r"192\.168\.",
    r"10\.0\.",
    r"172\.1[6-9]\.",
    r"172\.2[0-9]\.",
    r"172\.3[0-1]\.",
]


def is_whitelisted(line: str) -> bool:
    """判断这一行是否是内网地址"""
    for w in WHITELIST:
        if re.search(w, line):
            return True
    return False


def scan_file(path: Path) -> list:
    """扫描单个文件，返回问题列表"""
    issues = []
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return issues

    lines = content.split("\n")
    for i, line in enumerate(lines, 1):
        # 跳过注释行
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        # 跳过白名单
        if is_whitelisted(line):
            continue

        for pattern, desc in BACKDOOR_PATTERNS:
            if re.search(pattern, line):
                issues.append({
                    "file": str(path.relative_to(ROOT)),
                    "line": i,
                    "code": line.strip()[:100],
                    "issue": desc,
                })
    return issues


def scan_all() -> dict:
    """扫描整个项目"""
    all_issues = []
    files_scanned = 0

    for p in ROOT.rglob("*.py"):
        if p.name in EXCLUDE_FILES:
            continue
        # 跳过排除目录
        if any(part in EXCLUDE_DIRS for part in p.parts):
            continue
        files_scanned += 1
        all_issues.extend(scan_file(p))

    return {
        "files_scanned": files_scanned,
        "issues_count": len(all_issues),
        "issues": all_issues,
    }


if __name__ == "__main__":
    print("=== 后门检测 ===")
    r = scan_all()
    print(f"扫描文件: {r['files_scanned']}")
    print(f"发现问题: {r['issues_count']}")

    if r["issues"]:
        print("\n=== 问题列表 ===")
        for issue in r["issues"]:
            print(f"  [{issue['file']}:{issue['line']}] {issue['issue']}")
            print(f"    {issue['code']}")
    else:
        print("\n[通过] 未发现后门特征")