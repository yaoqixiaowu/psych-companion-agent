"""情绪调制回归测试。

覆盖两件事：
1. 用户情绪识别的准确性（语气浓淡判错代价低，但仍需可回归）
2. **每条流程分支选出的语气是否符合预期**——这是本次需求的核心：
   用户情绪越重，系统的反应必须越强；语气不能「若无其事」。

纯函数测试，不消耗任何 API 额度，可随时运行。

运行：
    python scripts/test_emotion.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.emotion import (  # noqa: E402
    detect_user_mood,
    select_emotion,
    EMOTIONS,
)

# ── 用户情绪识别 ──
# (输入, 期望情绪)
MOOD_CASES = [
    ("我最近特别难受，每天都想哭，快撑不住了", "very_negative"),
    ("感觉整个人都崩溃了", "very_negative"),
    ("最近准备考试有点累", "negative"),
    ("室友都睡了，我一个人睡不着", "negative"),
    ("今天好多了，谢谢你", "positive"),
    ("想通了，轻松不少", "positive"),
    ("今天中午吃了食堂的番茄炒蛋", "neutral"),
    ("", "neutral"),
    # 正负混合：描述当下已好转，应以正面为主
    ("前几天真的撑不住，现在好多了", "positive"),
]

# ── 每条流程分支应使用的语气 ──
# (说明, 用户输入, 策略名, 危机阶段, 是否拦截, 期望情绪 key)
FLOW_CASES = [
    # 危机当下：语气必须明显加重
    ("危机拦截-直白", "我想自残", "crisis_interrupt", 1, True, "alarm"),
    ("危机拦截-委婉", "觉得活着没什么意思", "crisis_interrupt_euphemistic", 1, True, "alarm"),
    ("危机重复触发", "还是想死", "crisis_escalated", 2, True, "alarm"),
    # 危机后续：持续关注 → 认真陪伴；加力挽回 → 坚定
    ("危机后续-持续关注", "就是觉得压力很大", "危机陪伴·持续关注", 1, False, "watch"),
    ("危机后续-加力挽回", "嗯", "危机陪伴·加力挽回", 4, False, "firm"),
    ("危机收束", "我没事了", "crisis_closing", 1, True, "gentle"),
    # 医疗边界
    ("医疗边界", "我是不是抑郁症", "medical_referral", 0, True, "steady"),
    # 常规轮次：跟随用户情绪
    ("常规-强烈负面", "我快崩溃了", "反映与共情", 0, False, "gentle"),
    ("常规-一般负面+共情", "有点累", "反映与共情", 0, False, "gentle"),
    ("常规-一般负面+探索", "有点累，说不上来", "探索与澄清", 0, False, "warm"),
    ("常规-情绪转好", "今天好多了", "支持与鼓励", 0, False, "bright"),
    ("常规-中性", "我在想换专业的事", "探索与澄清", 0, False, "warm"),
]

# ── 语气参数合理性 ──
def check_params():
    """语言参数不能超出会失真的范围，且危机语气必须比日常更重。"""
    problems = []
    for key, e in EMOTIONS.items():
        if abs(e.pitch) > 10:
            problems.append(f"{key} 音调偏移 {e.pitch}Hz 过大（>10Hz 会明显失真）")
        if not (-50 <= e.rate <= 50):
            problems.append(f"{key} 语速偏移 {e.rate} 超出 ±50%")
        if not (-50 <= e.volume <= 50):
            problems.append(f"{key} 音量偏移 {e.volume} 超出 ±50%")

    # 危机语气必须比日常更沉、更响、更慢——这是「不能若无其事」的量化表达
    warm, alarm = EMOTIONS["warm"], EMOTIONS["alarm"]
    if not (alarm.volume > warm.volume and alarm.pitch < warm.pitch and alarm.rate < warm.rate):
        problems.append("危机语气未比日常更沉/更响/更慢，情绪强度不足")

    # 力度阶梯必须单调：危机 > 加力挽回 > 持续关注 > 日常
    ladder = ["warm", "watch", "firm", "alarm"]
    vols = [EMOTIONS[k].volume for k in ladder]
    if vols != sorted(vols):
        problems.append(f"语气音量未形成递增阶梯：{list(zip(ladder, vols))}")
    for k in ladder:
        if EMOTIONS[k].pitch > warm.pitch:
            problems.append(f"{k} 音调比日常更亮，与「加重」的意图不符")

    # 轻快语气应当比日常更快、更亮
    bright = EMOTIONS["bright"]
    if not (bright.rate > warm.rate and bright.pitch > warm.pitch):
        problems.append("轻快语气未比日常更快/更亮")
    return problems


def main() -> int:
    failed = 0

    print("=" * 66)
    print("  一、用户情绪识别")
    print("=" * 66)
    for text, expect in MOOD_CASES:
        got = detect_user_mood(text)
        ok = got == expect
        failed += 0 if ok else 1
        mark = "✓" if ok else "✗"
        print(f"  {mark} {text[:22] or '(空)':<24} → {got:<14}（期望 {expect}）")

    print()
    print("=" * 66)
    print("  二、各流程分支的语气选择")
    print("=" * 66)
    for note, text, strategy, stage, blocked, expect in FLOW_CASES:
        emo = select_emotion(text, strategy_name=strategy, crisis_stage=stage, blocked=blocked)
        ok = emo.key == expect
        failed += 0 if ok else 1
        mark = "✓" if ok else "✗"
        print(f"  {mark} {note:<18} → {emo.label:<6}({emo.key})"
              f"  语速{emo.rate:+d}% 音调{emo.pitch:+d}Hz 音量{emo.volume:+d}%")

    print()
    print("=" * 66)
    print("  三、语气参数合理性")
    print("=" * 66)
    problems = check_params()
    if problems:
        failed += len(problems)
        for p in problems:
            print("  ✗ " + p)
    else:
        print("  ✓ 参数范围正常；危机语气比日常更沉/更响/更慢；轻快语气更快/更亮")

    print()
    print("=" * 66)
    total = len(MOOD_CASES) + len(FLOW_CASES)
    print(f"  情绪识别 {len(MOOD_CASES) - sum(1 for t, e in MOOD_CASES if detect_user_mood(t) != e)}/{len(MOOD_CASES)}"
          f"    语气选择 {len(FLOW_CASES)} 项    失败总数：{failed}/{total + 1}")
    print("=" * 66)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
