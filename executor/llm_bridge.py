"""
LLM Bridge —— 最终版
用 ollama run --format json 强制输出干净 JSON
不再依赖文本清理，不再有 ANSI 污染
"""
import sys
from pathlib import Path
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import json
import re
import subprocess
import os

PLANNER_MODEL = "qwen2.5:7b"
REASONER_MODEL = "deepseek-r1:7b"


def ask_llm(prompt, system="", model=None, timeout=300):
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"

    cmd = f'ollama run {model or PLANNER_MODEL} --format json'
    try:
        r = subprocess.run(
            cmd,
            input=full_prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=timeout,
            shell=True,
            env=env,
        )
        return r.stdout
    except subprocess.TimeoutExpired:
        return "[LLM_ERROR] 超时"
    except Exception as e:
        return f"[LLM_ERROR] {e}"


def _extract_json(text):
    """过滤掉所有非可见字符，然后提取 JSON 数组"""
    cleaned = []
    for ch in text:
        o = ord(ch)
        if o in (0x0a, 0x0d, 0x09):
            cleaned.append(ch)
        elif 0x20 <= o <= 0x7e:
            cleaned.append(ch)
        elif 0x4e00 <= o <= 0x9fff:
            cleaned.append(ch)
    text = "".join(cleaned)
    text = re.sub(r" thinking.*?", "", text, flags=re.DOTALL)

    # 尝试整体解析
    for m in re.finditer(r"\[", text):
        start = m.start()
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "[":
                depth += 1
            elif text[i] == "]":
                depth -= 1
                if depth == 0:
                    candidate = text[start:i+1]
                    try:
                        data = json.loads(candidate)
                        if isinstance(data, list) and data:
                            return data
                    except Exception:
                        pass
                    break
    return []


def plan_steps(goal, idle_prompt, debug=False):
    system = f"""你是 AI 智能体。{idle_prompt}

用户给你目标，你只输出 JSON 数组。
可用工具：
- read_file: params = {{"path": "路径"}}
- write_file: params = {{"path": "路径", "content": "内容"}}
- delete_file: params = {{"path": "路径"}}
- run_shell: params = {{"command": "命令"}}

步骤不超过 5 步。"""

    raw = ask_llm(f"目标：{goal}", system=system, model=PLANNER_MODEL)
    if debug:
        print("===== RAW OUTPUT =====")
        print(raw)
        print("===== END RAW =====\n")
    return _extract_json(raw)


if __name__ == "__main__":
    from policy.idle_code import get_idle_prompt
    idle = get_idle_prompt()
    goal = "在 D:\\votumsecuris\\test_out\\ 下创建 hello.txt 写入 hello world，然后读取它确认内容"
    print(f"[目标] {goal}\n")
    steps = plan_steps(goal, idle, debug=True)
    print(f"[AI 规划出 {len(steps)} 步]")
    for i, s in enumerate(steps, 1):
        print(f"  {i}. {s}")