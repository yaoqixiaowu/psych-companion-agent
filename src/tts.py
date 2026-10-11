"""语音合成（TTS）模块。

## 为什么不只用浏览器自带的语音

浏览器的 Web Speech API 依赖「操作系统里已安装语音包」。
真实环境中这个前提经常不成立：精简版 Windows、Linux、部分浏览器
可能一个中文语音包都没有（本项目开发机就是这种情况），用户需要
自己进系统设置下载——对分享和答辩演示来说门槛太高。

因此这里改为**服务端合成**：调用微软 Edge 的在线语音服务
（通过 edge-tts 库），免费、无需申请密钥、中文音色自然。
用户端任何浏览器打开就有声音，不需要安装任何东西。

## 降级链（由前端实现）

    在线语音（默认，服务端合成）
      → 浏览器本机语音（离线可用，需系统装过语音包）
        → 都没有时给出明确提示

## 成本与依赖

- 不消耗 DeepSeek 额度，与对话 API 完全独立
- 需要联网（合成在微软云端完成）；离线场景自动落到本机语音
- 同一句话做内存缓存，重复朗读不必重复请求
"""

from __future__ import annotations

import asyncio
import queue
import re
import threading
import time
import urllib.parse
import urllib.request
from collections import OrderedDict

try:  # 允许缺失：没装 edge-tts 时服务仍能启动，只是没有在线语音
    import edge_tts

    _EDGE_TTS_OK = True
except Exception:  # pragma: no cover - 取决于运行环境
    edge_tts = None
    _EDGE_TTS_OK = False


# ── 可选音色 ──
# 只列中文音色：这是一个中文心理陪伴场景，列出英文音色只会干扰选择。
# desc 用中文描述音色特点，比让用户看 "Neural" 这种术语有用得多。
ONLINE_VOICES: list[dict] = [
    {"id": "zh-CN-XiaoxiaoNeural", "name": "晓晓", "lang": "普通话", "gender": "女", "desc": "温柔亲切（推荐）"},
    {"id": "zh-CN-XiaochenNeural", "name": "晓辰", "lang": "普通话", "gender": "女", "desc": "知性沉稳"},
    {"id": "zh-CN-XiaohanNeural", "name": "晓涵", "lang": "普通话", "gender": "女", "desc": "温暖柔和"},
    {"id": "zh-CN-XiaomengNeural", "name": "晓梦", "lang": "普通话", "gender": "女", "desc": "甜美轻盈"},
    {"id": "zh-CN-XiaoyiNeural", "name": "晓伊", "lang": "普通话", "gender": "女", "desc": "活泼明亮"},
    {"id": "zh-CN-YunxiNeural", "name": "云希", "lang": "普通话", "gender": "男", "desc": "阳光自然"},
    {"id": "zh-CN-YunjianNeural", "name": "云健", "lang": "普通话", "gender": "男", "desc": "低沉稳重"},
    {"id": "zh-CN-YunyangNeural", "name": "云扬", "lang": "普通话", "gender": "男", "desc": "播音质感"},
    {"id": "zh-HK-HiuMaanNeural", "name": "曉曼", "lang": "粤语", "gender": "女", "desc": "粤语女声"},
    {"id": "zh-TW-HsiaoChenNeural", "name": "曉臻", "lang": "台湾", "gender": "女", "desc": "台湾女声"},
    {"id": "zh-TW-HsiaoYuNeural", "name": "曉雨", "lang": "台湾", "gender": "女", "desc": "台湾女声·轻柔"},
]

DEFAULT_VOICE = ONLINE_VOICES[0]["id"]

_VALID_IDS = {v["id"] for v in ONLINE_VOICES}

# 合成缓存：同一句话（重新朗读、刷新页面）不必重复请求云端。
# 上限 64 条，超出按最久未使用淘汰——陪伴场景回复短，占用可忽略。
_CACHE: "OrderedDict[tuple, bytes]" = OrderedDict()
_CACHE_MAX = 64

_SYNTH_TIMEOUT = 20  # 秒；超时宁可没有声音，也不要卡住请求

# 正在合成中的 key -> Event，用于合并同一段内容的并发请求（见 synthesize 说明）
_PENDING: dict[tuple, threading.Event] = {}
_PENDING_LOCK = threading.Lock()


def is_online_available() -> bool:
    """在线语音是否可用（库已安装即可，实际能否合成取决于网络）。"""
    return _EDGE_TTS_OK


def list_online_voices() -> list[dict]:
    return ONLINE_VOICES


_MD_PATTERNS = [
    (re.compile(r"```.*?```", re.S), " "),      # 代码块
    (re.compile(r"`([^`]*)`"), r"\1"),           # 行内代码
    (re.compile(r"\*\*([^*]*)\*\*"), r"\1"),     # 粗体
    (re.compile(r"\*([^*]*)\*"), r"\1"),         # 斜体
    (re.compile(r"^#{1,6}\s*", re.M), ""),       # 标题符号
    (re.compile(r"^\s*[-*+]\s+", re.M), ""),     # 列表符号
    (re.compile(r"^\s*\d+\.\s+", re.M), ""),     # 有序列表
    (re.compile(r"\[([^\]]*)\]\([^)]*\)"), r"\1"),  # 链接
    (re.compile(r"[*#>`_~]"), ""),               # 残留标记符号
    (re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]"), ""),  # emoji
]


def split_sentences(text: str, min_len: int = 16) -> list[str]:
    """
    把回复拆成便于分场合使用的片段。

    当前服务端不再预热（预热已移除，原因见 web.py），此函数主要供
    测试与潜在的后续功能使用；实际送合成的前端拆分逻辑见
    `templates/index.html` 的 splitChunks，两者使用同一套句末标点。

    前端采用「两段式」拆分：第一段只取第一句保证尽快出声，
    剩余内容合并成一整段连续合成——逐句独立合成会让每句都
    「新起一个调型」，句间又有切换缝隙，听感一顿一顿像机器念字；
    合并后句间停顿完全交给标点，节奏与真人说话一致。
    """
    marks = "。！？!?；;"
    out: list[str] = []
    buf = ""
    for ch in text or "":
        if ch == "\n":
            if buf.strip():
                out.append(buf.strip())
            buf = ""
            continue
        buf += ch
        if ch in marks:
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())

    merged: list[str] = []
    for part in out:
        if merged and len(merged[-1]) < min_len:
            merged[-1] += part
        else:
            merged.append(part)
    return merged


def clean_for_speech(text: str) -> str:
    """
    把带 Markdown 的回复转成适合朗读的纯文本。

    必须做这一步：TTS 会把 "**" 念成「星号星号」，
    把列表符号念出来，把 emoji 念成奇怪的名字，听感很差。
    号码中的连字符保留（"010-82951332" 读作号码，不会被拆坏）。
    """
    out = text or ""
    for pattern, repl in _MD_PATTERNS:
        out = pattern.sub(repl, out)
    out = re.sub(r"\n{2,}", "。", out)   # 段落间停顿用句号更自然
    out = re.sub(r"\n", "，", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    # 列表符号被删掉后容易留下「。，」这类连续标点，朗读时会多一次停顿
    out = re.sub(r"[，。、；：,;:]{2,}", lambda m: m.group(0)[0], out)
    out = re.sub(r"\s+([，。、；：？！,.;:?!])", r"\1", out)
    out = re.sub(r"。{2,}", "。", out)
    return out.strip()


def _cache_get(key):
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    return None


def _cache_put(key, value):
    _CACHE[key] = value
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


async def _synth_async(text: str, voice: str, rate: int, pitch: int, volume: int) -> bytes:
    """调用在线语音服务合成。

    rate / pitch / volume 三个维度共同构成「语气」：
    音色决定是谁在说，这三个参数决定**用什么情绪在说**。
    """
    kwargs = {
        "rate": f"{rate:+d}%",
        "pitch": f"{pitch:+d}Hz",
        "volume": f"{volume:+d}%",
    }
    communicate = edge_tts.Communicate(text, voice, **kwargs)
    buf = bytearray()
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            buf.extend(chunk["data"])
    return bytes(buf)


def _clamp(value, low, high):
    try:
        value = int(value)
    except (TypeError, ValueError):
        value = 0
    return max(low, min(high, value))


def _resolve(text: str, voice: str, rate: int, pitch: int, volume: int):
    """把入参统一成「合法音色 + 夹取后的参数 + 清洗后的文本」。

    返回 None 表示无需合成（文本为空）。合成与流式两条路径共用这一层，
    保证两边的缓存键完全一致——否则同一句话会被当成两句各合成一次。
    """
    speech = clean_for_speech(text)
    if not speech:
        return None
    if voice not in _VALID_IDS:
        voice = DEFAULT_VOICE
    # 上限刻意收得比较紧：偏移过大（尤其音调）会明显失真，
    # 听感变假反而削弱可信度，与「情绪要更真」的目标相反。
    return (
        voice,
        _clamp(rate, -50, 50),
        _clamp(pitch, -12, 12),
        _clamp(volume, -50, 50),
        speech,
    )


def synthesize(
    text: str,
    voice: str = DEFAULT_VOICE,
    rate: int = 0,
    pitch: int = 0,
    volume: int = 0,
) -> bytes | None:
    """
    合成一段语音，返回 MP3 字节；失败返回 None（由调用方决定如何降级）。

    参数：
        text   —— 原始文本（内部会自动做朗读清洗）
        voice  —— 音色 id，非法值回退到默认音色
        rate   —— 语速偏移百分比，如 -15 / 0 / +15
        pitch  —— 音调偏移 Hz，如 -3 / 0 / +5
        volume —— 音量偏移百分比，如 +28 / 0

    刻意不抛异常：语音是锦上添花的能力，
    合成失败不应该让一次正常的对话请求变成报错。

    ## 为什么要做「同内容去重」

    对话接口会在返回回复时后台预热音频（把合成耗时藏进用户阅读回复的时间），
    随后前端马上请求同一段音频。两个请求可能同时到达，若不处理就会
    对同一句话发起两次云端合成——既浪费也互相抢带宽。
    因此这里用一把 key 锁：同内容已有合成在进行时，后来的请求等它的结果，
    而不是重复干活。等待方拿到的仍然是同一份缓存结果。

    注意缓存 key 必须包含 pitch/volume：同一句话用不同情绪念，
    是不同的音频，不能互相命中。
    """
    if not _EDGE_TTS_OK:
        return None

    resolved = _resolve(text, voice, rate, pitch, volume)
    if resolved is None:
        return None
    voice, rate, pitch, volume, speech = resolved

    key = (voice, rate, pitch, volume, speech)
    cached = _cache_get(key)
    if cached is not None:
        return cached

    with _PENDING_LOCK:
        event = _PENDING.get(key)
        if event is None:
            event = threading.Event()
            _PENDING[key] = event
            owner = True
        else:
            owner = False

    if not owner:
        # 别人正在合成同一段内容：等它做完，直接取结果
        event.wait(timeout=_SYNTH_TIMEOUT + 5)
        return _cache_get(key)

    try:
        audio = asyncio.run(
            asyncio.wait_for(
                _synth_async(speech, voice, rate, pitch, volume),
                timeout=_SYNTH_TIMEOUT,
            )
        )
    except Exception:
        return None
    finally:
        with _PENDING_LOCK:
            _PENDING.pop(key, None)
        event.set()

    if not audio:
        return None

    _cache_put(key, audio)
    return audio


async def _stream_into(
    text: str, voice: str, rate: int, pitch: int, volume: int, sink: "queue.Queue", buf: bytearray
) -> None:
    """把云端返回的音频块逐块推进队列，同时在本地累积一份用于缓存。"""
    kwargs = {
        "rate": f"{rate:+d}%",
        "pitch": f"{pitch:+d}Hz",
        "volume": f"{volume:+d}%",
    }
    communicate = edge_tts.Communicate(text, voice, **kwargs)
    async for chunk in communicate.stream():
        if chunk.get("type") == "audio":
            data = chunk["data"]
            buf.extend(data)
            sink.put(data)


def stream_synthesize(
    text: str,
    voice: str = DEFAULT_VOICE,
    rate: int = 0,
    pitch: int = 0,
    volume: int = 0,
):
    """**边合成边产出** MP3 分块（生成器）。

    ## 为什么需要它

    实测发现：在线合成的**首字节固定要约 1.7 秒**——这与文本长短几乎无关
    （念 2 个字和念 41 个字一样要等 1.7 秒），属于连接与云端启用的固有开销；
    而把整段音频传完只多花约 0.5 秒（音频是一块块流式吐出来的）。

    也就是说，此前 `synthesize()` 等「整段合成完」才返回，等于
    白白多等了那 0.5 秒，用户感受就是「文字早就出来了，声音迟迟不来」。
    改为流式下发后，浏览器可以**边下边播**，首音时间明显提前。

    ## 与合成去重的关系

    同一段内容若已有请求在合成，后来者等它的结果（复用缓存），
    而不是重复向云端发起一次。等待期间该请求无法流式（拿到的是完整音频），
    这属于可接受的退化——它本来就命中缓存。

    ## 失败语义

    HTTP 层无法在流开始后再改状态码，因此这里不抛异常：
    合成失败时产出空流，由前端的音频元素触发 error 后走降级链路。
    """
    if not _EDGE_TTS_OK:
        return

    resolved = _resolve(text, voice, rate, pitch, volume)
    if resolved is None:
        return
    voice, rate, pitch, volume, speech = resolved
    key = (voice, rate, pitch, volume, speech)

    cached = _cache_get(key)
    if cached is not None:
        yield cached
        return

    with _PENDING_LOCK:
        event = _PENDING.get(key)
        if event is None:
            event = threading.Event()
            _PENDING[key] = event
            owner = True
        else:
            owner = False

    if not owner:
        event.wait(timeout=_SYNTH_TIMEOUT + 5)
        data = _cache_get(key)
        if data is not None:
            yield data
        return

    sink: "queue.Queue" = queue.Queue()
    sentinel = object()
    buf = bytearray()

    def worker() -> None:
        ok = False
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(
                    asyncio.wait_for(
                        _stream_into(speech, voice, rate, pitch, volume, sink, buf),
                        timeout=_SYNTH_TIMEOUT,
                    )
                )
                ok = True
            finally:
                loop.close()
        except Exception:
            ok = False
        finally:
            # 只有完整合成完才写缓存：客户端中途断开时 buf 是半截音频，
            # 缓存下来会让后续请求听到一段被截断的话。
            if ok and buf:
                _cache_put(key, bytes(buf))
            with _PENDING_LOCK:
                _PENDING.pop(key, None)
            event.set()
            sink.put(sentinel)

    threading.Thread(target=worker, daemon=True).start()

    # 生成器被提前关闭（客户端断开）时，worker 仍会跑完并把完整音频写进缓存，
    # 因此这里不需要额外的清理逻辑。
    for item in iter(sink.get, sentinel):
        yield item



# ══════════ 极速引擎（低延迟备选） ══════════
#
# 在线合成本身效果更好，但有一个无法绕开的成本：**首字节固定要约 1.9 秒**
# （实测与文本长短无关，念两个字和念四十个字一样久，属于连接与云端启用的固有开销）。
# 对于「文字已经读完、声音才响」的体感问题，这是主要的来源。
#
# 因此提供一个低延迟备选：公开的在线朗读接口，首字节约 0.8 秒，是前者的
# 一半以下。代价是音色较为平实、不支持音调/音量调制，所以它作为
# **可选引擎**存在，而不是替换掉音色更好的在线合成。
#
# 注意：该接口可能因网络环境不可达（部分网络会屏蔽），因此可用性必须实测，
# 不能假定；不可用时前端会自动退回在线语音。
_FAST_URL = "https://translate.google.com/translate_tts"
_FAST_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
_FAST_MAX_LEN = 180          # 该接口对过长文本会拒绝，按句传入足够短
_FAST_STATE = {"ok": None, "checked": 0.0}


def _fast_url(text: str) -> str:
    return f"{_FAST_URL}?ie=UTF-8&q={urllib.parse.quote(text)}&tl=zh-CN&client=tw-ob"


def fast_available(force: bool = False) -> bool:
    """极速引擎是否可用。结果缓存 10 分钟，避免每次请求都去探测。"""
    now = time.time()
    if not force and _FAST_STATE["ok"] is not None and now - _FAST_STATE["checked"] < 600:
        return bool(_FAST_STATE["ok"])

    ok = False
    try:
        req = urllib.request.Request(_fast_url("测试"), headers={"User-Agent": _FAST_UA})
        with urllib.request.urlopen(req, timeout=4) as resp:
            ok = getattr(resp, "status", 200) == 200 and bool(resp.read(64))
    except Exception:
        ok = False

    _FAST_STATE["ok"] = ok
    _FAST_STATE["checked"] = now
    return ok


def stream_fast(text: str):
    """极速引擎：取到一块就转发一块，首字节约 0.8 秒。"""
    speech = clean_for_speech(text)
    if not speech:
        return
    if len(speech) > _FAST_MAX_LEN:
        # 该接口对超长文本会直接拒绝，只能截断；但截在字中间会让话
        # 「念到一半突然断掉」，听感比没有声音更糟。因此退到最近的句末
        # 标点，让截断处落在一个自然的句读上。
        cut = max(speech.rfind(m, 0, _FAST_MAX_LEN) for m in "。！？!?；;，,")
        speech = speech[: cut + 1] if cut > 0 else speech[:_FAST_MAX_LEN]

    key = ("fast", speech)
    cached = _cache_get(key)
    if cached is not None:
        yield cached
        return

    buf = bytearray()
    try:
        req = urllib.request.Request(_fast_url(speech), headers={"User-Agent": _FAST_UA})
        with urllib.request.urlopen(req, timeout=_SYNTH_TIMEOUT) as resp:
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                buf.extend(chunk)
                yield chunk
    except Exception:
        return

    if buf:
        _cache_put(key, bytes(buf))
