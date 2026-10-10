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
            "适用前提：用户已经说出了具体的感受或事件。\n"
            "要求：先把你理解到的对方情绪复述一遍，用你自己的话，"
            "而不是机械重复对方的原句。\n"
            "例如用户说'我考砸了，心里堵得慌'，你可以说"
            "'听起来这次的结果让你很失落，也有些堵得慌'。\n"
            "本轮不要给建议，不要评价对错。"
        ),
        temperature=0.6,
    ),
    "explore": Strategy(
        name="探索与澄清",
        system_addon=(
            "本轮请采用【探索与澄清】策略。\n"
            "目标：帮对方把模糊的感受说得更具体——"
            "这正是他'说不上来'的原因。\n"
            "做法：提出**一个**开放式问题，低压力、无预设答案。\n"
            "好的问题像：'那件事对你来说，最难受的是哪一部分？'\n"
            "**注意**：\n"
            "  - 一次只问一个问题，不要连续追问\n"
            "  - 不要给具体建议或行动方案，那是下一轮的事\n"
            "  - 如果对方已经说不清，就换更小、更具体的切口"
        ),
        temperature=0.7,
    ),
    "support": Strategy(
        name="支持与鼓励",
        system_addon=(
            "本轮请采用【支持与鼓励】策略。\n"
            "目标：让对方感到自己的努力被看见，而不是被评价。\n"
            "做法：先**具体地**指出他已经在做的事或已经拥有的资源，"
            "再表达支持。注意必须具体——"
            "不要说'你已经很棒了''你很努力'这类空泛的话，"
            "而要说'你会主动问辅导员，这不是随便想想'这样的细节。\n"
            "**本轮严格禁止**：\n"
            "  - 不要提出任何新的问题\n"
            "  - 不要给具体建议或行动方案\n"
            "  - 不要说教\n"
            "如果实在想延续对话，只做陈述，不提问。"
        ),
        temperature=0.75,
    ),
    "reframe": Strategy(
        name="认知重构",
        system_addon=(
            "本轮请采用【认知重构】策略。\n"
            "目标：提供一个可能的替代视角，但绝不强迫对方接受。\n"
            "做法：先承认对方当前感受的合理性，"
            "再 gently 提出一个不同的角度，"
            "最后询问对方是否认同。\n"
            "例：'这确实挺难的。有没有另一种可能是——'\n"
            "**注意**：\n"
            "  - 不要说教，不要用'你应该''你必须'\n"
            "  - 不要强行乐观，不要否定对方的感受\n"
            "  - 如果对方不认同，下一轮应立刻退回共情，不要坚持\n"
            "这一点很重要：给视角是邀请，不是结论。"
        ),
        temperature=0.8,
    ),
}

# 策略选择的判定维度：
# 1. 情绪强度  2. 用户是否在寻求建议  3. 是否已有资源支撑  4. 是否陷入僵局
DEFAULT_STRATEGY = "reflect"

# 同一策略最多连续使用的轮数。
# 依据心理咨询中的「引导节奏」：连续追问超过三轮，会让用户从「被陪伴」
# 变成「被审问」，反而关闭表达。这个数字是经验值，需要真实试用校准。
MAX_CONSECUTIVE = 2

# 策略轮换顺序：连续使用同一策略后，按此顺序切换。
# 设计意图是在四个策略间形成自然轮换，避免卡在单一模式。
# 注意：此处用策略的 name（中文）而非字典 key（英文），
# 因为传入的 strategy_history 记录的是 name。
ROTATION_ORDER = ["反映与共情", "探索与澄清", "支持与鼓励", "认知重构"]


def _pick_rotation(previous: list, avoid: set) -> str:
    """
    在轮换顺序中挑选下一个策略。

    设计要点：不能固定顺序轮换。固定顺序会导致在两个策略间来回摆动
    （实测出现过 support ↔ reframe 交替），而真正的自适应应该
    「上次用了 A，这次就跳过 A 和紧邻的候选，向前推进」。

    因此这里的做法是：从上轮策略在 ROTATION_ORDER 中的位置往后找，
    跳过最近用过的策略。这样四个策略会自然轮转一圈再重复，
    而不是两两交替。
    """
    if not previous:
        return ROTATION_ORDER[0]

    recent = set(previous[:2])

    # 以上轮策略为起点，向后推进
    last = previous[0]
    if last in ROTATION_ORDER:
        start = ROTATION_ORDER.index(last) + 1
    else:
        start = 0

    candidates = ROTATION_ORDER[start:] + ROTATION_ORDER[:start]

    for name in candidates:
        if name in recent:
            continue
        if name in avoid:
            continue
        return name

    # 全部候选都被排除时，取轮换表首个
    return ROTATION_ORDER[0]


def select_strategy(
    user_input: str,
    turn_index: int,
    has_given_advice: bool = False,
    strategy_history: list | None = None,
) -> Strategy:
    """
    规则驱动的策略选择。

    刻意采用可读的规则而非模型判定：作业要求评测策略是否有效，
    规则方案可解释、可复现、可测量。

    参数
    ----
    user_input       用户本轮输入
    turn_index       已进行的轮次
    has_given_advice此前是否已给过建议（决定是否转向认知重构）
    strategy_history此前使用的策略名称列表，用于避免连续重复

    返回
    ----
    Strategy         选中的策略对象
    """
    text = user_input.strip()
    history = strategy_history or []

    def _by_name(name: str) -> Strategy:
        """按名称取策略对象。"""
        return next(s for s in STRATEGIES.values() if s.name == name)

    def _history_contains(name: str) -> bool:
        return name in history

    def _consecutive_count(name: str) -> int:
        """统计该策略在最近历史中连续出现的次数。"""
        count = 0
        for past in reversed(history):
            if past == name:
                count += 1
            else:
                break
        return count

    # 先算出已过滤的正常策略历史，供轮换与连续性判定使用。
    # 守卫：history 中可能含 crisis_interrupt 等边界策略名，
    # 它们不在轮换表内，必须先过滤，否则轮换逻辑会失效。
    normal_history = [h for h in history if h in ROTATION_ORDER]
    exhausted = (
        normal_history
        and _consecutive_count(normal_history[-1]) >= MAX_CONSECUTIVE
    )

    # ── 规则 0（最高优先级）：用户说不清自己的感受 ──
    # 这正是赛题背景指出的核心人群特征——「表达意愿不足、难以直接描述自身困扰」。
    # 此时共情是无效的：用户连自己的感受都抓不住，复述只会让他更困惑。
    # 正确做法是立刻提供具体的描述抓手，帮用户把模糊的感觉落地。
    vague_markers = ["说不上来", "不知道怎么说", "说不清", "形容不了", "就是觉得"]
    if any(marker in text for marker in vague_markers):
        return STRATEGIES["explore"]

    # ── 规则 1：索要答案 → 视此前是否已给过建议决定方向 ──
    # 若还没有给过建议，说明用户仍在等一个明确答复，此时重构会显得答非所问。
    advice_markers = ["怎么办", "该不该", "要不要", "建议", "如何", "怎么才能"]
    if any(marker in text for marker in advice_markers):
        if has_given_advice:
            return STRATEGIES["reframe"]
        # 没给过建议 → 先共情，让用户感到被听见后再谈思路
        return STRATEGIES["reflect"]

    # ── 规则 2（高优先）：连续使用同一策略已超上限 → 强制轮换 ──
    # 这是真实试用暴露的核心问题：原兜底逻辑让后 7 轮全落在「探索与澄清」，
    # 提问变成盘问。心理陪伴中连续追问三轮以上会让用户关闭表达。
    #
    # 该规则高于下面的内容匹配规则，因为当连续追问已经造成负担时，
    # 即使用户输入里出现了「我已经」这类词，也应先换方式而不是继续支持鼓励。
    if exhausted:
        return _by_name(_pick_rotation(normal_history, avoid=set()))

    # ── 规则 3：提及自己的努力或已有支撑 → 支持鼓励 ──
    resource_markers = ["我试过", "我已经", "我坚持", "我每天", "我靠着", "我一直在"]
    if any(marker in text for marker in resource_markers):
        return STRATEGIES["support"]

    # ── 规则 4：用户情绪强烈 → 先共情，不要急着分析 ──
    intense_markers = ["难受", "崩溃", "烦", "累", "委屈", "孤独", "害怕", "慌", "焦虑"]
    if any(marker in text for marker in intense_markers):
        return STRATEGIES["reflect"]

    # ── 规则 5：描述具体事件且非首轮 → 探索澄清 ──
    if len(text) > 25 and turn_index >= 1:
        return STRATEGIES["explore"]

    # ── 兜底 ──
    # 首轮共情；后续轮换，避免固定落在单一策略上。
    if turn_index == 0:
        return STRATEGIES["reflect"]
    if normal_history:
        return _by_name(_pick_rotation(normal_history, avoid={normal_history[-1]}))
    return STRATEGIES["explore"]
