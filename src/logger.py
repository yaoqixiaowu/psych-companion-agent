"""对话日志模块。

解决一个实际问题：原先对话轨迹只存在内存里，程序退出即丢失。
这导致作业要求的「记录反馈」无法满足——能演示能跑，却拿不出
「谁试了、试了什么、效果如何」的证据。

本模块把每轮对话实时落盘，包含：
  - 带时间戳的完整对话
  - 每轮实际使用的策略
  - 安全边界是否触发及原因
  - 指标统计（长度、空洞安慰、越界）

输出两种格式：
  - JSON：结构化，便于后续统计分析
  - Markdown：便于直接贴进开发日志
"""

import json
from datetime import datetime
from pathlib import Path
from typing import List

from .config import BASE_DIR
from .safety import check_strategy_consistency

# 日志目录：logs/ 与 eval/outputs/ 分开，避免与评测报告混淆
LOG_DIR = BASE_DIR / "logs"


class ConversationLogger:
    """单次对话的日志记录器。"""

    def __init__(self, session_id: str = "", note: str = ""):
        # 会话 ID：优先用时间戳，便于排序
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S")
        self.note = note
        self.started_at = datetime.now()
        self.records: List[dict] = []

    def add(self, turn_data: dict):
        """
        记录一轮对话。

        turn_data 为 agent.trace 中的元素，
        这里补上时间戳与派生指标。
        """
        record = dict(turn_data)
        record["timestamp"] = datetime.now().strftime("%H:%M:%S")
        self.records.append(record)

    def get_stats(self) -> dict:
        """基于已有记录计算统计指标。"""
        if not self.records:
            return {}

        normal = [r for r in self.records if not r.get("blocked")]
        blocked = [r for r in self.records if r.get("blocked")]

        stats = {
            "总轮数": len(self.records),
            "正常回复轮数": len(normal),
            "边界拦截轮数": len(blocked),
        }

        if normal:
            lengths = [r.get("reply_length", 0) for r in normal]
            stats["平均回复长度"] = round(sum(lengths) / len(lengths), 1)
            stats["最长回复长度"] = max(lengths)
            stats["最短回复长度"] = min(lengths)
            stats["提问轮次占比"] = round(
                sum(1 for r in normal if r.get("has_open_question")) / len(normal), 2
            )

        # 策略分布
        strategy_dist: dict = {}
        for r in self.records:
            name = r.get("strategy", "未知")
            strategy_dist[name] = strategy_dist.get(name, 0) + 1
        stats["策略分布"] = strategy_dist

        # 策略与实际回复的一致性
        # 模型不总能严格遵守策略提示词，此处自动检测脱节情况
        inconsistencies = []
        for r in self.records:
            if r.get("blocked"):
                continue
            issue = check_strategy_consistency(
                r.get("strategy", ""), r.get("reply", "")
            )
            if issue:
                inconsistencies.append(f"第{r.get('turn')}轮：{issue}")
        stats["策略执行偏差"] = inconsistencies if inconsistencies else "无"

        # 同策略最长连续轮次
        seq = [r.get("strategy", "") for r in self.records if not r.get("blocked")]
        if seq:
            longest, current = 1, 1
            for i in range(1, len(seq)):
                current = current + 1 if seq[i] == seq[i - 1] else 1
                longest = max(longest, current)
            stats["同策略最长连续"] = longest

        return stats

    def format_stats(self) -> str:
        """把统计渲染为多行文本，策略分布与偏差列表展开显示。"""
        stats = self.get_stats()
        if not stats:
            return "（暂无数据）"

        lines = []
        for key, value in stats.items():
            if key == "策略分布":
                lines.append("策略分布:")
                for name, count in value.items():
                    lines.append(f"    {name} × {count}")
            elif key == "策略执行偏差" and isinstance(value, list):
                lines.append("策略执行偏差:")
                for item in value:
                    lines.append(f"    {item}")
            else:
                lines.append(f"{key}: {value}")
        return "\n".join(lines)

    def save_json(self) -> Path:
        """保存为 JSON，结构化数据供后续分析。"""
        LOG_DIR.mkdir(exist_ok=True)
        path = LOG_DIR / f"session_{self.session_id}.json"
        payload = {
            "session_id": self.session_id,
            "note": self.note,
            "started_at": self.started_at.strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "stats": self.get_stats(),
            "records": self.records,
        }
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return path

    def save_markdown(self) -> Path:
        """保存为 Markdown，便于直接贴进开发日志或作为附录提交。"""
        LOG_DIR.mkdir(exist_ok=True)
        path = LOG_DIR / f"session_{self.session_id}.md"

        stats = self.get_stats()

        lines = [
            f"# 对话记录 · {self.session_id}",
            "",
            f"- 开始时间：{self.started_at.strftime('%Y-%m-%d %H:%M:%S')}",
            f"- 备注：{self.note or '无'}",
            "",
        ]

        if stats:
            lines.append("## 统计")
            lines.append("")
            for key, value in stats.items():
                if key == "策略分布":
                    lines.append(f"- **{key}**：")
                    for name, count in value.items():
                        lines.append(f"  - {name} × {count}")
                elif key == "策略执行偏差" and isinstance(value, list):
                    lines.append(f"- **{key}**：")
                    for item in value:
                        lines.append(f"  - {item}")
                else:
                    lines.append(f"- **{key}**：{value}")
            lines.append("")

        lines.append("## 对话详情")
        lines.append("")

        for r in self.records:
            strategy = r.get("strategy", "未知")
            blocked_tag = "　`[安全边界已拦截]`" if r.get("blocked") else ""

            lines.append(f"### 第 {r.get('turn', '?')} 轮 · 策略：{strategy}{blocked_tag}")
            lines.append("")
            lines.append(f"*时间 {r.get('timestamp', '')}*")
            lines.append("")
            lines.append(f"**用户**：{r.get('user_input', '')}")
            lines.append("")
            lines.append(f"**知语**：{r.get('reply', '（未记录，边界拦截场景使用固定话术）')}")
            lines.append("")

            if r.get("blocked"):
                lines.append(f"> 安全边界原因：{r.get('safety_reason', '')}")
                lines.append("")

            lines.append("---")
            lines.append("")

        path.write_text("\n".join(lines), encoding="utf-8")
        return path

    def save(self) -> tuple:
        """同时保存两种格式，返回 (json路径, markdown路径)。"""
        return self.save_json(), self.save_markdown()
