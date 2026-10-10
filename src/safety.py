"""安全边界模块。

对应任务目标第2 项：设计角色设定、语气与安全边界，明确它不做什么。

设计原则：
1. 危机识别优先于一切对话策略——命中风险时立即中断常规流程。
2. 边界不靠模型自觉，靠代码硬拦截 + prompt 双保险。
3. 智能体明确「不是」什么，比「是」什么更重要。
"""

from dataclasses import dataclass


# 高危信号：自伤 / 自杀 / 伤人风险
CRISIS_PATTERNS = {
    "self_harm": [
        "自杀", "轻生", "不想活", "活不下去", "结束生命",
        "自残", "割腕", "跳楼", "服药过量", "伤害自己",
    ],
    "harm_others": [
        "杀人", "报复社会", "伤害别人", "同归于尽",
    ],
}

# 医疗边界：涉及诊断与处方时必须转介
MEDICAL_BOUNDARY_PATTERNS = [
    "我是不是抑郁症", "帮我诊断", "开点药", "吃什么药",
    "是不是焦虑症", "帮我看看是不是有病",
]


@dataclass
class SafetyVerdict:
    """一次安全检查的结论。"""

    is_crisis: bool
    crisis_type: str | None
    reason: str
    # 是否属于医疗边界（需转介但不阻断对话）
    needs_referral: bool = False


def check_safety(user_input: str) -> SafetyVerdict:
    """
    对用户输入做安全检查。

    采用关键词匹配作为确定性兜底。生产环境应叠加分类模型，
    但关键词方案可解释、可评测，符合本作业的评测要求。
    """
    text = user_input.strip().lower()

    for pattern in CRISIS_PATTERNS["self_harm"]:
        if pattern in text:
            return SafetyVerdict(
                is_crisis=True,
                crisis_type="self_harm",
                reason=f"命中自伤/自杀相关表述：{pattern}",
                needs_referral=True,
            )

    for pattern in CRISIS_PATTERNS["harm_others"]:
        if pattern in text:
            return SafetyVerdict(
                is_crisis=True,
                crisis_type="harm_others",
                reason=f"命中伤人相关表述：{pattern}",
                needs_referral=True,
            )

    for pattern in MEDICAL_BOUNDARY_PATTERNS:
        if pattern in text:
            return SafetyVerdict(
                is_crisis=False,
                crisis_type=None,
                reason=f"涉及心理疾病诊断或处方：{pattern}",
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
