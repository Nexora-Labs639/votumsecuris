"""
Windows exe 打包脚本
- 把 Python 内核打包成单个 exe
- 输出到 dist/VotumSecuris.exe
"""
import sys
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent


def build():
    cmd = [
        "pyinstaller",
        "--onefile",
        "--name", "VotumSecuris",
        "--clean",
        "--noconfirm",
        # 主入口
        str(ROOT / "loader.py"),
        # 数据文件（打包进 exe）
        "--add-data", f"{ROOT / 'registry' / 'tools.yaml'};registry",
        "--add-data", f"{ROOT / 'policy' / 'rules.yaml'};policy",
        "--add-data", f"{ROOT / 'audit' / 'init.sql'};audit",
        "--add-data", f"{ROOT / 'memory' / 'init.sql'};memory",
        "--add-data", f"{ROOT / 'knowledge' / 'README.md'};knowledge",
        # 隐藏导入
        "--hidden-import", "yaml",
        "--hidden-import", "sqlite3",
        "--hidden-import", "memory.rag",
        "--hidden-import", "memory.version",
        "--hidden-import", "memory.perf_log",
        "--hidden-import", "policy.engine",
        "--hidden-import", "policy.honesty",
        "--hidden-import", "policy.idle_code",
        "--hidden-import", "executor.llm_control",
        "--hidden-import", "executor.safe_delete",
        "--hidden-import", "executor.policy_bridge",
        "--hidden-import", "sync.server",
        "--hidden-import", "sync.client",
        "--hidden-import", "identity.agent_id",
        "--hidden-import", "identity.permission",
        "--hidden-import", "identity.audit",
    ]

    print("=== 开始打包 ===")
    print(" ".join(cmd))
    print()

    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode == 0:
        print("\n[成功] exe 已生成: dist/VotumSecuris.exe")
    else:
        print(f"\n[失败] 退出码: {r.returncode}")


if __name__ == "__main__":
    build()