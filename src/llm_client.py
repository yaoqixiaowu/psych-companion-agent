"""DeepSeek API 客户端封装。

隔离底层 SDK 调用，上层只需关心「发消息、拿回复」。
"""

from typing import List, Dict

from openai import OpenAI

from .config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_MODEL,
    check_api_key,
)


class LLMClient:
    def __init__(self):
        if not check_api_key():
            raise ValueError(
                "未检测到有效的 DEEPSEEK_API_KEY。\n"
                "请在项目根目录创建 .env 文件，写入：\n"
                "    DEEPSEEK_API_KEY=sk-你的真实密钥\n"
                "密钥申请地址：https://platform.deepseek.com/api_keys"
            )
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
        )
        self.model = DEEPSEEK_MODEL

    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> str:
        """
        发送一轮对话，返回助手回复文本。

        关于 thinking 模式：deepseek-flash 默认开启思考模式，会额外返回
        reasoning_content 并计入输出 token。对心理陪伴场景而言，模型的推理
        过程对用户没有价值，反而增加成本与延迟，因此显式关闭。

        参数说明：
          thinking.type = "disabled" 关闭思考模式
          reasoning_effort 仅在开启思考时有意义，关闭时一并置为最低。
        """
        extra_body = {
            "thinking": {"type": "disabled"},
            "reasoning_effort": "low",
        }

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
            extra_body=extra_body,
        )

        content = response.choices[0].message.content

        # 兜底：若因配额耗尽等原因返回空内容，明确报错而非让上层拿到空串
        if not content or not content.strip():
            raise RuntimeError(
                "模型返回空内容。可能原因："
                "max_tokens 过小，或账户额度不足。"
                f"（finish_reason={response.choices[0].finish_reason}）"
            )

        return content
