"""
完整性校验器
- 启动时校验所有核心文件
- 任何文件被改，立即拒绝启动
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "integrity" / "manifest.json"


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify() -> dict:
    if not MANIFEST.exists():
        return {"ok": False, "reason": "manifest.json 不存在"}

    with open(MANIFEST, encoding="utf-8") as f:
        manifest = json.load(f)

    tampered = []
    missing = []

    for rel, expected_hash in manifest["files"].items():
        path = ROOT / rel
        if not path.exists():
            missing.append(rel)
            continue
        actual = file_hash(path)
        if actual != expected_hash:
            tampered.append(rel)

    if tampered:
        return {
            "ok": False,
            "reason": f"检测到 {len(tampered)} 个文件被篡改",
            "tampered": tampered,
        }
    if missing:
        return {
            "ok": False,
            "reason": f"检测到 {len(missing)} 个文件缺失",
            "missing": missing,
        }
    return {"ok": True, "reason": "完整性校验通过", "files": len(manifest["files"])}


if __name__ == "__main__":
    r = verify()
    print(json.dumps(r, ensure_ascii=False, indent=2))
    if not r["ok"]:
        sys.exit(1)