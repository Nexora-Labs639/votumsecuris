"""
策略引擎（跨平台）
判断删除操作的安全性，返回结构化判决
"""
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent

# ========== 缓存/垃圾文件（可自动删） ==========
JUNK_SUFFIXES = {
    ".tmp", ".temp", ".cache", ".bak", ".swp", ".swo", ".log",
    ".pyc", ".pyo", ".pyd", ".ds_store",
}
JUNK_FILENAMES = {"thumbs.db", ".ds_store", "desktop.ini"}
JUNK_DIR_NAMES = {
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".gradle", ".idea", ".vscode", "node_modules",
}
JUNK_REGEX = [
    re.compile(r"~\$.*\.(docx|xlsx|pptx|doc|xls|ppt)$", re.IGNORECASE),
    re.compile(r".*\.tmp\.\d+$", re.IGNORECASE),
]

# ========== 系统禁删目录（跨平台） ==========
FORBIDDEN_DIRS = [
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
    "C:\\ProgramData",
    "/System",
    "/Library",
    "/usr",
    "/etc",
    "/bin",
    "/sbin",
    "/var",
]

# ========== 重要文件（必须审批 + 强烈警告） ==========
IMPORTANT_SUFFIXES = {
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".pdf",
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp",
    ".mp4", ".mov", ".avi", ".mkv", ".mp3", ".wav",
    ".zip", ".rar", ".7z", ".tar", ".gz",
    ".py", ".js", ".ts", ".java", ".cpp", ".c", ".h", ".go", ".rs",
    ".db", ".sqlite", ".sql",
    ".key", ".pem", ".crt", ".p12",
}

def _normalize_path(path: str) -> str:
    """跨平台路径规范化"""
    if not path:
        return ""
    p = path.replace("\\", "/")
    p = re.sub(r"/+", "/", p)
    return p


def _has_dir(path: str, dir_name: str) -> bool:
    """检查路径中是否包含某目录名（跨平台）"""
    return dir_name.lower() in _normalize_path(path).lower()


def _suffix_of(path: str) -> str:
    """取文件后缀，小写"""
    name = _normalize_path(path).split("/")[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].lower()


def _filename_of(path: str) -> str:
    return _normalize_path(path).split("/")[-1].lower()


def _is_junk(path: str) -> bool:
    """是不是缓存/垃圾文件"""
    if not path:
        return False
    for d in JUNK_DIR_NAMES:
        if _has_dir(path, d):
            return True
    if _filename_of(path) in JUNK_FILENAMES:
        return True
    if _suffix_of(path) in JUNK_SUFFIXES:
        return True
    for pat in JUNK_REGEX:
        if pat.match(_normalize_path(path)):
            return True
    return False


def _is_forbidden(path: str) -> tuple:
    """是不是系统禁删目录。返回 (bool, 匹配到的目录)"""
    if not path:
        return False, ""
    np = _normalize_path(path).lower()
    for d in FORBIDDEN_DIRS:
        dn = _normalize_path(d).lower()
        if np == dn or np.startswith(dn + "/"):
            return True, d
    return False, ""


def _is_important(path: str) -> bool:
    """是不是重要文件（文档/图片/代码/数据库/密钥）"""
    return _suffix_of(path) in IMPORTANT_SUFFIXES
    
def load_rules():
    import yaml
    p = ROOT / "policy" / "rules.yaml"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("rules", [])


def evaluate(tool_name: str, params: dict, risk: str, undo=None) -> dict:
    """
    返回: {"action": "allow|deny|require_approval", "reason": str, "severity": str}
    severity: info / warn / critical
    """
    path = params.get("path", "") or ""
    command = params.get("command", "") or ""

    # ========== 硬规则 1：系统目录禁删 ==========
    forbidden, matched = _is_forbidden(path)
    if path and forbidden:
        return {
            "action": "deny",
            "reason": f"禁止操作系统目录: {matched}",
            "severity": "critical",
        }

    # ========== 硬规则 2：删除文件分级 ==========
    if tool_name in ("delete_file", "write_file"):
        if path and _is_junk(path):
            return {
                "action": "allow",
                "reason": f"缓存/垃圾文件，自动清理",
                "severity": "info",
            }
        if path and _is_important(path):
            return {
                "action": "require_approval",
                "reason": f"重要文件，必须人工确认后才能删除",
                "severity": "critical",
            }
        return {
            "action": "require_approval",
            "reason": f"非缓存文件，删除前必须人工确认",
            "severity": "warn",
        }

    # ========== 硬规则 3：危险命令 ==========
    if tool_name == "run_shell":
        dangerous = ["rm -rf", "format ", "del /f", "rmdir /s", "mkfs", ":(){:|:&};:"]
        for d in dangerous:
            if d in command.lower():
                return {
                    "action": "deny",
                    "reason": f"危险命令，直接拒绝: {d}",
                    "severity": "critical",
                }

    # ========== 规则 4：高风险 ==========
    if risk == "high":
        return {
            "action": "require_approval",
            "reason": "高风险操作，需人工审批",
            "severity": "warn",
        }

    # ========== 规则 5：不可撤销 ==========
    if undo is None and risk != "low":
        return {
            "action": "require_approval",
            "reason": "不可撤销操作，强制审批",
            "severity": "warn",
        }

    return {"action": "allow", "reason": "默认放行", "severity": "info"}
    
if __name__ == "__main__":
    cases = [
        ("delete_file", {"path": "D:/project/tmp/abc.tmp"}, "medium", None),
        ("delete_file", {"path": "D:/project/__pycache__/x.pyc"}, "medium", None),
        ("delete_file", {"path": "D:/project/important.docx"}, "medium", None),
        ("delete_file", {"path": "D:/project/家庭照片.jpg"}, "medium", None),
        ("delete_file", {"path": "D:/project/note.txt"}, "medium", None),
        ("delete_file", {"path": "C:\\Windows\\System32\\x.dll"}, "medium", None),
        ("write_file",  {"path": "D:/project/note.txt", "content": "hi"}, "medium", "delete_file"),
        ("run_shell",   {"command": "rm -rf /"}, "high", None),
        ("run_shell",   {"command": "echo hello"}, "high", None),
    ]
    for name, params, risk, undo in cases:
        r = evaluate(name, params, risk, undo)
        print(f"{name:12s} {str(params)[:55]:55s} -> {r['action']:18s} [{r['severity']}] {r['reason']}")
    