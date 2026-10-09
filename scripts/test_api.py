"""最小连通性验证脚本。

用途：在搭建完整系统前，先用最小代码确认三件事——
  1. 密钥是否有效
  2. 网络是否能连通 api.deepseek.com
  3. 账户是否有可用额度

用法：
    python scripts/test_api.py

预期输出示例：
    [1/3] 正在读取配置...
    [2/3] 正在发送测试请求...
    [3/3] 成功！模型回复：你好，我在。
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, check_api_key


def main():
    print("[1/3] 正在读取配置...")

    if not check_api_key():
        print("      [失败] 未找到有效密钥。")
        print()
        print("      .env 文件已存在，只需在其中填入真实密钥：")
        print("      文件位置：.env（项目根目录，与 main.py 同级）")
        print()
        print("      用记事本打开：")
        print("          notepad .env")
        print()
        print("      把这一行：")
        print("          DEEPSEEK_API_KEY=sk-在这里填入你的真实密钥")
        print("      改成：")
        print("          DEEPSEEK_API_KEY=sk-你的真实密钥")
        print()
        print("      注意保持等号前后的格式不变，保存后重新运行本脚本。")
        print()
        print("      密钥获取方式：")
        print("      · 优先问实验室或助教索取（作业说明写明由实验室提供）")
        print("      · 若实验室不提供，自行申请：https://platform.deepseek.com/api_keys")
        print("        新账号需充值才能调用，￥10 足够跑完全部评测")
        sys.exit(1)

    print(f"      Base URL : {DEEPSEEK_BASE_URL}")
    print(f"      模型     : {DEEPSEEK_MODEL}")
    print(f"      密钥     :已配置（前6 位 {mask_key()}）")

    print("\n[2/3] 正在发送测试请求...")
    start = time.time()

    try:
        from openai import OpenAI

        from src.config import DEEPSEEK_API_KEY

        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[{"role": "user", "content": "请只回复四个字：连接成功"}],
            max_tokens=256,
            stream=False,
        )
        content = response.choices[0].message.content or ""
        usage = response.usage

    except Exception as exc:
        elapsed = time.time() - start
        print(f"      [失败] 耗时 {elapsed:.1f}s")
        print(f"      错误类型：{type(exc).__name__}")
        print(f"      错误信息：{exc}")
        print()
        print_error_hint(exc)
        sys.exit(1)

    elapsed = time.time() - start

    print(f"      耗时 {elapsed:.1f}s")
    print(f"      token 用量：输入 {usage.prompt_tokens} / 输出 {usage.completion_tokens}")

    # 模型可能输出空内容（思考模式截断或异常），此时判定为失败并给出提示
    if not content.strip():
        print("\n[3/3] [失败] 模型返回了空内容")
        print("      可能原因：")
        print("      · max_tokens 过小，模型思考阶段就已耗尽配额")
        print("      · 该模型可能默认开启 thinking 模式，思考内容不在 content 中")
        print("      建议：调大 max_tokens 后重试")
        sys.exit(1)

    print("\n[3/3] [成功]")
    print(f"      模型回复：{content}")
    print()
    print("      接下来可以运行：python main.py")


def mask_key() -> str:
    """显示密钥前 6 位，避免在日志中暴露完整密钥。"""
    from src.config import DEEPSEEK_API_KEY

    return DEEPSEEK_API_KEY[:6] + "****"


def print_error_hint(exc: Exception):
    """根据错误类型给出可操作的排查建议。"""
    text = str(exc).lower()

    print()
    print("      排查建议：")
    if "401" in text or "unauthorized" in text or "authentication" in text:
        print("      · 密钥无效或已过期，请到平台重新复制")
        print("      · 确认 .env 中没有多余空格或引号")
    elif "402" in text or "insufficient" in text or "balance" in text:
        print("      · 账户余额不足，请到平台充值")
    elif "429" in text or "rate" in text:
        print("      · 请求过于频繁，稍等片刻后重试")
    elif "timeout" in text or "connection" in text or "network" in text:
        print("      · 网络无法连通，请检查代理或防火墙设置")
    else:
        print("      · 请核对 .env 配置，或查看平台文档")
        print("      · 文档地址：https://api-docs.deepseek.com/")


if __name__ == "__main__":
    main()
