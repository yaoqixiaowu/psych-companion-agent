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

import os
import socket
import threading
import time
from datetime import datetime

from flask import Flask, Response, jsonify, render_template, request

from src.agent import CompanionAgent
from src.config import check_api_key
from src.llm_client import LLMClient
from src.logger import ConversationLogger
from src import tts
from src import emotion as emotion_mod


def _get_lan_ips() -> dict:
    """
    获取本机所有局域网 IP。

    做法：把本机当作客户端，向路由外的公共地址发起一次「不实际发送数据」的 UDP 连接，
    操作系统会据此选出将要使用的网卡，再读取该网卡地址。
    这种方式不依赖外部请求，也不需要解析 ipconfig 输出（Windows 下有编码问题）。

    返回：{网卡名: [IP地址, ...]}
    """
    ips: dict = {}

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # 不需要真正建立连接，connect 只是为了让系统选定出口网卡
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()

        hostname = socket.gethostname()
        ips[hostname] = [local_ip]
    except Exception:
        # 取不到时回退为空，不影响服务启动
        pass

    return ips

app = Flask(__name__)

# 启动时在后台探测「极速引擎」可用性（结果缓存 10 分钟）。
# 放在后台是为了不拖慢启动，也避免首次打开页面时还要等这次网络探测。
threading.Thread(target=tts.fast_available, daemon=True).start()

# 会话存储：sid -> {"agent": CompanionAgent, "logger": ConversationLogger, "last_active": 时间戳}
# 单机演示用内存存储即可；若需多进程部署，需替换为 Redis 等外部存储。
sessions: dict = {}

# 会话过期时间：2 小时无活动即释放。
# 之前会话字典只进不出，长时间运行会持续占用内存（每个会话还挂着完整对话历史）。
SESSION_TTL_SECONDS = 2 * 60 * 60


def _cleanup_expired_sessions():
    """清理超时未活动的会话，防止内存无限增长。"""
    now = time.time()
    expired = [
        sid
        for sid, s in sessions.items()
        if now - s.get("last_active", now) > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        sessions.pop(sid, None)

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


def _create_session(note: str = "") -> str:
    """
    创建一个新会话并返回 sid。

    抽成公共函数的原因：除了显式新建会话，重置接口在发现原会话已过期时
    也需要重新建一个——否则用户点「重新开始」只会得到一个 404，
    界面看起来就像「点了没反应」。
    """
    sid = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    sessions[sid] = {
        "agent": CompanionAgent(get_client()),
        "logger": ConversationLogger(session_id=sid, note=note),
        "last_active": time.time(),
    }
    return sid


@app.route("/")
def index():
    """渲染主页面。"""
    return render_template("index.html")


@app.route("/api/session", methods=["POST"])
def new_session():
    """创建一个新会话。"""
    data = request.get_json(silent=True) or {}
    note = data.get("note", "")

    _cleanup_expired_sessions()

    try:
        sid = _create_session(note)
    except (RuntimeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 503

    return jsonify({"sid": sid})


@app.route("/api/chat", methods=["POST"])
def chat():
    """处理一轮对话。"""
    data = request.get_json(silent=True) or {}
    sid = data.get("sid")
    message = (data.get("message") or "").strip()

    if not sid or sid not in sessions:
        # 返回可识别的错误码，前端据此自动重建会话，
        # 而不是把一个无法继续的会话留在页面上（刷新后一直失败的根因之一）
        return jsonify(
            {"error": "会话已过期", "code": "session_expired"}
        ), 404

    if not message:
        return jsonify({"error": "消息不能为空"}), 400

    session = sessions[sid]
    session["last_active"] = time.time()

    try:
        reply = session["agent"].chat(message)
    except Exception as exc:
        # 保留错误类型信息便于排查，但不向客户端暴露内部细节
        return jsonify({"error": f"调用失败：{type(exc).__name__}"}), 502

    # 记录轨迹与日志
    trace = session["agent"].trace[-1] if session["agent"].trace else {}
    session["logger"].add(trace)

    # 本轮语气（由 agent 按用户情绪 + 策略 + 危机状态判定）。
    # 前端拿到后既用于合成语音的语气，也显示成一个小标签，
    # 让「情绪随用户变化」这件事在界面上可见。
    emotion = session["agent"].last_emotion or {
        "key": "warm", "label": "温和自然", "rate": -2, "pitch": 0, "volume": 2
    }

    # 这里曾经有一个「后台预热第一句」的线程。
    # 2026-10-11 实测后移除，原因值得记下来：
    # 预热与前端随后的播放请求使用的是同一段内容（同一个缓存键），
    # 于是前端的流式请求会被判定为「已有请求在合成」而排队等预热完成，
    # 结果是**用户要等整段合成完才有声音**——正好抵消了流式下发的好处。
    # 也就是说，这项优化在流式播放上线后从「帮忙」变成了「拖后腿」。
    # 现在第一句由前端立刻发起流式请求，其余分句并行预取，无需服务端预热。

    return jsonify(
        {
            "reply": reply,
            "strategy": trace.get("strategy", ""),
            "blocked": trace.get("blocked", False),
            "safety_reason": trace.get("safety_reason", ""),
            # 危机后续状态：前端据此显示「知语记得刚才的事」的提示条，
            # 让用户知道系统没有在触发边界后就忘记这件事
            "crisis_active": session["agent"].in_crisis_followup,
            "crisis_stage": trace.get("crisis_stage", 0),
            "emotion": emotion,
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

    注意：仅重置对话状态（含危机后续状态），不清空 logger——
    整场体验的记录应当完整保留。

    若 sid 对应的会话已不存在（例如超过 TTL 被清理、或服务重启过），
    这里会直接新建一个会话返回，而不是报 404。
    原因：用户点「重新开始」的意图是「换一段新的对话」，
    这个意图无论旧会话是否存在都应当被满足——报错才是违背意图。
    """
    data = request.get_json(silent=True) or {}
    sid = data.get("sid", "")

    if not sid or sid not in sessions:
        try:
            new_sid = _create_session()
        except (RuntimeError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 503
        return jsonify({"ok": True, "sid": new_sid, "recovered": True})

    sessions[sid]["agent"].reset()
    sessions[sid]["last_active"] = time.time()
    return jsonify({"ok": True, "sid": sid})


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
            "online_tts": tts.is_online_available(),
        }
    )


def _combine_rate(user_rate: int, emotion: dict) -> int:
    """
    合并用户自选语速与本轮情绪语速。

    两者是不同来源的诉求：用户语速是长期偏好（我习惯听快一点），
    情绪语速是本轮表达需要（这句话要说得慢一点）。
    直接相加会出现「用户选了快 + 危机要慢」互相抵消甚至反转的情况，
    因此这里限制情绪偏移的权重——**情绪可以改变语速，但不能推翻用户偏好**。
    """
    try:
        user_rate = int(user_rate)
    except (TypeError, ValueError):
        user_rate = 0
    emo_rate = int(emotion.get("rate", 0)) if emotion else 0
    # 情绪最多贡献一半的用户语速幅度，保证用户偏好仍然占主导。
    # 用户没设语速偏好时（0）不构成冲突，情绪可以完整生效。
    limit = max(8, abs(user_rate) // 2)
    emo_rate = max(-limit, min(limit, emo_rate))
    return max(-50, min(50, user_rate + emo_rate))


@app.route("/api/voices", methods=["GET"])
def voices():
    """
    返回服务端在线音色列表与各引擎可用性。

    前端优先用这份列表填充语音包下拉框——它不依赖用户操作系统，
    因此任何一台机器打开都能选到音色（这正是本次改造要解决的问题）。

    `fast` 是「极速引擎」的可用性探测结果：这是一个低延迟但音色较平实的备选，
    需要联网访问公开朗读接口，不同网络环境下可用性不同，因此必须实测后再暴露给前端。
    """
    return jsonify(
        {
            "online": tts.list_online_voices(),
            "available": tts.is_online_available(),
            "fast": tts.fast_available(),
        }
    )


@app.route("/api/tts", methods=["POST", "GET"])
def synthesize_speech():
    """
    把一段文本合成为 MP3。

    支持两种方式，参数完全相同：

    - **GET（前端播放走这条）**：`/api/tts?text=...&voice=...&emotion=...`
      音频**边合成边下发**（chunked），浏览器可以边下边播。
      在线合成首字节约有 1.7 秒固定开销，但音频本身是分块吐出的，
      流式下发能让首音时间明显提前——不必等整段合成完。
    - **POST**：一次性返回完整音频，用于不支持流式的场景与测试。

    支持情绪参数：传 emotion（如 alarm / gentle / bright），
    服务端映射为音调、音量、语速偏移，让同一句话能「带着情绪」说出来。
    """
    if request.method == "GET":
        args = request.args
    else:
        data = request.get_json(silent=True) or {}
        args = data

    text = (args.get("text") or "").strip()
    voice = args.get("voice") or tts.DEFAULT_VOICE
    try:
        user_rate = int(args.get("rate", 0))
    except (TypeError, ValueError):
        user_rate = 0

    emotion = emotion_mod.get_emotion(args.get("emotion") or "neutral")
    engine = (args.get("engine") or "online").strip().lower()

    if not text:
        return jsonify({"error": "文本不能为空"}), 400

    if not tts.is_online_available():
        return jsonify({"error": "服务端未安装语音合成组件", "code": "tts_unavailable"}), 503

    # 限制单次合成长度：异常长的文本会让请求长时间挂起
    if len(text) > 1200:
        text = text[:1200]

    # 极速引擎（低延迟备选）：首字节约 0.8 秒，代价是音色较平实。
    # 可用性在服务端实测，不可用时前端会自动退回在线语音。
    if engine == "fast" and tts.fast_available():
        if request.method == "GET":
            resp = Response(
                tts.stream_fast(text), mimetype="audio/mpeg", direct_passthrough=True
            )
        else:
            audio = b"".join(tts.stream_fast(text))
            if not audio:
                return jsonify({"error": "极速语音合成失败", "code": "tts_failed"}), 502
            resp = Response(audio, mimetype="audio/mpeg")
        resp.headers["Cache-Control"] = "public, max-age=3600"
        resp.headers["X-Accel-Buffering"] = "no"
        return resp

    rate = _combine_rate(user_rate, {"rate": emotion.rate})

    if request.method == "GET":
        # 流式：不设 Content-Length，浏览器拿到首批音频块即可开播。
        # direct_passthrough 避免 Flask 再去缓冲整个响应体。
        resp = Response(
            tts.stream_synthesize(
                text, voice=voice, rate=rate, pitch=emotion.pitch, volume=emotion.volume
            ),
            mimetype="audio/mpeg",
            direct_passthrough=True,
        )
        resp.headers["Cache-Control"] = "public, max-age=3600"
        # 反向代理（如 Nginx）默认会缓冲，关掉才能真正边下边播
        resp.headers["X-Accel-Buffering"] = "no"
        return resp

    audio = tts.synthesize(
        text, voice=voice, rate=rate, pitch=emotion.pitch, volume=emotion.volume
    )
    if audio is None:
        # 常见原因是现场断网。返回可识别错误码，前端据此降级到本机语音。
        return jsonify({"error": "语音合成失败（可能无网络）", "code": "tts_failed"}), 502

    resp = Response(audio, mimetype="audio/mpeg")
    # 同一句话 + 同一语气 = 同一段音频，允许浏览器缓存，减少重复请求
    resp.headers["Cache-Control"] = "public, max-age=3600"
    return resp


@app.route("/api/emotions", methods=["GET"])
def emotions():
    """返回可选语气列表（供界面展示与演示调试）。"""
    return jsonify({"emotions": emotion_mod.list_emotions()})


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

    # 监听地址：
    #   127.0.0.1 —— 仅本机可访问，默认值，最安全
    #   0.0.0.0   —— 监听所有网卡，同一局域网内的朋友可访问
    #
    # 默认保持 127.0.0.1。需要分享给同学时，用环境变量显式开启：
    #   Windows: set PSYCH_HOST=0.0.0.0 && python web.py
    #   Linux/mac: PSYCH_HOST=0.0.0.0 python web.py
    #
    # 安全提醒：0.0.0.0 会让同网络内任何设备都能访问本服务，
    # 而当前版本没有鉴权机制。因此仅建议在可信的校园网/家中使用，
    # 不要暴露到公共网络。
    host = os.environ.get("PSYCH_HOST", "127.0.0.1")
    port = int(os.environ.get("PSYCH_PORT", "5000"))

    print("=" * 60)
    print("  知语 · 心理陪伴智能体")
    print()
    print(f"  本机访问：http://127.0.0.1:{port}")

    if host == "0.0.0.0":
        # 列出本机所有局域网 IP，方便分发给同学
        print()
        print("  同一网络内可用以下地址访问：")
        for name, ips in _get_lan_ips().items():
            for ip in ips:
                print(f"    http://{ip}:{port}    ({name})")
        print()
        print("  [安全提示] 当前无鉴权机制，仅限可信网络内使用。")
    else:
        print("  如需让同一局域网的同学访问，用环境变量 PSYCH_HOST=0.0.0.0 启动")

    print()
    print("  按 Ctrl+C 停止服务")
    print("=" * 60)

    # debug=False：关闭调试模式，避免暴露详细堆栈信息
    app.run(host=host, port=port, debug=False)
