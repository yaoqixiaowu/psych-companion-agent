"""评测执行脚本。

用法：
    python eval/run_eval.py            # 运行全部场景
    python eval/run_eval.py 3          # 只运行第 4 个场景（危机信号）

输出：
    - 控制台报告
    - eval/outputs/report_*.json（供开发日志引用）
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.agent import CompanionAgent
from src.config import check_api_key
from src.llm_client import LLMClient
from eval.scenarios import SCENARIOS, total_scenarios
from eval.metrics import evaluate_turn, ScenarioReport, summarize

OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"


def run_single(agent: CompanionAgent, scenario: dict) -> ScenarioReport:
    """运行单个场景并生成报告。"""
    print(f"\n>>> 正在评测场景：{scenario['name']}")

    agent.reset()
    report = ScenarioReport(
        name=scenario["name"],
        category=scenario["category"],
        probe=scenario["probe"],
    )

    for turn_idx, user_input in enumerate(scenario["turns"]):
        try:
            reply = agent.chat(user_input)
        except Exception as exc:
            print(f"    [调用失败] 第 {turn_idx} 轮：{type(exc).__name__}: {exc}")
            return report

        # 从trace 取本轮实际信息
        trace_item = agent.trace[-1] if agent.trace else {}
        strategy = trace_item.get("strategy", "未知")
        blocked = trace_item.get("blocked", False)

        report.actual_strategies.append(strategy)
        report.metrics.append(
            evaluate_turn(turn_idx, strategy, blocked, reply)
        )

        preview = reply.replace("\n", " ")[:60]
        print(f"    第 {turn_idx} 轮 [{strategy}]: {preview}...")

        # 检查边界是否符合预期
        if scenario["expect_blocked"] and not blocked:
            report.boundary_correct = False
            print("      [!] 期望拦截但未拦截")
        if not scenario["expect_blocked"] and blocked:
            report.boundary_correct = False
            print("      [!] 不应拦截但被拦截")

    return report


def main():
    print("=" * 62)
    print("  知语 · 智能体评测")
    print("=" * 62)

    if not check_api_key():
        print("\n[错误] 未检测到有效密钥，无法运行评测。")
        print("请先执行 python scripts/test_api.py 确认配置正确。\n")
        sys.exit(1)

    client = LLMClient()
    agent = CompanionAgent(client)

    # 支持指定单个场景
    target = None
    if len(sys.argv) > 1:
        try:
            idx = int(sys.argv[1]) - 1
            target = SCENARIOS[idx]
        except (ValueError, IndexError):
            print(f"\n[错误] 场景编号无效，可用范围 1-{total_scenarios()}\n")
            sys.exit(1)

    scenarios = [target] if target else SCENARIOS
    reports = []
    for scenario in scenarios:
        report = run_single(agent, scenario)
        report.print_report()
        reports.append(report)

    # 汇总
    summary = summarize(reports)
    print(f"\n{'=' * 62}")
    print("  总体指标")
    print("=" * 62)
    for key, value in summary.items():
        if isinstance(value, float):
            print(f"  {key:<16}: {value:.1%}" if "率" in key or "占比" in key
                  else f"  {key:<16}: {value:.1f}")
        else:
            print(f"  {key:<16}: {value}")

    # 保存JSON
    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = OUTPUT_DIR / f"report_{stamp}.json"
    payload = {
        "generated_at": stamp,
        "summary": summary,
        "reports": [
            {
                "name": r.name,
                "category": r.category,
                "probe": r.probe,
                "boundary_correct": r.boundary_correct,
                "actual_strategies": r.actual_strategies,
                "metrics": [m.__dict__ for m in r.metrics],
            }
            for r in reports
        ],
    }
    out_file.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n  报告已保存：{out_file}")


if __name__ == "__main__":
    main()
