"""Flask Web 服务端。

提供与命令行版本相同的心理陪伴能力，但通过浏览器访问。
核心逻辑完全复用 src.agent.CompanionAgent，不存在两套实现。

设计要点：
1. 每个会话独立持有自己的 CompanionAgent 实例，避免多人使用串扰
2. 危机场景下前端会以醒目样式呈现求助渠道，不做视觉弱化
3. 日志与命令行版共用同一套 ConversationLogger，便于统一分析

运行：
    python web.py
    浏览器打开 http://127.0.0.1:5000
"""

from datetime import datetime

from flask import Flask, jsonify, render_template, request

from src.agent import CompanionAgent
from src.config import check_api_key
from src.llm_client import LLMClient
from src.logger import ConversationLogger

app = Flask(__name__)

# 会话存储：sid -> {"agent": CompanionAgent, "logger": ConversationLogger}
# 单机演示用内存存储即可；若需多进程部署，需替换为 Redis 等外部存储。
sessions: dict = {}

# LLM 客户端复用同一实例，避免重复创建连接池。
# 但仅在密钥有效时创建，否则启动即报错无法给出友好提示。
_llm_client = None
_llm_error = None


def get_client() -> LLMClient:
    """获取或创建 LLM 客户端。"""
    global _llm_client, _llm_error
    if _llm_error:
        raise RuntimeError(_llm_error)
    if _llm_client is None:
        if not check_api_key():
            _llm_error = (
                "未检测到有效的 DEEPSEEK_API_KEY。"
                "请在项目根目录的 .env 文件中填入密钥。"
            )
            raise RuntimeError(_llm_error)
        _llm_client = LLMClient()
    return _llm_client


@app.route("/")
def index():
    """渲染主页面。"""
    return render_template("index.html")


@app.route("/api/session", methods=["POST"])
def new_session():
    """创建一个新会话。"""
    data = request.get_json(silent=True) or {}
    note = data.get("note", "")

    # 会话 ID 用时间戳即可，单机场景无需更复杂方案
    sid = datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    try:
        agent = CompanionAgent(get_client())
    except (RuntimeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 503

    sessions[sid] = {
        "agent": agent,
        "logger": ConversationLogger(session_id=sid, note=note),
    }
    return jsonify({"sid": sid})


@app.route("/api/chat", methods=["POST"])
def chat():
    """处理一轮对话。"""
    data = request.get_json(silent=True) or {}
    sid = data.get("sid")
    message = (data.get("message") or "").strip()

    if not sid or sid not in sessions:
        return jsonify({"error": "会话不存在或已过期，请刷新页面重新开始"}), 404

    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    session = sessions[sid]

    try:
        reply = session["agent"].chat(message)
    except Exception as exc:
        # 保留错误类型信息便于排查，但不向客户端暴露内部细节
        return jsonify({"error": f"调用失败：{type(exc).__name__}"}), 502

    # 记录轨迹与日志
    trace = session["agent"].trace[-1] if session["agent"].trace else {}
    session["logger"].add(trace)

    return jsonify(
        {
            "reply": reply,
            "strategy": trace.get("strategy", ""),
            "blocked": trace.get("blocked", False),
            "safety_reason": trace.get("safety_reason", ""),
        }
    )


@app.route("/api/stats", methods=["GET"])
def stats():
    """返回当前会话的统计。"""
    sid = request.args.get("sid", "")
    if not sid or sid not in sessions:
        return jsonify({"error": "会话不存在"}), 404
    return jsonify(sessions[sid]["logger"].get_stats())


@app.route("/api/reset", methods=["POST"])
def reset():
    """
    重置会话。

    注意：仅重置对话上下文，不清空 logger——
    整场体验的记录应当完整保留。
    """
    data = request.get_json(silent=True) or {}
    sid = data.get("sid", "")
    if not sid or sid not in sessions:
        return jsonify({"error": "会话不存在"}), 404
    sessions[sid]["agent"].reset()
    return jsonify({"ok": True})


@app.route("/api/save", methods=["POST"])
def save_log():
    """保存当前会话的对话记录。"""
    data = request.get_json(silent=True) or {}
    sid = data.get("sid", "")
    note = data.get("note", "")
    if not sid or sid not in sessions:
        return jsonify({"error": "会话不存在"}), 404

    logger = sessions[sid]["logger"]
    if note:
        logger.note = note
    if not logger.records:
        return jsonify({"error": "本次还没有对话记录"}), 400

    try:
        json_path, md_path = logger.save()
    except Exception as exc:
        return jsonify({"error": f"保存失败：{type(exc).__name__}"}), 500

    return jsonify(
        {
            "md": str(md_path),
            "json": str(json_path),
            "stats": logger.get_stats(),
        }
    )


@app.route("/api/health")
def health():
    """健康检查，同时暴露密钥配置状态便于调试。"""
    return jsonify(
        {
            "status": "ok",
            "api_configured": check_api_key(),
            "sessions": len(sessions),
        }
    )


if __name__ == "__main__":
    if not check_api_key():
        print("=" * 60)
        print("  [错误] 未检测到 DEEPSEEK_API_KEY")
        print()
        print("  请在项目根目录创建 .env 文件，写入：")
        print("      DEEPSEEK_API_KEY=sk-你的真实密钥")
        print()
        print("  密钥申请：https://platform.deepseek.com/api_keys")
        print("=" * 60)
        raise SystemExit(1)

    print("=" * 60)
    print("  知语 · 心理陪伴智能体")
    print()
    print("  浏览器打开：http://127.0.0.1:5000")
    print("  按 Ctrl+C 停止服务")
    print("=" * 60)

    # debug=False：关闭调试模式，避免暴露详细堆栈信息
    # 端口 5000，被占用时自动尝试 5001、5002
    app.run(host="127.0.0.1", port=5000, debug=False)
