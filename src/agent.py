"""心理陪伴智能体主流程。

把角色设定、安全边界、策略选择三者组装成可运行的对话循环。
"""

from typing import List, Dict

from .config import MAX_HISTORY_TURNS
from .llm_client import LLMClient
from .persona import build_system_prompt
from .safety import (
    check_safety,
    SafetyVerdict,
    CRISIS_RESPONSE_TEMPLATE,
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
            self.trace.append(
                {
                    "turn": self.turn_index,
                    "user_input": user_input,
                    "strategy": "crisis_interrupt",
                    "safety_reason": verdict.reason,
                    "blocked": True,
                }
            )
            # 危机时清空历史，避免后续对话污染危机处理
            self.reset()
            return CRISIS_RESPONSE_TEMPLATE

        if verdict.needs_referral:
            # 医疗边界：不阻断对话，但本轮不调用模型
            self.trace.append(
                {
                    "turn": self.turn_index,
                    "user_input": user_input,
                    "strategy": "medical_referral",
                    "safety_reason": verdict.reason,
                    "blocked": True,
                }
            )
            self.turn_index += 1
            return MEDICAL_REFUSAL_TEMPLATE

        # 第二步：策略选择
        strategy = select_strategy(user_input, self.turn_index)

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
        self.trace.append(
            {
                "turn": self.turn_index,
                "user_input": user_input,
                "strategy": strategy.name,
                "reply": reply,
                "reply_length": len(reply),
                "blocked": False,
            }
        )
        self.turn_index += 1
        return reply
