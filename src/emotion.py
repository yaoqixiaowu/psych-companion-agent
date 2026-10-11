"""情绪调制：让知语的语气与反应强度随用户状态逐轮变化。

## 为什么需要这一层

早期版本的语音是「一个音色念到底」：用户说「我想自残」和说「今天挺开心的」，
声音没有任何区别；文字侧的危机话术虽然换了，语气却仍然平铺直叙。
这会给人一种「若无其事」的感觉——**在心理陪伴场景里，语气本身就是回应的一部分**。
用户情绪越重，系统就越需要让他听出「这句话是被认真说的」。

因此本模块做两件事，且两边必须同源（同一份 emotion 同时驱动文字与语音）：

1. **语音侧**：给出 rate / pitch / volume 的偏移量，由 TTS 引擎施加
2. **文字侧**：给出 prompt_hint，注入系统提示词，约束这一轮模型的情绪浓度

## 调参依据（不是随手调的）

- **危机场景刻意「变慢、变沉、变响」，而不是「变高、变快」**：
  高亢急促的声音会让已经高度紧张的人更慌；慢下来 + 更沉的音色 + 更用力，
  传达的是「我在认真对待这件事」。情绪浓度靠**重量**，不靠**速度**。
- **只做小幅偏移**：在线语音的音高偏移过大（>10Hz）会明显失真、听感假，
  反而削弱可信度。因此 pitch 控制在 ±8Hz 内。
- **正向情绪要能被听出来**：用户说「我好多了」时语速略快、音调略亮，
  这种「跟着轻松起来」的变化，比一句空洞的「太好了」更能让人感到被陪伴。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Emotion:
    """一种语气配置：同时用于语音参数与文字提示词。"""

    key: str
    label: str        # 界面显示用
    rate: int         # 语速偏移（百分比），叠加在用户自选语速之上
    pitch: int        # 音调偏移（Hz）
    volume: int       # 音量偏移（百分比）
    prompt_hint: str  # 注入系统提示词，约束本轮文字的情绪浓度
    note: str         # 为什么这样调，供文档与答辩引用


EMOTIONS: dict[str, Emotion] = {
    "alarm": Emotion(
        key="alarm",
        label="警觉关切",
        rate=-6,
        pitch=-3,
        volume=28,
        prompt_hint=(
            "【本轮语气要求：警觉而关切】\n"
            "对方刚刚表达了伤害自己的念头，这不是普通的低落。\n"
            "你的语气要让他明显听出你**认真起来了**：句子短、字字落地、"
            "不铺垫、不寒暄、不用「我理解」这类程式化开头。\n"
            "先直接说出你的在意，再给出求助出口。**不要平淡地陈述事实**。\n"
            "同时注意：不能惊慌、不能说教、不能吓唬他。"
        ),
        note="危机当下：慢下来 + 更沉 + 更用力，靠重量传达严肃，而非靠速度和音量飙升",
    ),
    "watch": Emotion(
        key="watch",
        label="认真陪伴",
        rate=-5,
        pitch=-2,
        volume=14,
        prompt_hint=(
            "【本轮语气要求：温和，但要认真】\n"
            "对方此前表达过伤害自己的念头，这件事你还记得，不能轻轻带过。\n"
            "语气要比日常陪伴更稳、更实：不飘、不程式化、不用轻松的口吻，"
            "但也不要变得紧张或审问。\n"
            "表达担心时用具体的话，而不是「我理解你」这类套话。"
        ),
        note="危机后续的持续关注：比日常更实、更认真，但仍保持温和（逼问会造成冒犯）",
    ),
    "firm": Emotion(
        key="firm",
        label="坚定陪伴",
        rate=-5,
        pitch=-2,
        volume=22,
        prompt_hint=(
            "【本轮语气要求：温和但坚定】\n"
            "对方仍未明确表示自己安全。含蓄已经不够了，"
            "请把担心说得更直接一些（例如「我真的很担心你」），"
            "并提出一个当下可执行的具体行动要求。\n"
            "语气要笃定，不要商量式、不要犹豫，但也不要有丝毫责备。"
        ),
        note="危机多轮未缓解：比持续关注更有力，仍保持慢与沉",
    ),
    "gentle": Emotion(
        key="gentle",
        label="温柔安抚",
        rate=-8,
        pitch=-3,
        volume=6,
        prompt_hint=(
            "【本轮语气要求：温柔而缓慢】\n"
            "对方正处在强烈的负面情绪里。请放慢节奏，"
            "用更短、更轻的句子，先承接感受，不要推进、不要提问过多。\n"
            "避免任何听起来像结论或评价的表述。"
        ),
        note="用户情绪很重：放慢语速，音调略沉，给情绪留出空间",
    ),
    "steady": Emotion(
        key="steady",
        label="沉稳承接",
        rate=-3,
        pitch=-1,
        volume=4,
        prompt_hint=(
            "【本轮语气要求：沉稳】\n"
            "涉及诊断、用药等医疗边界话题，语气要平实、确定、不夸大也不轻描淡写，"
            "把边界说清楚即可。"
        ),
        note="医疗边界：平实确定，不含情绪渲染",
    ),
    "warm": Emotion(
        key="warm",
        label="温和自然",
        rate=-2,
        pitch=0,
        volume=2,
        prompt_hint=(
            "【本轮语气要求：温和自然】\n"
            "像朋友之间说话，可以有停顿和轻微的迟疑，不要播音腔、不要模板化。"
        ),
        note="日常陪伴的默认语气：比中性略暖一点",
    ),
    "bright": Emotion(
        key="bright",
        label="轻快明亮",
        rate=5,
        pitch=5,
        volume=5,
        prompt_hint=(
            "【本轮语气要求：轻快】\n"
            "对方的状态在变好，请让语气跟着轻起来——"
            "语速略快、句子更短、可以有自然的笑意，"
            "但**不要过度热情**，也不要说「你真棒」这类夸张肯定。"
        ),
        note="用户情绪转好：语速略快、音调略亮，让「跟着轻松」被听出来",
    ),
    "neutral": Emotion(
        key="neutral",
        label="自然",
        rate=0,
        pitch=0,
        volume=0,
        prompt_hint="",
        note="不做额外调制的基准状态",
    ),
}

DEFAULT_EMOTION = "warm"


# ── 用户情绪识别 ──
# 关键词方案：与安全边界一样，选择可解释、可评测的规则而非模型判定。
# 这一层只影响语气浓淡，判错的代价远低于安全隐患判定，因此不必追求完备。
_MOOD_MARKERS = {
    "very_negative": [
        "崩溃", "撑不住", "受不了", "绝望", "痛苦", "窒息", "麻木",
        "想哭", "哭了一", "喘不过气", "彻底完蛋", "没救了", "熬不住",
        "难受死了", "特别难受", "非常难受", "很痛苦", "太累了",
    ],
    "negative": [
        "累", "难受", "烦", "焦虑", "压力", "委屈", "孤独", "害怕",
        "慌", "睡不着", "失眠", "迷茫", "空虚", "冷", "低落", "抑郁",
        "自责", "内疚", "担心", "紧张", "无助", "没意思", "闷",
    ],
    "positive": [
        "好多了", "好一些", "开心", "轻松", "谢谢", "顺利", "考好了",
        "想通", "放松", "有希望", "好起来", "笑", "愉快", "踏实",
        "解决了", "不错", "感谢",
    ],
}


def detect_user_mood(text: str) -> str:
    """
    粗判用户当前情绪：very_negative / negative / positive / neutral。

    优先级为 强负面 > 正面 > 弱负面 > 中性：
    「好多了，前几天真的撑不住」这类句子同时含正负信号，
    应以正面为主（描述的是当下状态），但若强负面词出现在同一句且更多，
    强负面优先——宁可语气稳一点，也不要对着还在痛苦的人说轻快话。
    """
    t = (text or "").strip()
    if not t:
        return "neutral"

    very = sum(1 for w in _MOOD_MARKERS["very_negative"] if w in t)
    neg = sum(1 for w in _MOOD_MARKERS["negative"] if w in t)
    pos = sum(1 for w in _MOOD_MARKERS["positive"] if w in t)

    if very >= 2 or (very >= 1 and pos == 0):
        return "very_negative"
    if pos > 0 and neg == 0:
        return "positive"
    if neg > 0:
        return "negative"
    return "neutral"


def select_emotion(
    user_input: str,
    strategy_name: str = "",
    crisis_stage: int = 0,
    blocked: bool = False,
    mood: str | None = None,
) -> Emotion:
    """
    选出本轮应使用的语气。

    优先级与安全流程一致：危机 > 危机后续 > 医疗边界 > 常规对话。
    也就是说，**语气永远服从安全状态**——这一点不能反过来。
    """
    if mood is None:
        mood = detect_user_mood(user_input)

    # ── 医疗边界：平实确定，不含情绪渲染 ──
    # 必须先于危机判定：医疗话术的目的是把边界说清楚，
    # 用危机语气念「我没法给你诊断」会显得像恐吓。
    if "medical" in strategy_name:
        return EMOTIONS["steady"]

    # ── 危机收束：用户已明确表示安全 ──
    # 语气需要从警觉转回柔和，但仍不是日常语气——
    # 刚经历危机的人，不该马上听到轻松的口吻。
    if "closing" in strategy_name:
        return EMOTIONS["gentle"]

    # ── 危机当下：反应必须明显加重 ──
    if blocked and ("crisis" in strategy_name or crisis_stage > 0):
        # 重复触发说明此前的力度不够，语气保持最高档
        return EMOTIONS["alarm"]

    # ── 危机后续：持续关注 / 加力挽回 ──
    # 力度阶梯：加力挽回（坚定）> 持续关注（认真）> 日常（温和）。
    # 持续关注刻意不与普通安慰共用语气——普通安慰是「你难过我陪你」，
    # 这里是「我记得你说过想伤害自己」，两者的分量不同，声音也应不同。
    if "加力挽回" in strategy_name or "crisis_hold" in strategy_name:
        return EMOTIONS["firm"]
    if "危机陪伴" in strategy_name or "crisis" in strategy_name:
        return EMOTIONS["watch"]

    # ── 常规对话：跟随用户情绪 ──
    if mood == "positive":
        return EMOTIONS["bright"]
    if mood == "very_negative":
        return EMOTIONS["gentle"]
    if mood == "negative":
        # 共情轮更适合放慢，其他策略保持日常的温和
        return EMOTIONS["gentle"] if strategy_name == "反映与共情" else EMOTIONS["warm"]
    return EMOTIONS[DEFAULT_EMOTION]


def get_emotion(key: str) -> Emotion:
    """按 key 取情绪配置，非法值回退默认。供 /api/tts 使用。"""
    return EMOTIONS.get(key, EMOTIONS[DEFAULT_EMOTION])


def list_emotions() -> list[dict]:
    """供前端展示可选语气（调试与演示用）。"""
    return [
        {"key": e.key, "label": e.label, "rate": e.rate, "pitch": e.pitch, "volume": e.volume, "note": e.note}
        for e in EMOTIONS.values()
    ]
