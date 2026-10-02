"""
安全删除执行器
- 删除前自动备份到回收站目录（.votumsecuris_trash）
- 写审计日志
- 支持从回收站恢复
"""
import sys
import shutil
import hashlib
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from audit.writer import log

TRASH_DIR = ROOT / ".votumsecuris_trash"


def _ensure_trash():
    TRASH_DIR.mkdir(exist_ok=True)


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_delete(agent_id: str, path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {"ok": False, "msg": f"文件不存在: {path}", "trash_path": "", "hash": ""}

    _ensure_trash()
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = f"{ts}_{p.name}"
    trash_path = TRASH_DIR / safe_name

    try:
        if p.is_dir():
            shutil.copytree(p, trash_path)
        else:
            shutil.copy2(p, trash_path)
    except Exception as e:
        return {"ok": False, "msg": f"备份失败: {e}", "trash_path": "", "hash": ""}

    try:
        h = _file_hash(trash_path) if trash_path.is_file() else ""
    except Exception as e:
        return {"ok": False, "msg": f"备份校验失败: {e}", "trash_path": str(trash_path), "hash": ""}

    try:
        if p.is_dir():
            shutil.rmtree(p)
        else:
            p.unlink()
    except Exception as e:
        return {"ok": False, "msg": f"删除失败: {e}", "trash_path": str(trash_path), "hash": h}

    try:
        log(agent_id, "safe_delete", {"path": path}, f"备份到 {trash_path}", "ok")
    except Exception:
        pass

    return {"ok": True, "msg": "已删除（可从回收站恢复）", "trash_path": str(trash_path), "hash": h}


def restore(trash_path: str, target_path: str) -> dict:
    src = Path(trash_path)
    dst = Path(target_path)
    if not src.exists():
        return {"ok": False, "msg": f"回收站文件不存在: {trash_path}"}
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return {"ok": True, "msg": f"已恢复到 {target_path}"}
    except Exception as e:
        return {"ok": False, "msg": f"恢复失败: {e}"}


def list_trash() -> list:
    _ensure_trash()
    return [
        {"name": f.name, "path": str(f), "size": f.stat().st_size if f.is_file() else 0}
        for f in sorted(TRASH_DIR.iterdir(), reverse=True)
    ]


if __name__ == "__main__":
    test_file = ROOT / "test_trash_demo.txt"
    test_file.write_text("hello votumsecuris", encoding="utf-8")
    print(f"创建测试文件: {test_file}")

    r = safe_delete("agent-test", str(test_file))
    print(f"删除结果: {r}")

    print("\n回收站内容:")
    for item in list_trash():
        print(f"  {item}")

    if r["ok"]:
        rr = restore(r["trash_path"], str(test_file))
        print(f"\n恢复结果: {rr}")
        if test_file.exists():
            print(f"恢复内容: {test_file.read_text(encoding='utf-8')}")
            test_file.unlink()
            