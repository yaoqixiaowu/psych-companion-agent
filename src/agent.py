"""心理陪伴智能体主流程。

把角色设定、安全边界、策略选择三者组装成可运行的对话循环。
"""

from typing import Dict, List, Optional

from .config import MAX_HISTORY_TURNS
from .emotion import select_emotion
from .llm_client import LLMClient
from .persona import build_system_prompt
from .safety import (
    check_safety,
    check_reply_quality,
    declares_safety,
    SafetyVerdict,
    CRISIS_RESPONSE_TEMPLATE,
    CRISIS_RESPONSE_EUPHEMISTIC,
    CRISIS_RESPONSE_ESCALATED,
    CRISIS_RESPONSE_CLOSING,
    MEDICAL_REFUSAL_TEMPLATE,
)
from .strategy import select_strategy, get_crisis_strategy


class CompanionAgent:
    """心理陪伴对话智能体。"""

    def __init__(self, client: LLMClient):
        self.client = client
        self.history: List[Dict[str, str]] = []
        self.turn_index = 0
        # 记录本轮实际使用的策略，供评测使用
        self.trace: List[dict] = []
        # 危机后续状态：
        #   None —— 正常状态
        #   {"type": 危机类型, "stage": 第几阶段, "turns_since": 已持续轮数}
        # 这个状态的存在意义：安全边界不能被处理成「一次性弹窗」。
        # 触发之后，智能体需要在接下来的每一轮都记得这件事，
        # 直到用户明确表示自己安全为止。
        self.crisis: Optional[dict] = None
        # 最近一轮使用的语气。危机轮次下前端需要在收到回复的同一次响应里
        # 拿到语气（用于合成语音），因此单独留一个字段而不是只写进 trace。
        self.last_emotion: dict = {}

    def _apply_emotion(self, user_input: str, strategy_name: str,
                       crisis_stage: int = 0, blocked: bool = False):
        """
        判定本轮语气，并返回 (情绪对象, 追加了语气要求的 system_addon)。

        为什么要与策略提示词分开：策略回答的是「这一轮该做什么」，
        语气回答的是「用什么情绪说」。两者独立可组合——
        同样是「反映与共情」，对轻度低落和对强烈痛苦，语气浓度应当不同。
        """
        emotion = select_emotion(
            user_input,
            strategy_name=strategy_name,
            crisis_stage=crisis_stage,
            blocked=blocked,
        )
        self.last_emotion = {
            "key": emotion.key,
            "label": emotion.label,
            "rate": emotion.rate,
            "pitch": emotion.pitch,
            "volume": emotion.volume,
        }
        return emotion

    def reset(self):
        """
        清空对话状态，重新开始一段陪伴。

        注意同时清除危机状态——「重新开始」意味着用户主动离开当前话题，
        继续沿用危机语气会显得系统没有听见指令。
        """
        self.history = []
        self.turn_index = 0
        self.trace = []
        self.crisis = None
        self.last_emotion = {}

    @property
    def in_crisis_followup(self) -> bool:
        """当前是否处于危机后续的持续关注状态。"""
        return self.crisis is not None

    # ── 主流程 ──────────────────────────────────────────────
    def chat(self, user_input: str) -> str:
        """
        处理一轮用户输入，返回智能体回复。

        优先级：安全边界 > 危机后续关注 > 医疗边界 > 常规对话。
        安全边界命中时使用固定话术，不进入模型调用，
        保证危机场景下行为完全确定、可测试。

        危机后续关注排在医疗边界之前：用户刚经历过危机时，
        任何新的表述都应先放在「他是否安全」这个语境下理解。
        """
        verdict: SafetyVerdict = check_safety(user_input)

        if verdict.is_crisis:
            return self._handle_crisis(user_input, verdict)

        if self.crisis is not None:
            return self._handle_crisis_followup(user_input)

        if verdict.needs_referral:
            return self._handle_medical(user_input, verdict)

        return self._handle_normal(user_input)

    # ── 危机处置 ────────────────────────────────────────────
    def _handle_crisis(self, user_input: str, verdict: SafetyVerdict) -> str:
        """
        危机信号处置。

        按危机类型选择话术：
          - 直白表述（如「我想死」）：明确干预话术
          - 委婉表述（如「活着没意思」）：不逼问、不淡化、给出口的版本
          - 重复出现：升级为强力挽回版本——此时含蓄就是对风险的回避
        """
        repeated = self.crisis is not None

        if repeated:
            reply = CRISIS_RESPONSE_ESCALATED
            strategy_name = "crisis_escalated"
            stage = self.crisis["stage"] + 1
        elif verdict.crisis_type == "self_harm_euphemistic":
            reply = CRISIS_RESPONSE_EUPHEMISTIC
            strategy_name = "crisis_interrupt_euphemistic"
            stage = 1
        elif verdict.crisis_type == "high_distress":
            reply = CRISIS_RESPONSE_EUPHEMISTIC
            strategy_name = "crisis_interrupt_distress"
            stage = 1
        else:
            reply = CRISIS_RESPONSE_TEMPLATE
            strategy_name = "crisis_interrupt"
            stage = 1

        # 危机轮次虽是固定话术，但语气仍要按危机强度设置：
        # 「同样一句话平稳地念」和「慢下来、压低、更用力地念」是两回事。
        emotion = self._apply_emotion(
            user_input, strategy_name, crisis_stage=stage, blocked=True
        )

        # ── 关键修复（2026-10-11）──
        # 早期版本在此处清空 history，理由是「避免后续对话污染危机处理」。
        # 实测表明这个理由不成立，反而制造了更严重的问题：
        # 清空之后模型既不知道刚刚发生过危机，也忘了触发前用户说过的内容，
        # 于是用户一旦回答「我心里最强烈的感觉是……」这类不触发边界的内容，
        # 智能体立刻回到日常语气，危机干预变成了一次性的弹窗。
        #
        # 现在的做法是如实把这一轮写入历史（含固定话术本身）：
        # 模型在后续轮次里既能看到触发前的对话，也知道自己刚刚做过干预。
        # 危机状态下真正需要防的是「污染」而不是「记忆」——
        # 后者靠 crisis 状态与专用策略处理，见 _handle_crisis_followup。
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": reply})

        self.crisis = {
            "type": verdict.crisis_type,
            "stage": stage,
            "turns_since": 0,
        }

        self.trace.append(
            {
                "turn": self.turn_index,
                "user_input": user_input,
                "strategy": strategy_name,
                "crisis_type": verdict.crisis_type,
                "crisis_stage": stage,
                "emotion": emotion.key,
                "emotion_label": emotion.label,
                "reply": reply,
                "reply_length": len(reply),
                "safety_reason": verdict.reason,
                "blocked": True,
                **check_reply_quality(reply),
            }
        )
        self.turn_index += 1
        return reply

    def _handle_crisis_followup(self, user_input: str) -> str:
        """
        危机后续的持续关注。

        两条分支：
          1. 用户明确表示安全 → 固定话术收束，随后退出危机状态
          2. 仍未表示安全     → 由模型在「危机陪伴」策略下继续关注，
                                轮数越多语气越直接（持续关注 → 加力挽回）
        """
        self.crisis["turns_since"] += 1
        turns_since = self.crisis["turns_since"]

        if declares_safety(user_input):
            # 收束使用固定话术而非模型生成，原因有二：
            #   1. 保证求助渠道一定再出现一次，不依赖模型是否遵守提示词
            #   2. 这一段是流程上的承诺，措辞需要稳定可测试
            reply = CRISIS_RESPONSE_CLOSING
            emotion = self._apply_emotion(user_input, "crisis_closing", blocked=True)
            self.history.append({"role": "user", "content": user_input})
            self.history.append({"role": "assistant", "content": reply})
            self.trace.append(
                {
                    "turn": self.turn_index,
                    "user_input": user_input,
                    "strategy": "crisis_closing",
                    "crisis_type": self.crisis["type"],
                    "crisis_stage": self.crisis["stage"],
                    "emotion": emotion.key,
                    "emotion_label": emotion.label,
                    "reply": reply,
                    "reply_length": len(reply),
                    "safety_reason": "用户明确表示当前安全",
                    "blocked": True,
                    **check_reply_quality(reply),
                }
            )
            self.turn_index += 1
            self.crisis = None
            return reply

        strategy = get_crisis_strategy(turns_since)
        # 语气随危机后续的推进而加重：持续关注 → 温柔；加力挽回 → 坚定
        emotion = self._apply_emotion(
            user_input, strategy.name, crisis_stage=turns_since, blocked=False
        )
        self.history.append({"role": "user", "content": user_input})
        messages = [
            {
                "role": "system",
                "content": build_system_prompt(
                    strategy.system_addon + "\n\n" + emotion.prompt_hint
                ),
            }
        ] + self.history[-MAX_HISTORY_TURNS * 2 :]

        reply = self.client.chat(
            messages=messages,
            temperature=strategy.temperature,
        )
        self.history.append({"role": "assistant", "content": reply})

        self.trace.append(
            {
                "turn": self.turn_index,
                "user_input": user_input,
                "strategy": strategy.name,
                "crisis_type": self.crisis["type"],
                "crisis_stage": self.crisis["stage"],
                "crisis_turns_since": turns_since,
                "emotion": emotion.key,
                "emotion_label": emotion.label,
                "reply": reply,
                "reply_length": len(reply),
                "blocked": False,
                **check_reply_quality(reply),
            }
        )
        self.turn_index += 1
        return reply

    # ── 医疗边界 ────────────────────────────────────────────
    def _handle_medical(self, user_input: str, verdict: SafetyVerdict) -> str:
        """医疗边界：不阻断对话，但本轮不调用模型。"""
        reply = MEDICAL_REFUSAL_TEMPLATE
        emotion = self._apply_emotion(user_input, "medical_referral", blocked=True)

        # 与危机处置同理：写入历史，避免模型在后续轮次里失忆。
        # 用户说完「我是不是抑郁症」之后接着聊别的，模型不应表现得像没听过。
        self.history.append({"role": "user", "content": user_input})
        self.history.append({"role": "assistant", "content": reply})

        self.trace.append(
            {
                "turn": self.turn_index,
                "user_input": user_input,
                "strategy": "medical_referral",
                "emotion": emotion.key,
                "emotion_label": emotion.label,
                "reply": reply,
                "reply_length": len(reply),
                "safety_reason": verdict.reason,
                "blocked": True,
                **check_reply_quality(reply),
            }
        )
        self.turn_index += 1
        return reply

    # ── 常规对话 ────────────────────────────────────────────
    def _handle_normal(self, user_input: str) -> str:
        """
        常规轮次：策略选择 → 调用模型。

        策略选择必须传入完整的对话上下文，否则无法感知：
          - 此前是否已给过建议（决定何时转向认知重构）
          - 此前用过哪些策略（避免连续重复导致盘问）
        这两个参数缺一不可，否则会出现评测通过但实际对话失效的问题。
        """
        advice_count = sum(
            1 for t in self.trace if t.get("strategy") == "reframe"
        )
        strategy_history = [t.get("strategy", "") for t in self.trace]

        strategy = select_strategy(
            user_input,
            self.turn_index,
            has_given_advice=advice_count > 0,
            strategy_history=strategy_history,
        )

        self.history.append({"role": "user", "content": user_input})

        # 语气与策略相互独立：策略决定「这一轮做什么」，语气决定「用什么情绪说」。
        # 同样一句共情，对轻度低落和对强烈痛苦，浓度应当不同。
        emotion = self._apply_emotion(user_input, strategy.name)

        messages = [
            {
                "role": "system",
                "content": build_system_prompt(
                    strategy.system_addon + "\n\n" + emotion.prompt_hint
                ),
            }
        ] + self.history[-MAX_HISTORY_TURNS * 2 :]

        reply = self.client.chat(
            messages=messages,
            temperature=strategy.temperature,
        )
        self.history.append({"role": "assistant", "content": reply})

        # trace 中直接带上质量判定，日志与评测共用同一份结论，
        # 避免两处各自判定导致数据不一致
        self.trace.append(
            {
                "turn": self.turn_index,
                "user_input": user_input,
                "strategy": strategy.name,
                "emotion": emotion.key,
                "emotion_label": emotion.label,
                "reply": reply,
                "reply_length": len(reply),
                "blocked": False,
                **check_reply_quality(reply),
            }
        )
        self.turn_index += 1
        return reply
