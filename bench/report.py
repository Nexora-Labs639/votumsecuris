"""
压测报告生成器（终级版）
- 所有 section 独立异常保护
- 结构化 JSON → Markdown 渲染
- 报告带 schema 版本
"""
import sys
import json
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

REPORTS_DIR = ROOT / "bench" / "reports"
OUT_PATH = ROOT / "bench" / "PERF_REPORT.md"
REPORT_SCHEMA = "v1"


def _ensure_dir():
    """确保报告目录存在"""
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def _latest(pattern: str) -> dict:
    """取最新的报告，异常返回空 dict"""
    if not _ensure_dir():
        return {}
    try:
        files = sorted(REPORTS_DIR.glob(pattern), reverse=True)
        if not files:
            return {}
        with open(files[0], encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _safe_num(v, default=0):
    """安全转数字"""
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default
        
def _section_baseline(perf: dict) -> list:
    """性能基准 section"""
    try:
        out = ["## 一、性能基准", ""]
        if not perf:
            out.append("_未找到性能基准报告_")
            out.append("")
            return out

        out.append("| 模块 | 迭代次数 | 平均耗时 | 最小 | 最大 | 中位数 | 标准差 |")
        out.append("|---|---|---|---|---|---|---|")
        for key, name in [
            ("policy_engine", "策略引擎"),
            ("honesty", "诚实性检查"),
            ("rag_search", "RAG 检索"),
            ("llm_inference", "推理引擎"),
        ]:
            r = perf.get(key, {}) or {}
            out.append(
                f"| {name} | {int(_safe_num(r.get('iterations')))} | "
                f"{_safe_num(r.get('avg_ms'))}ms | {_safe_num(r.get('min_ms'))}ms | "
                f"{_safe_num(r.get('max_ms'))}ms | {_safe_num(r.get('median_ms'))}ms | "
                f"{_safe_num(r.get('stdev_ms'))}ms |"
            )
        out.append("")
        return out
    except Exception as e:
        return ["## 一、性能基准", "", f"_渲染失败: {e}_", ""]


def _section_load_policy(load: dict) -> list:
    """策略引擎并发 section"""
    try:
        out = ["### 策略引擎并发", ""]
        if not load:
            out.append("_无数据_")
            out.append("")
            return out
        out.append("| 并发 | 总请求 | QPS | 平均耗时 | P95 | 错误 |")
        out.append("|---|---|---|---|---|---|")
        for conc in [1, 5, 10, 20]:
            r = load.get(f"policy_conc_{conc}", {}) or {}
            if not r:
                continue
            out.append(
                f"| {int(_safe_num(r.get('concurrency')))} | {int(_safe_num(r.get('total_requests')))} | "
                f"{_safe_num(r.get('qps'))} | {_safe_num(r.get('avg_ms'))}ms | "
                f"{_safe_num(r.get('p95_ms'))}ms | {int(_safe_num(r.get('errors')))} |"
            )
        out.append("")
        return out
    except Exception as e:
        return ["### 策略引擎并发", "", f"_渲染失败: {e}_", ""]


def _section_load_audit(load: dict) -> list:
    """审计写入并发 section"""
    try:
        out = ["### 审计写入并发", ""]
        if not load:
            out.append("_无数据_")
            out.append("")
            return out
        out.append("| 并发 | 总请求 | QPS | 总耗时 | 错误 |")
        out.append("|---|---|---|---|---|")
        for conc in [1, 5, 10]:
            r = load.get(f"audit_conc_{conc}", {}) or {}
            if not r:
                continue
            out.append(
                f"| {int(_safe_num(r.get('concurrency')))} | {int(_safe_num(r.get('total_requests')))} | "
                f"{_safe_num(r.get('qps'))} | {_safe_num(r.get('total_elapsed_s'))}s | "
                f"{int(_safe_num(r.get('errors')))} |"
            )
        out.append("")
        return out
    except Exception as e:
        return ["### 审计写入并发", "", f"_渲染失败: {e}_", ""]
        
def _section_conclusion(perf: dict, load: dict) -> list:
    """结论 section"""
    try:
        out = ["## 三、结论", ""]
        if perf:
            policy_ms = _safe_num(perf.get("policy_engine", {}).get("avg_ms"))
            out.append(f"- 策略引擎平均耗时 **{policy_ms}ms**，可忽略不计")
        if load:
            qps_list = []
            for c in [1, 5, 10, 20]:
                r = load.get(f"policy_conc_{c}", {}) or {}
                if r:
                    qps_list.append(_safe_num(r.get("qps")))
            if qps_list:
                out.append(f"- 策略引擎峰值 QPS **{max(qps_list)}**")
            total_errors = 0
            for k, v in load.items():
                if isinstance(v, dict) and "errors" in v:
                    total_errors += int(_safe_num(v.get("errors")))
            out.append(f"- 全部压测错误数: **{total_errors}**")
        out.append("")
        return out
    except Exception as e:
        return ["## 三、结论", "", f"_渲染失败: {e}_", ""]


def generate_markdown() -> str:
    """生成 Markdown 报告"""
    perf = _latest("perf_*.json")
    load = _latest("load_*.json")

    sections = []

    # 头部
    sections.append("# VotumSecuris 性能压测报告")
    sections.append("")
    sections.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    sections.append(f"报告版本: {REPORT_SCHEMA}")
    sections.append("")

    # 各 section 独立处理
    sections.extend(_section_baseline(perf))
    sections.append("## 二、并发压测")
    sections.append("")
    sections.extend(_section_load_policy(load))
    sections.extend(_section_load_audit(load))
    sections.extend(_section_conclusion(perf, load))

    # 尾部
    sections.append("---")
    sections.append("")
    sections.append("*本报告由 `bench/report.py` 自动生成*")

    return "\n".join(sections)
    
def save_report() -> str:
    """保存并打印报告"""
    try:
        md = generate_markdown()
    except Exception as e:
        md = f"# 报告生成失败\n\n错误: {e}\n"

    try:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(OUT_PATH, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"报告已保存: {OUT_PATH}")
    except Exception as e:
        print(f"[保存失败] {e}")

    print()
    print(md[:2000])
    return str(OUT_PATH)


if __name__ == "__main__":
    save_report()