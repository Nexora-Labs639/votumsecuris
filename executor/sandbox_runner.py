import subprocess
import sys
from pathlib import Path

def run_sandboxed(cmd: str, timeout_ms: int = 5000, mem_limit_mb: int = 256):
    """
    沙箱执行器（Python 版，先用这个占位，等 C++ 版好了替换）
    返回: {"stdout": str, "stderr": str, "exit_code": int, "status": str}
    status: ok / timeout / error
    """
    try:
        p = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout_ms / 1000.0
        )
        return {
            "stdout": p.stdout,
            "stderr": p.stderr,
            "exit_code": p.returncode,
            "status": "ok" if p.returncode == 0 else "error"
        }
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "TIMEOUT", "exit_code": -1, "status": "timeout"}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "exit_code": -1, "status": "error"}


if __name__ == "__main__":
    print(run_sandboxed("echo hello"))
    print(run_sandboxed("ping 127.0.0.1 -n 10", timeout_ms=2000))  # 应超时