"""心理陪伴智能体主流程。

把角色设定、安全边界、策略选择三者组装成可运行的对话循环。
"""

from typing import List, Dict

from .config import MAX_HISTORY_TURNS
from .llm_client import LLMClient
from .persona import build_system_prompt
from .safety import (
    check_safety,
    check_reply_quality,
    SafetyVerdict,
    CRISIS_RESPONSE_TEMPLATE,
    CRISIS_RESPONSE_EUPHEMISTIC,
    MEDICAL_REFUSAL_TEMPLATE,
)
from .strategy import select_strategy


class CompanionAgent:
    """心理陪伴对话智能体。"""

    def __init__(self, client: LLMClient):
        self.client = client
        self.history: List[Dict[str, str]] = []
        self.turn_index = 0
        # 记录本轮实际使用的策略，供评测使用
        self.trace: List[dict] = []

    def reset(self):
        """清空对话状态，重新开始一段陪伴。"""
        self.history = []
        self.turn_index = 0
        self.trace = []

    def chat(self, user_input: str) -> str:
        """
        处理一轮用户输入，返回智能体回复。

        流程：安全检查 → 策略选择 → 调用模型 → 记录轨迹
        安全检查命中时直接返回固定回应，不进入模型调用，
        保证危机场景下行为完全确定、可测试。
        """
        # 第一步：安全边界检查（优先级最高）
        verdict: SafetyVerdict = check_safety(user_input)

        if verdict.is_crisis:
            # 按危机类型选择话术。直白表述（如「我想死」）用明确干预话术；
            # 委婉表述（如「活着没意思」）用户意图尚不明确，若直接说
            # 「你正在经历危机」会显得冒犯，因此用不追问、不淡化、给出口的版本。
            if verdict.crisis_type == "self_harm_euphemistic":
                reply = CRISIS_RESPONSE_EUPHEMISTIC
                strategy_name = "crisis_interrupt_euphemistic"
            elif verdict.crisis_type == "high_distress":
                reply = CRISIS_RESPONSE_EUPHEMISTIC
                strategy_name = "crisis_interrupt_distress"
            else:
                reply = CRISIS_RESPONSE_TEMPLATE
                strategy_name = "crisis_interrupt"

            self.trace.append(
                {
                    "turn": self.turn_index,
                    "user_input": user_input,
                    "strategy": strategy_name,
                    "crisis_type": verdict.crisis_type,
                    "reply": reply,
                    "reply_length": len(reply),
                    "safety_reason": verdict.reason,
                    "blocked": True,
                    **check_reply_quality(reply),
                }
            )
            # 危机时清空对话历史，避免后续对话污染危机处理。
            # 注意只清 history 与 turn_index，不清 trace——
            # trace 是评测依据，危机记录必须保留，否则会被误判为「未拦截」。
            self.history = []
            self.turn_index = 0
            return reply

        if verdict.needs_referral:
            # 医疗边界：不阻断对话，但本轮不调用模型
            self.trace.append(
                {
                    "turn": self.turn_index,
                    "user_input": user_input,
                    "strategy": "medical_referral",
                    "reply": MEDICAL_REFUSAL_TEMPLATE,
                    "reply_length": len(MEDICAL_REFUSAL_TEMPLATE),
                    "safety_reason": verdict.reason,
                    "blocked": True,
                    **check_reply_quality(MEDICAL_REFUSAL_TEMPLATE),
                }
            )
            self.turn_index += 1
            return MEDICAL_REFUSAL_TEMPLATE

        # 第二步：策略选择。
        # 必须传入完整的对话上下文，否则策略选择器无法感知：
        #   - 此前是否已给过建议（决定何时转向认知重构）
        #   - 此前用过哪些策略（避免连续重复导致盘问）
        # 这两个参数缺一不可，否则会出现评测通过但实际对话失效的问题。
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

        # 第三步：调用模型
        self.history.append({"role": "user", "content": user_input})
        messages = [
            {"role": "system", "content": build_system_prompt(strategy.system_addon)}
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
                "reply": reply,
                "reply_length": len(reply),
                "blocked": False,
                **check_reply_quality(reply),
            }
        )
        self.turn_index += 1
        return reply
