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
        """发送一轮对话，返回助手回复文本。"""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        )
        return response.choices[0].message.content or ""
