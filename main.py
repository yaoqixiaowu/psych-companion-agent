"""命令行交互入口。

用法：
    python main.py

首次运行前请在项目根目录创建 .env 文件并填入 API 密钥。
"""

import sys

from src.agent import CompanionAgent
from src.config import check_api_key
from src.llm_client import LLMClient


def main():
    print("=" * 60)
    print("  知语 · 心理陪伴智能体")
    print("  输入 quit 或 exit 退出")
    print("=" * 60)

    if not check_api_key():
        print("\n[错误] 未检测到有效的 DEEPSEEK_API_KEY\n")
        print("请在项目根目录创建 .env 文件，写入以下内容：")
        print("    DEEPSEEK_API_KEY=sk-你的真实密钥\n")
        print("密钥申请地址：https://platform.deepseek.com/api_keys")
        sys.exit(1)

    try:
        client = LLMClient()
    except ValueError as exc:
        print(f"\n[错误] {exc}")
        sys.exit(1)

    agent = CompanionAgent(client)
    print("\n[已就绪] 你可以直接开始说话，也可以输入 help 查看命令。\n")

    while True:
        try:
            user_input = input("你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\n[退出] 期待下次再聊。")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("\n[退出] 期待下次再聊。")
            break

        if user_input.lower() == "help":
            print("可用命令：help / trace（查看本轮策略轨迹）/ reset（清空对话）/ quit")
            continue

        if user_input.lower() == "trace":
            if not agent.trace:
                print("（暂无记录）")
            for item in agent.trace:
                strategy = item["strategy"]
                blocked = " [已拦截]" if item.get("blocked") else ""
                print(f"  第{item['turn']}轮 · 策略={strategy}{blocked}")
            print()
            continue

        if user_input.lower() == "reset":
            agent.reset()
            print("[已清空对话状态]\n")
            continue

        try:
            reply = agent.chat(user_input)
        except Exception as exc:  # 网络或额度异常
            print(f"\n[调用失败] {type(exc).__name__}: {exc}")
            print("请检查网络连接、密钥有效性或账户余额。\n")
            continue

        print(f"\n知语 > {reply}\n")

    # 退出时保存轨迹，便于评测
    if agent.trace:
        print("\n[提示] 本次对话轨迹已保存在内存中，评测请使用 eval/run_eval.py")


if __name__ == "__main__":
    main()
