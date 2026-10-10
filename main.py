"""命令行交互入口。

用法：
    python main.py
    python main.py --note "与同学试用的第一轮对话"

首次运行前请在项目根目录创建 .env 文件并填入 API 密钥。

每次退出时会自动在 logs/ 目录下生成对话记录（JSON + Markdown），
用于作业要求的「记录反馈」。
"""

import sys

from src.agent import CompanionAgent
from src.config import check_api_key
from src.llm_client import LLMClient
from src.logger import ConversationLogger


def parse_args():
    """解析命令行参数。支持 --note 标注本次对话的用途。"""
    if "--note" in sys.argv:
        idx = sys.argv.index("--note")
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return ""


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
    # logger 全程跟随，agent.reset() 不清空它——
    # reset 只清对话上下文，而整场体验的记录应当完整保留。
    logger = ConversationLogger(note=parse_args())

    print("\n[已就绪] 你可以直接开始说话，也可以输入 help 查看命令。")
    print("[提示] 本次对话退出后会自动保存到 logs/ 目录\n")

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
            print("可用命令：help / trace（查看策略轨迹）/ stats（查看统计）/ reset（清空对话）/ quit")
            continue

        if user_input.lower() == "trace":
            if not agent.trace:
                print("（暂无记录）")
            for item in agent.trace:
                blocked = " [已拦截]" if item.get("blocked") else ""
                print(f"  第{item['turn']}轮 · 策略={item['strategy']}{blocked}")
            print()
            continue

        if user_input.lower() == "stats":
            print("\n  本次对话统计：")
            print(logger.format_stats())
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

        # 同步写入日志。agent.trace 末条即本轮记录。
        # 注意危机场景下 trace 不被清空，因此这里总能取到正确的一条。
        if agent.trace:
            logger.add(agent.trace[-1])

        print(f"\n知语 > {reply}\n")

    # 退出时保存日志
    if logger.records:
        try:
            json_path, md_path = logger.save()
            print("\n[已保存对话记录]")
            print(f"  Markdown : {md_path}")
            print(f"  JSON     : {json_path}")
            print("\n[本次统计]")
            print(logger.format_stats())
            print()
        except Exception as exc:
            print(f"\n[警告] 日志保存失败：{exc}\n")
    else:
        print("\n[提示] 本次没有对话记录，未生成日志。")


if __name__ == "__main__":
    main()
