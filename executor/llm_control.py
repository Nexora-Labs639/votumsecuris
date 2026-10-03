"""
推理引擎深度控制（终级版）
- 参数通过 ModelFile 写死，用 ollama create 创建自定义模型
- 每个 preset 对应一个独立模型（votum-fast / votum-balanced / votum-deep / votum-creative）
- 模型无关：base 模型可换成任何 Ollama 支持的模型
"""
import sys
import os
import re
import json
import time
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

OLLAMA_CMD = "ollama"

# 每个 preset 的推理参数
PRESETS = {
    "fast": {
        "temperature": 0.0,
        "top_p": 0.9,
        "top_k": 20,
        "num_ctx": 2048,
        "repeat_penalty": 1.0,
    },
    "balanced": {
        "temperature": 0.1,
        "top_p": 0.9,
        "top_k": 40,
        "num_ctx": 4096,
        "repeat_penalty": 1.1,
    },
    "deep": {
        "temperature": 0.3,
        "top_p": 0.95,
        "top_k": 60,
        "num_ctx": 8192,
        "repeat_penalty": 1.2,
    },
    "creative": {
        "temperature": 0.8,
        "top_p": 0.95,
        "top_k": 80,
        "num_ctx": 4096,
        "repeat_penalty": 1.0,
    },
}

# base 模型池（模型无关，可扩展）
BASE_MODELS = {
    "qwen": "qwen2.5:7b",
    "deepseek": "deepseek-r1:7b",
}
DEFAULT_BASE = "qwen"

def _run_ollama(cmd: str, timeout: int = 120, input_text: str = None) -> tuple:
    """统一执行 ollama 命令，返回 (成功, stdout, stderr)"""
    try:
        result = subprocess.run(
            cmd,
            input=input_text,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
            shell=True,
        )
        return result.returncode == 0, result.stdout or "", result.stderr or ""
    except subprocess.TimeoutExpired:
        return False, "", f"超时 (>{timeout}s)"
    except Exception as e:
        return False, "", str(e)


def _clean(raw: str) -> str:
    raw = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", raw or "")
    raw = raw.replace("\x1b", "")
    return raw.strip()


def list_custom_models() -> list:
    """列出本产品创建的自定义模型"""
    ok, out, _ = _run_ollama(f"{OLLAMA_CMD} list", timeout=30)
    if not ok:
        return []
    models = []
    for line in out.split("\n")[1:]:
        name = line.split()[0] if line.strip() else ""
        if name.startswith("votum-"):
            models.append(name)
    return models


def build_model(preset: str, base: str = DEFAULT_BASE) -> dict:
    """
    根据 preset 创建自定义模型。
    如果模型已存在，跳过。
    """
    if preset not in PRESETS:
        return {"ok": False, "error": f"未知 preset: {preset}"}
    if base not in BASE_MODELS:
        return {"ok": False, "error": f"未知 base: {base}"}

    model_name = f"votum-{preset}-{base}"
    if model_name in list_custom_models():
        return {"ok": True, "model": model_name, "created": False}

    params = PRESETS[preset]
    base_model = BASE_MODELS[base]

    modelfile_lines = [f"FROM {base_model}"]
    for k, v in params.items():
        modelfile_lines.append(f"PARAMETER {k} {v}")
    modelfile_content = "\n".join(modelfile_lines)

    in_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                          suffix=".Modelfile", delete=False) as f:
            f.write(modelfile_content)
            in_path = f.name
        cmd = f'{OLLAMA_CMD} create {model_name} -f "{in_path}"'
        ok, out, err = _run_ollama(cmd, timeout=300)
        if ok:
            return {"ok": True, "model": model_name, "created": True}
        return {"ok": False, "error": _clean(err) or _clean(out) or "create 失败"}
    finally:
        if in_path:
            try:
                os.unlink(in_path)
            except Exception:
                pass
                
def run_llm(prompt: str, system: str = "", preset: str = "balanced",
            base: str = DEFAULT_BASE, timeout: int = 300) -> dict:
    """
    执行一次推理。
    返回: {ok, text, elapsed, model, preset, base, error}
    """
    # 1. 确保模型已创建
    build = build_model(preset, base)
    if not build.get("ok"):
        return {
            "ok": False, "text": "", "elapsed": 0.0,
            "model": "", "preset": preset, "base": base,
            "error": f"模型创建失败: {build.get('error', '')}",
        }
    model_name = build["model"]

    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    # 2. 用文件管道传 prompt，避免命令行转义问题
    in_path = None
    start = time.time()
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                          suffix=".txt", delete=False) as f:
            f.write(full_prompt)
            in_path = f.name
        cmd = f'{OLLAMA_CMD} run {model_name} < "{in_path}"'
        ok, out, err = _run_ollama(cmd, timeout=timeout)
        elapsed = round(time.time() - start, 3)

        if not ok:
            return {
                "ok": False, "text": "", "elapsed": elapsed,
                "model": model_name, "preset": preset, "base": base,
                "error": _clean(err) or "run 失败",
            }
        return {
            "ok": True, "text": _clean(out), "elapsed": elapsed,
            "model": model_name, "preset": preset, "base": base,
            "error": "",
        }
    finally:
        if in_path:
            try:
                os.unlink(in_path)
            except Exception:
                pass


def cleanup_custom_models() -> int:
    """删除所有 votum- 自定义模型（慎用，只在重装时用）"""
    count = 0
    for m in list_custom_models():
        ok, _, _ = _run_ollama(f"{OLLAMA_CMD} rm {m}", timeout=60)
        if ok:
            count += 1
    return count
    
def init_default_models() -> dict:
    """初始化默认模型（首次安装时调用）"""
    results = {}
    for preset in PRESETS:
        r = build_model(preset, DEFAULT_BASE)
        results[preset] = r
    return results


if __name__ == "__main__":
    print("=== 初始化默认模型 ===")
    init_result = init_default_models()
    for preset, r in init_result.items():
        status = "已存在" if r.get("created") is False else ("新建" if r.get("ok") else "失败")
        print(f"  votum-{preset}-{DEFAULT_BASE}: {status}")

    print("\n=== 测试 1：fast 预设 ===")
    r = run_llm("用一句话解释 AI Agent", preset="fast")
    print(f"  耗时: {r['elapsed']}秒 | 模型: {r['model']} | ok={r['ok']}")
    print(f"  输出: {r['text'][:120]}")
    if r['error']:
        print(f"  错误: {r['error']}")

    print("\n=== 测试 2：deep 预设 ===")
    r = run_llm("列举 3 个 AI Agent 的安全风险", preset="deep")
    print(f"  耗时: {r['elapsed']}秒 | ok={r['ok']}")
    print(f"  输出: {r['text'][:200]}")
    if r['error']:
        print(f"  错误: {r['error']}")