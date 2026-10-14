"""
Inno Setup 编译脚本
- 检测 Inno Setup 是否装
- 自动编译 setup.iss
- 输出 VotumSecuris_Setup.exe
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ISS = ROOT / "installer" / "setup.iss"

# Inno Setup 常见安装路径
ISCC_PATHS = [
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
]


def find_iscc():
    for p in ISCC_PATHS:
        if Path(p).exists():
            return p
    return None


def build():
    iscc = find_iscc()
    if not iscc:
        print("[错误] 找不到 Inno Setup 编译器 ISCC.exe")
        print("请到 https://jrsoftware.org/isdl.php 下载安装")
        return False

    print(f"[OK] 找到编译器: {iscc}")
    r = subprocess.run([iscc, str(ISS)], cwd=str(ROOT))
    if r.returncode == 0:
        print("[OK] 安装包已生成: installer/output/VotumSecuris_Setup.exe")
        return True
    print("[失败] 编译失败")
    return False


if __name__ == "__main__":
    sys.exit(0 if build() else 1)