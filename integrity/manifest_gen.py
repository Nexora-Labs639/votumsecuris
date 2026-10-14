"""
黄金值清单生成器
- 扫描核心文件，计算 SHA256
- 输出 manifest.json
"""
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
MANIFEST = ROOT / "integrity" / "manifest.json"

# 需要保护的核心目录
PROTECTED_DIRS = ["policy", "executor", "bridge", "audit", "memory", "identity"]
PROTECTED_FILES = ["loader.py"]


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate():
    manifest = {
        "version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": {},
    }

    for d in PROTECTED_DIRS:
        dir_path = ROOT / d
        if not dir_path.exists():
            continue
        for f in dir_path.rglob("*.py"):
            if "__pycache__" in str(f):
                continue
            rel = str(f.relative_to(ROOT))
            manifest["files"][rel] = file_hash(f)

    for f in PROTECTED_FILES:
        path = ROOT / f
        if path.exists():
            manifest["files"][f] = file_hash(path)

    MANIFEST.parent.mkdir(exist_ok=True)
    with open(MANIFEST, "w", encoding="utf-8") as fp:
        json.dump(manifest, fp, ensure_ascii=False, indent=2)

    print(f"[OK] 已生成 {MANIFEST}")
    print(f"[OK] 保护文件数: {len(manifest['files'])}")


if __name__ == "__main__":
    generate()