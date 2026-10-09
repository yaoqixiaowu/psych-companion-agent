"""心理对话策略选择机制。

对应任务目标第 3 项：让系统能根据不同场景选择合适的心理沟通策略。

策略来源：《心理咨询面谈技术》第4 版的核心技术，
结合赛题背景中「学生表达意愿不足」这一特征做适配。

四种策略：
  - reflect    反映与共情：复述用户情绪，确认理解正确
  - explore    探索与澄清：开放式提问，帮用户把模糊感受说具体
  - support    支持与鼓励：肯定用户已做的努力，强化自我效能
  - reframe    认知重构： gently 引导发现新的解读角度
"""

from dataclasses import dataclass


@dataclass
class Strategy:
    """一种沟通策略。"""

    name: str
    system_addon: str
    temperature: float = 0.7
    # 该策略下不建议使用的追问数量提示
    max_questions: int = 1


STRATEGIES = {
    "reflect": Strategy(
        name="反映与共情",
        system_addon=(
            "本轮请采用【反映与共情】策略。\n"
            "要求：先把你理解到的对方情绪复述一遍，用你自己的话，"
            "而不是机械重复对方的原句。\n"
            "例如用户说'我考砸了，心里堵得慌'，你可以说"
            "'听起来这次的结果让你很失落，也有些堵得慌'。\n"
            "本轮不要给建议，不要急着解决问题。"
        ),
        temperature=0.6,
    ),
    "explore": Strategy(
        name="探索与澄清",
        system_addon=(
            "本轮请采用【探索与澄清】策略。\n"
            "要求：提出一个开放式问题，帮对方把模糊的感受说得更具体。\n"
            "问题要低压力、无预设答案，避免连续追问。\n"
            "例如：'那件事对你来说，最难受的是哪一部分？'\n"
            "一次只问一个问题。"
        ),
        temperature=0.7,
    ),
    "support": Strategy(
        name="支持与鼓励",
        system_addon=(
            "本轮请采用【支持与鼓励】策略。\n"
            "要求：先具体地指出对方已经做到的事或已经拥有的资源，"
            "再表达支持。注意要具体，不要泛泛地说'你已经很棒了'。\n"
            "本轮不要提出新的问题。"
        ),
        temperature=0.75,
    ),
    "reframe": Strategy(
        name="认知重构",
        system_addon=(
            "本轮请采用【认知重构】策略。\n"
            "要求： gently 引导对方从另一个角度看这件事，"
            "但绝对不要说教、不要说'你应该'、不要强行乐观。\n"
            "做法是提出一个可能的替代视角，并询问对方是否认同。\n"
            "例如：'有没有另一种可能是，这次的结果也让你看清了自己在意什么？'\n"
            "如果对方不认同，立刻退回共情，不要坚持。"
        ),
        temperature=0.8,
    ),
}

# 策略选择的判定维度：
# 1. 情绪强度  2. 用户是否在寻求建议  3. 是否已有资源支撑  4. 是否陷入僵局
DEFAULT_STRATEGY = "reflect"


def select_strategy(
    user_input: str,
    turn_index: int,
    has_given_advice: bool = False,
) -> Strategy:
    """
    规则驱动的策略选择。

    刻意采用可读的规则而非模型判定：作业要求评测策略是否有效，
    规则方案可解释、可复现、可测量。
    """
    text = user_input.strip()

    # 规则 1：明显在求助解决方案，且我们已经给过一次建议 → 转向认知重构
    advice_markers = ["怎么办", "该不该", "要不要", "建议", "如何", "怎么才能"]
    if any(marker in text for marker in advice_markers) and has_given_advice:
        return STRATEGIES["reframe"]

    # 规则 2：用户在描述一件具体的事，希望被理解 → 探索澄清
    if len(text) > 25 and turn_index >= 1:
        return STRATEGIES["explore"]

    # 规则 3：用户情绪强烈但表达混乱 → 先共情
    intense_markers = ["难受", "崩溃", "烦", "累", "委屈", "孤独", "害怕", "慌"]
    if any(marker in text for marker in intense_markers) and turn_index == 0:
        return STRATEGIES["explore"]

    # 规则 4：用户提到自己的努力或已有支撑 → 支持鼓励
    resource_markers = ["我试过", "我已经", "我坚持", "我每天", "我靠着"]
    if any(marker in text for marker in resource_markers):
        return STRATEGIES["support"]

    # 兜底：第一轮共情，后续逐步引导表达
    if turn_index == 0:
        return STRATEGIES["reflect"]
    return STRATEGIES["explore"]
