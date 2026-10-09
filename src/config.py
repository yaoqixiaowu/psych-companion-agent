"""配置加载：统一从环境变量读取，杜绝硬编码密钥。"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（src/ 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent

# 优先加载项目根目录下的 .env
load_dotenv(BASE_DIR / ".env")

DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")

# 对话窗口保留的最大轮数，兼顾成本与上下文连贯性
MAX_HISTORY_TURNS = 20


def check_api_key() -> bool:
    """校验密钥是否已配置。返回是否可用。"""
    if not DEEPSEEK_API_KEY:
        return False
    # 避免把占位符当成真实密钥
    if DEEPSEEK_API_KEY.startswith("sk-your") or len(DEEPSEEK_API_KEY) < 20:
        return False
    return True
