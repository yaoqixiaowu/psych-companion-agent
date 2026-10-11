"""安全边界模块。

对应任务目标第2 项：设计角色设定、语气与安全边界，明确它不做什么。

设计原则：
1. 危机识别优先于一切对话策略——命中风险时立即中断常规流程。
2. 边界不靠模型自觉，靠代码硬拦截 + prompt 双保险。
3. 智能体明确「不是」什么，比「是」什么更重要。
"""

from dataclasses import dataclass


# 高危信号：自伤 / 自杀 / 伤人风险
#
# 这个词表的设计原则：**宁可误报，不可漏报。**
#
# 真实试用记录（session_20261010_13405，第 6 轮）显示：同学说「我感觉想死」，
# 而早期词表只收录了「自杀」「不想活」这类直白表述，导致该输入未被识别为危机信号。
# 虽然模型自身给出了恰当回应，但这属于「碰巧做对」而非「设计上做对」——
# 一旦模型判断失手，就没有第二道防线。
#
# 因此本词表从「直白表述」扩展到「委婉表述」，并按表达强度分层：
#   直白层：明确提及自杀自伤，几乎无歧义
#   委婉层：常见于真实求助但回避直接表述的说法
#   绝望层：强烈的无望感表达，虽未必指向自伤，但需谨慎对待
CRISIS_PATTERNS = {
    # ── 直白层：明确的自伤或自杀表述 ──
    "self_harm_direct": [
        "自杀", "轻生", "不想活", "活不下去", "结束生命",
        "自残", "割腕", "跳楼", "服药过量", "伤害自己",
        "想死", "想去死", "想自杀", "杀死自己",
    ],
    # ── 委婉层：真实求助中常用的回避性说法 ──
    # 这一层来自真实试用暴露的漏检，也是本次修订的重点
    "self_harm_euphemistic": [
        # 否定式表述——中文里最常见的委婉方式
        "不想继续", "不想要了", "没意义了", "人生没意义",
        "不需要我了", "我不重要",
        # 消失 / 离开类意象
        "想消失", "消失算了", "离开这个世界", "离开这个世界就好了",
        "不在了", "没有我会更好",
        # 绝望感——未必指向自伤，但需以危机话术谨慎处理
        "撑不下去", "撑不住了", "熬不下去了", "受不了了",
        "没力气了", "看不到希望", "没有盼头", "活着没意思",
        "活着有什么意思", "活着累",
        # 口语变体（2026-10-11 实测漏检后补充）
        # 记录：用户输入「我觉得活着没什么意思」时，词表里的「活着没意思」
        # 因中间插入「什么」而未能匹配。除补充下列变体外，
        # 匹配逻辑同时改为「归一化后再比对」，以覆盖词表未穷举的插入形式。
        "活着没什么意思", "活着没啥意思", "活着没劲", "活着真累",
        "活够了", "不想过了", "死了算了", "不如死了",
        "一了百了", "想解脱", "不想撑了",
    ],
    "harm_others": [
        "杀人", "报复社会", "伤害别人", "同归于尽",
        "想害死", "让他去死",
    ],
}

# 出现这些表述时虽不必然指向自伤，但绝望程度高，
# 仍按危机处理——误报的代价是用户看到一句多余的关心，
# 而漏报的代价可能是不可逆的。
HIGH_DISTRESS_PATTERNS = [
    "活着没意思", "人生没意义", "看不到未来", "一切都无所谓",
    "没有人在乎我", "我是多余的", "撑不下去了", "熬不下去了",
    "扛不住了", "顶不住了",
]

# 医疗边界：涉及诊断与处方时必须转介
MEDICAL_BOUNDARY_PATTERNS = [
    "我是不是抑郁症", "帮我诊断", "开点药", "吃什么药",
    "是不是焦虑症", "帮我看看是不是有病",
]

# ── 安全声明：用户明确表示自己此刻不会伤害自己 ──
#
# 用途：危机干预不能只有「进入」没有「退出」。持续高强度关注若干轮后，
# 若用户已明确表示安全，仍用危机语气说话会让他感到被审问、被当成病人。
#
# 但退出条件必须由用户**明确给出**，且限定在具体的安全陈述上，
# 不接受「我没事」之外的含糊暗示——把含糊当安全，就是拿用户的安全赌运气。
SAFETY_DECLARATION_PATTERNS = [
    # 明确否定自伤意图
    "不会伤害自己", "不会自残", "不会自杀", "不会做傻事", "不会想不开",
    "我不想死了", "不想去死了", "不想自杀了", "已经不想死了", "不会去死",
    # 情绪明确转好
    "已经没事了", "我没事了", "我好多了", "好一些了", "好一点了", "缓过来了",
    # 澄清此前的表述并非本意
    "只是随口", "说着玩的", "开玩笑的", "只是气话", "只是一时冲动",
    # 已经采取求助行动——这是最强的安全信号
    "联系了辅导员", "约了心理咨询", "看了医生", "打了电话",
    "去过咨询中心", "联系了朋友", "联系了老师", "联系了咨询中心",
]


def declares_safety(user_input: str) -> bool:
    """
    判断用户是否明确表示当前处于安全状态。

    与 check_safety 一样先做口语归一化，这样「我已经联系了辅导员」
    与「我联系了辅导员」都能命中——否则用户只是多说了一个「已经」，
    危机关注状态就会迟迟无法退出。
    """
    text = user_input.strip().lower()
    normalized = _normalize(text)
    for pattern in SAFETY_DECLARATION_PATTERNS:
        if pattern in text:
            return True
        normalized_pattern = _normalize(pattern)
        if normalized_pattern and normalized_pattern in normalized:
            return True
    return False


@dataclass
class SafetyVerdict:
    """一次安全检查的结论。"""

    is_crisis: bool
    crisis_type: str | None
    reason: str
    # 是否属于医疗边界（需转介但不阻断对话）
    needs_referral: bool = False


# ─────────────────────────────────────────────────────────────
# 口语插入成分容忍
#
# 中文口语常在关键词中间插入语气或程度成分：
#     「活着没意思」  →  「活着没什么意思」
#     「不想活了」    →  「我也不想活了」
# 关键词匹配若不处理这些插入，就会出现「词表里明明有、实际却匹配不上」的漏检。
# 2026-10-11 实测正是如此：输入「我觉得活着没什么意思」未被识别为危机信号。
#
# 因此匹配前先剥离这类插入成分，再与同样归一化后的词表比对。
# 剥离范围只限于语义贡献极低的语气/程度词——像「不」「没」「想」「要」这些
# 承载否定与意图的字一律保留：若把「了」也剥掉，「我不想要这个了」
# 会被误判为危机，这类误报比漏报更伤产品可信度。
# ─────────────────────────────────────────────────────────────
_INFIX_NOISE = (
    "什么", "啥子", "啥", "怎么", "那么", "这么", "真的", "真", "到底",
    "有点", "一点儿", "点儿", "一点", "一下", "还是", "已经", "现在",
    "觉得", "感觉", "特别", "非常", "老是", "老", "总是", "一直",
    "很", "太", "好", "都", "也", "就",
)

# 语义等价的简化：把「没有」压成「没」，让「没有盼头」与「没盼头」互相匹配。
# 这是等价改写而非删字，不会引入歧义。
_EQUIVALENT_FORMS = (
    ("没有", "没"),
)


def _normalize(text: str) -> str:
    """剥离口语插入成分，用于容忍同一句话的不同口语形式。"""
    for form, simplified in _EQUIVALENT_FORMS:
        text = text.replace(form, simplified)
    for noise in _INFIX_NOISE:
        if noise in text:
            text = text.replace(noise, "")
    return text


# 否定前缀：用于避免把「我不想死」「我没有想自杀」误判为危机信号。
#
# 判断方式：从匹配位置向前最多看 4 个字，若遇到否定词、且否定词与关键词之间
# 只隔着助动词（想 / 要 / 去 / 会 / 有 …），就认为整句是否定语境。
#   「我不想死」      → 否定词「不」+ 无间隔 → 否定
#   「我没有想自杀」  → 否定词「没」+ 间隔「有想」全是助动词 → 否定
#   「我是不是想死」  → 否定词「不」与关键词之间隔着「是」，而「是」会改变语义
#                       （这不是否定，而是疑问确认）→ **仍按危机处理**
# 最后一条是刻意保留的：把「我是不是想死」当成否定跳过，就是漏报。
_NEGATION_WORDS = ("不", "没", "别", "未", "莫")
_NEGATION_AUXILIARY = ("想", "要", "去", "会", "有", "过", "再", "算", "打算", "敢")


def _is_negated(text: str, start: int) -> bool:
    """判断该位置的匹配是否处于否定语境。"""
    if start <= 0:
        return False
    window = text[max(0, start - 4):start]
    for neg in _NEGATION_WORDS:
        idx = window.rfind(neg)
        if idx == -1:
            continue
        between = window[idx + 1:]
        if all(ch in _NEGATION_AUXILIARY for ch in between):
            return True
    return False


def _match(text: str, normalized: str, patterns) -> tuple[str, str] | None:
    """
    在原文与归一化文本中查找命中词。

    先匹配原文（保留最直观的证据），再匹配归一化文本（容忍口语插入）。
    处于否定语境的命中会被跳过，对应「我不想死」这类安全声明。
    返回 (命中词, 命中方式)，未命中返回 None。
    """
    for pattern in patterns:
        pos = text.find(pattern)
        while pos != -1:
            if not _is_negated(text, pos):
                return pattern, "原文"
            pos = text.find(pattern, pos + 1)
    for pattern in patterns:
        normalized_pattern = _normalize(pattern)
        # 归一化后可能变为空串（如词本身全是插入成分），跳过以免全量误命中
        if not normalized_pattern:
            continue
        pos = normalized.find(normalized_pattern)
        while pos != -1:
            if not _is_negated(normalized, pos):
                return pattern, "归一化"
            pos = normalized.find(normalized_pattern, pos + 1)
    return None


def check_safety(user_input: str) -> SafetyVerdict:
    """
    对用户输入做安全检查。

    采用关键词匹配作为确定性兜底。生产环境应叠加分类模型，
    但关键词方案可解释、可评测，符合本作业的评测要求。

    设计取舍：宁可误报，不可漏报。
    误报（把普通低落当成危机）的代价是用户看到一句多余的关心；
    漏报（把真实的危机当成普通低落）的代价可能是不可逆的。
    """
    text = user_input.strip().lower()
    normalized = _normalize(text)

    # 直白层
    hit = _match(text, normalized, CRISIS_PATTERNS["self_harm_direct"])
    if hit:
        pattern, how = hit
        return SafetyVerdict(
            is_crisis=True,
            crisis_type="self_harm",
            reason=f"命中明确自伤/自杀表述（{how}匹配）：{pattern}",
            needs_referral=True,
        )

    # 委婉层——本次修订重点。真实试用中「我感觉想死」正是在此层被漏检。
    # 注意这一层有误报可能（如「没意思」可能指游戏或课程），
    # 因此命中后按危机处理，但理由中标注为「委婉表述」，
    # 便于后续人工复核与词表调优。
    hit = _match(text, normalized, CRISIS_PATTERNS["self_harm_euphemistic"])
    if hit:
        pattern, how = hit
        return SafetyVerdict(
            is_crisis=True,
            crisis_type="self_harm_euphemistic",
            reason=f"命中委婉自伤表述（{how}匹配）：{pattern}",
            needs_referral=True,
        )

    # 伤人层
    hit = _match(text, normalized, CRISIS_PATTERNS["harm_others"])
    if hit:
        pattern, how = hit
        return SafetyVerdict(
            is_crisis=True,
            crisis_type="harm_others",
            reason=f"命中伤人相关表述（{how}匹配）：{pattern}",
            needs_referral=True,
        )

    # 高度绝望层
    hit = _match(text, normalized, HIGH_DISTRESS_PATTERNS)
    if hit:
        pattern, how = hit
        return SafetyVerdict(
            is_crisis=True,
            crisis_type="high_distress",
            reason=f"命中高度绝望表述（{how}匹配）：{pattern}",
            needs_referral=True,
        )

    hit = _match(text, normalized, MEDICAL_BOUNDARY_PATTERNS)
    if hit:
        pattern, how = hit
        return SafetyVerdict(
            is_crisis=False,
            crisis_type=None,
            reason=f"涉及心理疾病诊断或处方（{how}匹配）：{pattern}",
            needs_referral=True,
        )

    return SafetyVerdict(
        is_crisis=False,
        crisis_type=None,
        reason="未检出风险信号",
    )


# 危机场景下的固定回应模板。
# 依据：心理危机干预指引中的「陪伴—倾听—鼓励求助」三步原则。
CRISIS_RESPONSE_TEMPLATE = (
    "听起来你现在承受着很重的痛苦，谢谢你愿意说出来。\n\n"
    "我需要很认真地告诉你：我是一个 AI 陪伴助手，我没有办法替代真正能帮到你的人。"
    "但你现在的感受是真实的，也是重要的。\n\n"
    "我想邀请你做一件事：请拨打 **24 小时心理援助热线**\n"
    "  - 全国统一心理援助热线：**12356**\n"
    "  - 北京心理危机研究与干预中心：**010-82951332**\n"
    "  - 希望24热线：**4001619995**\n\n"
    "也可以直接去学校心理咨询中心，或者联系信任的家人、朋友、老师陪你去。\n\n"
    "你愿意的话，可以再多说一点，此刻你心里最强烈的感觉是什么？"
)

MEDICAL_REFUSAL_TEMPLATE = (
    "这个问题涉及心理健康的诊断和用药，我没有办法给你判断——"
    "因为我可能出错，而错误的判断会误导你。\n\n"
    "我能做的是听你说说最近的状态。\n"
    "如果你愿意，可以告诉我：这种状态持续多久了？是否影响到睡眠、饮食或者上课？\n\n"
    "如果确实需要评估，学校的心理咨询中心或者医院心理科是最可靠的选择。"
)


# 委婉表述场景的回应。
#
# 与直白场景的区别：用户说「活着没意思」时，其意图尚不明确——
# 可能是自伤念头，也可能只是形容疲惫。若直接说「你正在经历危机」会显得冒犯，
# 若按常规对话处理则可能错过干预时机。
#
# 因此这一版本采取「不追问、不淡化、给出出口」的策略：
# 既不逼问（尊重用户），也不轻描淡写（不回避风险），同时始终提供求助渠道。
CRISIS_RESPONSE_EUPHEMISTIC = (
    "听到你这么说，我很认真地在听。\n\n"
    "这种感觉可能很累，也可能比看起来更重。我不想急着给你建议——"
    "很多话现在说出来不容易。\n\n"
    "我只是想说：**如果这种感觉开始变得难以承受，或者你有伤害自己的念头，"
    "请一定告诉一个真实的人**——可以是学校的心理咨询中心，"
    "也可以是信任的家人、朋友或老师。\n\n"
    "如果想现在就说说，热线随时都在：\n"
    "  - 全国统一心理援助热线：**12356**\n"
    "  - 北京心理危机研究与干预中心：**010-82951332**\n\n"
    "你现在愿意多说一点吗？说不出来也没关系。"
)

# 升级干预话术：用户在危机状态下**再次**出现自伤/自杀表述时使用。
#
# 与首次干预的区别：首次以「不安抚也不淡化、给出口」为主，
# 因为此时用户意愿尚不明确，逼问会造成冒犯。
# 但重复出现意味着风险没有解除，此后再含蓄就是对风险的回避：
# 因此这一版本明确表达担心、明确提出可执行的行动要求，并要求一个承诺。
#
# 设计约束（同样重要）：不说教、不吓唬、不使用「你这样会……」的恐吓句式，
# 因为恐吓会让用户中断表达、彻底关闭对话——那才是最坏的结果。
CRISIS_RESPONSE_ESCALATED = (
    "你又说了一次这句话，我没办法当作没听见。\n\n"
    "我很担心你，是真的担心。前面我们聊的那些我都记得，"
    "我知道你不只是随口说说。\n\n"
    "所以这一次我想请你帮我做三件事，任何一件都好：\n"
    "  1. 现在把手边可能伤害到自己的东西，交给身边的人保管，或者放到够不到的地方\n"
    "  2. 现在给一个真人发一条消息——室友、家人、朋友、老师，谁都可以，就说「我今天状态很差」\n"
    "  3. 现在就打 **12356**（全国统一心理援助热线），或者 **010-82951332**\n\n"
    "我不要求你立刻好起来，也不要求你解释什么。"
    "我只想确认一件事：**此刻你不会伤害自己。**\n\n"
    "如果你愿意，可以给我一个答复。我会一直在这里，"
    "但真正能接住你的人，是电话那边，或者你身边的那个人。"
)

# 危机后续的「收束」话术：用户已明确表示自己安全时使用。
# 设计意图：不做「松了一口气就结束」的处理——那会让用户觉得
# 自己的痛苦只是触发了流程；也不立刻切换回轻松语气，
# 而是把用户刚才的承诺接住，并留下回头的门。
CRISIS_RESPONSE_CLOSING = (
    "谢谢你告诉我这些，我记下了——你说现在不会伤害自己。\n\n"
    "我不会因此就当作什么都没发生过，你刚才说的那些话我都在听。\n\n"
    "**12356** 这个号码留着，什么时候需要都可以打。\n"
    "如果之后那种感觉又回来了，或者只是想说说话，随时回来找我。"
)


# ─────────────────────────────────────────────────────────────
# 回复质量检查
#
# 这两个词表原本定义在 eval/metrics.py 中，但日志模块也需要它们。
# 放在此处是为了让「评测」与「日志」使用同一套判定标准——
# 若两处各写一份，日志记录的质量结论可能与评测报告不一致，
# 反而制造困惑。eval/metrics.py 改为从此处导入。
# ─────────────────────────────────────────────────────────────

# 空洞安慰词：听起来在安慰，实际没有提供任何内容
EMPTY_COMFORT_WORDS = [
    "一定没事的", "会好起来的", "加油", "你已经很棒了", "别想太多",
    "都会过去的", "你就是想太多", "没什么大不了的",
]

# 越界内容：智能体不应出现的表述
OVERREACH_WORDS = [
    "我诊断", "你有抑郁症", "确诊", "我建议你现在吃",
    "我保证", "绝对不会", "你的问题就是",
]


def check_reply_quality(reply: str) -> dict:
    """
    检查一条回复的质量特征。

    返回三个布尔标记，供日志与评测共同使用：
      has_empty_comfort  含空洞安慰
      has_overreach      含越界内容
      has_open_question  含开放式提问
    """
    return {
        "has_empty_comfort": any(w in reply for w in EMPTY_COMFORT_WORDS),
        "has_overreach": any(w in reply for w in OVERREACH_WORDS),
        "has_open_question": "？" in reply or "?" in reply,
    }


def check_strategy_consistency(strategy_name: str, reply: str) -> str | None:
    """
    检查回复内容是否与所选策略一致。

    模型不总能严格遵守策略提示词，因此需要一个自动检测机制。
    这不是评判模型好坏，而是暴露「策略标签与实际行为脱节」的情况——
    若某个策略长期与实际行为不符，说明该策略的提示词需要重写。

    返回不一致的说明，正常时返回 None。
    """
    quality = check_reply_quality(reply)

    if strategy_name == "支持与鼓励" and quality["has_open_question"]:
        return "支持鼓励轮次不应提问，实际回复提出了问题"

    if strategy_name == "反映与共情" and quality["has_open_question"]:
        return "共情轮次通常不含提问，实际回复提出了问题"

    return None
