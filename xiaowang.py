"""
AI 助手 - 入口文件 (Entry Point)

系统的 HTTP 服务器和消息路由中枢。

核心功能:
1. HTTP 服务器：接收消息平台回调
2. 配置加载：多租户用户路由表
3. 消息去重：合并短时间内的连续消息
4. 媒体处理：下载、ASR 语音识别
5. 群聊支持：@提及过滤、上下文缓冲
6. 路由分发：转发到对应用户容器

模块结构:
  xiaowang.py  — 入口：配置、HTTP 服务器、回调处理、消息去重（本文件）
  llm.py       — LLM 调用 + 工具使用循环 + 会话管理
  tools.py     — 工具注册表（只在这里添加工具）
  messaging.py — 消息 API 封装（文本/图片/文件/视频/链接/CDN）
  scheduler.py — 内置调度器（一次性任务 + 定时任务）
  memory.py    — 三层记忆系统（会话 + 压缩 + 向量）
  router.py    — Docker 路由器（多租户容器编排）

技术特性:
- WebSocket 流式 ASR（讯飞 API）
- 消息去重缓冲区（1.5 秒窗口）
- 群聊上下文缓冲（最后 20 条消息）
- 媒体文件持久化存储
- 多租户隔离（独立工作空间）

使用方法：python3 xiaowang.py
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import base64
import hashlib
import hmac
import json
import logging
import os
import struct
import subprocess
import threading
import time
import urllib.request
import websocket
import ssl

# ============================================================
#  配置部分 (Configuration)
# ============================================================

# 数据目录：从环境变量读取，默认为当前文件所在目录
# Data directory: read from environment variable, default to current file's directory
DATA_DIR = os.environ.get("AGENT_DATA", os.path.dirname(os.path.abspath(__file__)))
# 配置文件路径：从环境变量读取，默认为数据目录下的 config.json
# Config file path: read from environment variable, default to config.json under data directory
CONFIG_PATH = os.environ.get("AGENT_CONFIG", os.path.join(DATA_DIR, "config.json"))

# 加载配置文件
# Load configuration file
with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    CONFIG = json.load(f)

# 多租户支持：构建 USERS 路由表
# Multi-tenant support: build USERS routing table
# 每个用户有独立的工作空间和模型配置
# Each user has independent workspace and model configuration
USERS = {}
for _uid, _ucfg in CONFIG.get("users", {}).items():
    # 用户工作空间路径，默认为 ./users/{用户 ID}
    # User workspace path, default to ./users/{user ID}
    _ws = os.path.abspath(_ucfg.get("workspace", f"./users/{_uid}"))
    os.makedirs(_ws, exist_ok=True)
    USERS[str(_uid)] = {
        "owner_id": str(_uid),           # 用户 ID (User ID)
        "name": _ucfg.get("name", "user"),  # 用户名称 (User name)
        "workspace": _ws,                   # 工作空间路径 (Workspace path)
        "model": _ucfg.get("model", CONFIG["models"]["default"]),  # 使用的模型 (Model to use)
    }
# 主工作空间路径
# Main workspace path
WORKSPACE = os.path.abspath(CONFIG.get("workspace", "./workspace"))
# 向后兼容：支持旧的 owner_ids 配置格式
# Backward compatibility: support old owner_ids config format
for _oid in CONFIG.get("owner_ids", []):
    _sid = str(_oid)
    if _sid not in USERS:
        USERS[_sid] = {"owner_id": _sid, "name": "owner", "workspace": WORKSPACE, "model": CONFIG["models"]["default"]}
# HTTP 服务器端口，默认 8080
# HTTP server port, default 8080
PORT = CONFIG.get("port", 8080)
# 消息去重时间窗口（秒），用于合并短时间内连续发送的消息
# Message debounce time window (seconds), used to merge continuously sent messages in short time
DEBOUNCE_SECONDS = CONFIG.get("debounce_seconds", 1.5)
# 会话存储目录
# Session storage directory
SESSIONS_DIR = os.path.join(DATA_DIR, "sessions")
# 定时任务存储文件
# Scheduled task storage file
JOBS_FILE = os.path.join(DATA_DIR, "jobs.json")
# Docker 单租户模式：使用第一个用户的工作空间作为默认文件目录
# Docker single-tenant mode: use first user's workspace as default file directory
_first_user_ws = next(iter(USERS.values()))["workspace"] if USERS else WORKSPACE
FILES_DIR = os.path.join(_first_user_ws, "files")

# 创建必要的目录
# Create necessary directories
os.makedirs(SESSIONS_DIR, exist_ok=True)
os.makedirs(FILES_DIR, exist_ok=True)

# 配置日志系统：时间戳 + 日志级别 + 消息
# Configure logging system: timestamp + log level + message
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("agent")

# ============================================================
#  模块初始化 (Module Initialization)
# ============================================================

# 导入核心模块
# Import core modules
import messaging  # 消息平台 API 封装 (Messaging platform API wrapper)
import llm        # LLM 调用和工具使用循环 (LLM invocation and tool use loop)
import scheduler  # 定时任务调度器 (Scheduled task scheduler)

# ============================================================
#  群聊支持 - 名称缓存 + 辅助函数 (Group Chat Support - Name Cache + Helper Functions)
# ============================================================

# 发送者名称缓存：sender_id -> (名称，时间戳)
# Sender name cache: sender_id -> (name, timestamp)
# 避免频繁调用 API 查询联系人信息
# Avoid frequent API calls to query contact information
_name_cache = {}

# 群聊上下文缓冲区：存储未 @ 机器人的消息，供 LLM 参考
# Group chat context buffer: store messages not @-mentioning the bot, for LLM reference
# 结构：group_id -> deque（双端队列，自动限制最大长度）
# Structure: group_id -> deque (double-ended queue, automatically limits max length)
from collections import deque
_group_context_buffers = {}  # 群 ID -> 消息队列 (Group ID -> Message queue)
GROUP_CONTEXT_MAX = 20  # 每个群最多保留 20 条上下文消息 (Max 20 context messages per group)


def _format_group_context(group_id):
    """格式化群聊上下文缓冲区，供 LLM 参考
    Format group chat context buffer for LLM reference
    """
    buf = _group_context_buffers.get(group_id, [])
    if not buf:
        return ""
    lines = ["[最近的群消息（未@你，仅供参考）]"]
    for item in buf:
        lines.append("[%s] %s" % (item["sender"], item["text"]))
    return "\n".join(lines)


def _resolve_sender_name(sender_id):
    """查询发送者昵称，带 1 小时缓存
    Query sender nickname, with 1-hour cache
    """
    # 检查缓存是否有效（1 小时内）
    # Check if cache is valid (within 1 hour)
    cached = _name_cache.get(sender_id)
    if cached and time.time() - cached[1] < 3600:
        return cached[0]
    # 调用消息 API 查询联系人信息
    # Call messaging API to query contact information
    try:
        info = messaging.get_contact_info([sender_id])
        if info:
            # 优先使用昵称，其次备注名
            # Prefer nickname, then remark name
            name = info[0].get("nickname") or info[0].get("remark") or ""
            if name:
                _name_cache[sender_id] = (name, time.time())
                return name
    except Exception:
        pass
    # 降级方案：使用用户 ID 后 6 位
    # Fallback: use last 6 digits of user ID
    fallback = "user%s" % str(sender_id)[-6:]
    _name_cache[sender_id] = (fallback, time.time())
    return fallback


def _strip_at_mention(content):
    """从消息开头移除 @xxx 提及文本
    Remove @xxx mention text from the beginning of message
    """
    import re as _re2
    # 使用正则表达式移除开头的 @ 提及
    # Use regex to remove @ mention from the beginning
    return _re2.sub(r'^@\S+\s*', '', content).strip()

messaging.init(CONFIG["messaging"])
llm.init(CONFIG["models"], USERS, SESSIONS_DIR)
scheduler.init(JOBS_FILE, llm.chat, USERS, sessions_dir=SESSIONS_DIR)

import tools
tools.init_extra(CONFIG)

# Initialize memory system
# 初始化内存系统
import memory as mem_mod
_mem_db = os.path.join(DATA_DIR, 'memory_db')
os.makedirs(_mem_db, exist_ok=True)
mem_mod.init(CONFIG, CONFIG.get('models', {}), _mem_db)

# ============================================================
#  持久化文件存储 (Persistent File Storage)
# ============================================================

FILES_INDEX = os.path.join(FILES_DIR, "index.json")


def _load_files_index():
    """加载文件索引
    Load file index
    """
    if os.path.exists(FILES_INDEX):
        try:
            with open(FILES_INDEX, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def _save_files_index(index):
    """保存文件索引
    Save file index
    """
    with open(FILES_INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)


def save_media_file(tmp_path, media_type, filename="", files_dir=None):
    """Move temp file to persistent storage, return persistent path
    移动临时文件到持久化存储，返回持久化路径
    """
    from datetime import datetime, timezone, timedelta
    CST = timezone(timedelta(hours=8))  # 中国标准时间 (China Standard Time)
    now = datetime.now(CST)
    _fdir = files_dir or FILES_DIR
    month_dir = os.path.join(_fdir, now.strftime("%Y-%m"))  # 按年月组织文件 (Organize files by year-month)
    os.makedirs(month_dir, exist_ok=True)

    # 获取文件扩展名 (Get file extension)
    ext = os.path.splitext(tmp_path)[1] or os.path.splitext(filename)[1] if filename else ".bin"
    if not ext:
        ext = ".bin"
    # 安全文件名：替换路径分隔符 (Safe filename: replace path separators)
    safe_name = filename.replace("/", "_").replace("\\", "_") if filename else ""
    import random as _rnd
    _ts_ms = int(now.timestamp() * 1000)  # 时间戳毫秒 (Timestamp in milliseconds)
    _rand = '%04x' % _rnd.randint(0, 0xFFFF)  # 随机数防止重名 (Random number to prevent name collision)
    stored_name = f"{_ts_ms}_{_rand}_{safe_name}" if safe_name else f"{_ts_ms}_{_rand}{ext}"
    dest = os.path.join(month_dir, stored_name)

    # 移动文件到持久化存储 (Move file to persistent storage)
    try:
        os.rename(tmp_path, dest)
    except OSError:
        import shutil
        shutil.move(tmp_path, dest)

    # 记录文件索引 (Record file index)
    entry = {
        "path": dest,
        "type": media_type,
        "filename": filename or os.path.basename(dest),
        "size": os.path.getsize(dest),
        "time": now.isoformat(),
    }
    index = _load_files_index()
    index.append(entry)
    _save_files_index(index)
    log.info(f"[files] saved {media_type} to {dest}")
    return dest

# ============================================================
#  ASR (WebSocket Streaming Recognition) - 语音识别
# ============================================================

XFYUN_CONFIG = CONFIG.get("xfyun", {})  # 讯飞语音配置 (iFlytek voice configuration)


def xfyun_asr(audio_path):
    """WebSocket ASR: audio file -> text
    WebSocket 自动语音识别：音频文件转文本
    """
    if not XFYUN_CONFIG:
        return None
    _asr_start = time.time()

    # Transcode to PCM: silk via pilk, other formats via ffmpeg
    # 转码为 PCM 格式：silk 格式用 pilk，其他格式用 ffmpeg
    pcm_path = audio_path + ".pcm"
    try:
        with open(audio_path, "rb") as f:
            header = f.read(10)
        if b"SILK" in header:
            import pilk
            pilk.decode(audio_path, pcm_path, pcm_rate=16000)
            log.info("[asr] silk -> pcm via pilk")
        else:
            subprocess.run(
                ["ffmpeg", "-y", "-i", audio_path, "-ar", "16000", "-ac", "1", "-f", "s16le", pcm_path],
                capture_output=True, timeout=30
            )
            log.info("[asr] audio -> pcm via ffmpeg")
    except Exception as e:
        log.error(f"[asr] transcode error: {e}")
        return None

    if not os.path.exists(pcm_path) or os.path.getsize(pcm_path) == 0:
        log.error("[asr] transcode produced empty PCM")
        return None

    # 读取 PCM 音频数据 (Read PCM audio data)
    try:
        with open(pcm_path, "rb") as f:
            audio_data = f.read()
    finally:
        try:
            os.unlink(pcm_path)  # 删除临时 PCM 文件 (Delete temporary PCM file)
        except Exception:
            pass

    # Build authentication URL
    # 构建认证 URL (Build authentication URL)
    from datetime import datetime
    from urllib.parse import urlencode
    import email.utils

    app_id = XFYUN_CONFIG["app_id"]
    api_key = XFYUN_CONFIG["api_key"]
    api_secret = XFYUN_CONFIG["api_secret"]

    url = "wss://iat-api.xfyun.cn/v2/iat"
    now = datetime.utcnow()
    date = email.utils.formatdate(timeval=time.mktime(now.timetuple()), usegmt=True)

    # HMAC-SHA256 签名 (HMAC-SHA256 signature)
    signature_origin = f"host: iat-api.xfyun.cn\ndate: {date}\nGET /v2/iat HTTP/1.1"
    signature_sha = hmac.new(api_secret.encode(), signature_origin.encode(), hashlib.sha256).digest()
    signature = base64.b64encode(signature_sha).decode()

    authorization_origin = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    authorization = base64.b64encode(authorization_origin.encode()).decode()

    ws_url = url + "?" + urlencode({"authorization": authorization, "date": date, "host": "iat-api.xfyun.cn"})

    # WebSocket synchronous call
    # WebSocket 同步调用 (WebSocket synchronous call)
    result_text = []
    done_event = threading.Event()
    error_holder = [None]

    def on_message(ws, message):
        """处理 WebSocket 消息回调
        Handle WebSocket message callback
        """
        try:
            data = json.loads(message)
            code = data.get("code", 0)
            if code != 0:
                error_holder[0] = f"xfyun error code={code}: {data.get('message', '')}"
                done_event.set()
                return
            result = data.get("data", {}).get("result", {})
            ws_list = result.get("ws", [])
            for ws_item in ws_list:
                for cw in ws_item.get("cw", []):
                    result_text.append(cw.get("w", ""))
            if data.get("data", {}).get("status") == 2:  # 识别完成 (Recognition complete)
                done_event.set()
        except Exception as e:
            error_holder[0] = str(e)
            done_event.set()

    def on_error(ws, error):
        """处理 WebSocket 错误回调
        Handle WebSocket error callback
        """
        error_holder[0] = str(error)
        done_event.set()

    def on_open(ws):
        """WebSocket 连接打开后发送音频数据
        Send audio data after WebSocket connection opens
        """
        def send_audio():
            frame_size = 8000  # bytes per frame (每帧字节数)
            status = 0  # 0=first (首帧), 1=continue (中间帧), 2=last (末帧)
            offset = 0
            while offset < len(audio_data):
                end = min(offset + frame_size, len(audio_data))
                chunk = audio_data[offset:end]
                if offset + frame_size >= len(audio_data):
                    status = 2

                d = {
                    "common": {"app_id": app_id} if status == 0 else None,
                    "business": {
                        "language": "zh_cn",
                        "domain": "iat",
                        "accent": "mandarin",
                        "vad_eos": 3000,
                    } if status == 0 else None,
                    "data": {
                        "status": status,
                        "format": "audio/L16;rate=16000",
                        "encoding": "raw",
                        "audio": base64.b64encode(chunk).decode(),
                    },
                }
                # Remove None values (移除空值)
                d = {k: v for k, v in d.items() if v is not None}
                ws.send(json.dumps(d))

                if status == 0:
                    status = 1
                offset = end
                if status != 2:
                    time.sleep(0.04)  # Simulate real-time (模拟实时传输)
        threading.Thread(target=send_audio, daemon=True).start()

    ws = websocket.WebSocketApp(
        ws_url,
        on_message=on_message,
        on_error=on_error,
        on_open=on_open,
    )
    wst = threading.Thread(target=lambda: ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE}), daemon=True)
    wst.start()
    done_event.wait(timeout=15)  # 等待识别完成，最多 15 秒 (Wait for recognition, max 15 seconds)
    ws.close()

    if error_holder[0]:
        _asr_elapsed = time.time() - _asr_start
        log.error(f"[asr] failed in {_asr_elapsed:.1f}s: {error_holder[0]}")
        return None

    text = "".join(result_text).strip()
    _asr_elapsed = time.time() - _asr_start
    if text:
        log.info(f"[asr] completed in {_asr_elapsed:.1f}s, recognized: {text[:100]}")
    else:
        log.warning(f"[asr] failed in {_asr_elapsed:.1f}s, no text recognized")
    return text if text else None


# ============================================================
#  Message Splitting - 消息分割
# ============================================================

def split_message(text, max_bytes=1800):
    """分割长消息，避免超过平台限制
    Split long messages to avoid exceeding platform limits
    """
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        test = current + "\n" + line if current else line
        if len(test.encode("utf-8")) > max_bytes:
            if current:
                chunks.append(current)
            current = line
        else:
            current = test
    if current:
        chunks.append(current)
    return chunks

# ============================================================
#  Debounce - 消息去重
# ============================================================

# 去重缓冲区：sender_id -> [{"text": str, "images": [path, ...]}]
# Debounce buffer: sender_id -> [{"text": str, "images": [path, ...]}]
_debounce_buffers = {}
_debounce_timers = {}
# 待处理下载计数：sender_id -> int (pending download count)
_debounce_pending = {}
# 待处理开始时间：sender_id -> timestamp (first pending registered)
_debounce_pending_since = {}
_debounce_lock = threading.Lock()
_PENDING_MAX_WAIT = 30  # Max wait 30s for download, force flush on timeout (下载最大等待 30 秒，超时强制刷新)


def _debounce_flush(sender_id):
    """刷新去重缓冲区，发送合并后的消息
    Flush debounce buffer, send merged messages
    """
    with _debounce_lock:
        pending = _debounce_pending.get(sender_id, 0)
        if pending > 0:
            # Check if max wait time exceeded
            # 检查是否超过最大等待时间 (Check if max wait time exceeded)
            since = _debounce_pending_since.get(sender_id, time.time())
            waited = time.time() - since
            if waited < _PENDING_MAX_WAIT:
                log.info(f"[debounce] {sender_id}: {pending} downloads pending ({waited:.0f}s), deferring flush")
                timer = threading.Timer(DEBOUNCE_SECONDS, _debounce_flush, args=[sender_id])
                timer.daemon = True
                timer.start()
                _debounce_timers[sender_id] = timer
                return
            else:
                log.warning(f"[debounce] {sender_id}: force flush after {waited:.0f}s, {pending} downloads still pending")

        # 弹出缓冲区数据 (Pop buffer data)
        fragments = _debounce_buffers.pop(sender_id, [])
        _debounce_timers.pop(sender_id, None)
        _debounce_pending.pop(sender_id, None)
        _debounce_pending_since.pop(sender_id, None)

    if not fragments:
        return

    # Merge text and images
    # 合并文本和图片 (Merge text and images)
    texts = []
    images = []
    for frag in fragments:
        if isinstance(frag, dict):
            if frag.get("text"):
                texts.append(frag["text"])
            images.extend(frag.get("images", []))
        else:
            texts.append(str(frag))

    combined_text = "\n".join(texts)
    # Diagnostic log: record merged fragment count and content preview
    # 诊断日志：记录合并的片段数量和内容预览 (Diagnostic log: record merged fragment count and content preview)
    preview = combined_text[:80].replace("\n", " ")
    log.info(f"[debounce] flush {sender_id}: {len(fragments)} fragments, images={len(images)}, preview=\"{preview}\"")

    # Detect if group chat
    # 检测是否为群聊 (Detect if group chat)
    group_ctx = None
    for frag in fragments:
        if isinstance(frag, dict) and frag.get("group_ctx"):
            group_ctx = frag["group_ctx"]
            break

    if group_ctx:
        # ===== Group chat path =====
        # ===== 群聊处理路径 =====
        group_id = group_ctx["group_id"]
        session_key = "wecom_group_%s" % group_id
        user_config = next(iter(USERS.values()), None)
        if not user_config:
            return
        try:
            log.info("[group] chat for room=%s, text=%s", group_id, combined_text[:100])
            reply = llm.chat(combined_text, session_key, images=images,
                           user_config=user_config, group_ctx=group_ctx)
            if reply and reply.strip():
                from tools_base import _strip_markdown, _split_message
                for chunk in _split_message(_strip_markdown(reply), 1800):
                    messaging.send_text(group_id, chunk)
        except Exception as e:
            log.error("[group] chat error for %s: %s", group_id, e, exc_info=True)
        return

    # ===== Direct message path (original logic unchanged) =====
    # ===== 私聊处理路径（原始逻辑保持不变）=====
    try:
        user_config = USERS.get(str(sender_id))
        if not user_config:
            messaging.send_text(sender_id, "Sorry, you have not activated the AI assistant service.")
            return

        # === Record user activity timestamp (for scheduler inactivity guard) ===
        # === 记录用户活动时间戳（用于调度器不活动监控）===
        try:
            activity_file = os.path.join(user_config.get("workspace", ""), ".last_user_message")
            with open(activity_file, "w") as f:
                f.write(str(time.time()))
        except Exception:
            pass

        # === Dormant recovery: user came back, remove dormant marker ===
        # === 休眠恢复：用户回来了，移除休眠标记 ===
        dormant_file = os.path.join(user_config.get("workspace", ""), ".dormant_since")
        if os.path.exists(dormant_file):
            try:
                os.remove(dormant_file)
                log.info("[dormant] user %s is back, removed dormant marker", sender_id)
            except Exception:
                pass

                log.info(f"[chat] {sender_id} -> tool use loop (images={len(images)})")
        session_key = f"wecom_dm_{sender_id}"
        reply = llm.chat(combined_text, session_key, images=images, user_config=user_config)

        if not reply or not reply.strip():
            log.warning(f"[chat] empty reply for {sender_id}")
            return

        # Pre-send buffer check: did new messages arrive during LLM processing?
        # 发送前缓冲区检查：LLM 处理期间是否有新消息到达？
        # Note: no longer discarding current reply. Side effects during LLM processing (write_file/schedule) already executed,
        # Discarding reply would hide results from user while state has changed.
        # New messages will be handled naturally by the debounce timer.
        # 注意：不再丢弃当前回复。LLM 处理期间的副作用（写文件/调度）已执行，
        # 丢弃回复会向用户隐藏结果而状态已改变。
        # 新消息将由去重定时器自然处理。
        with _debounce_lock:
            new_fragments = _debounce_buffers.get(sender_id, [])
            has_new = len(new_fragments) > 0

        if has_new:
            log.info(f"[pre-send-check] {sender_id}: {len(new_fragments)} new messages arrived during LLM, will be handled by next flush")

        from tools import _strip_markdown, _split_message
        for i, chunk in enumerate(_split_message(_strip_markdown(reply), 1800)):
            messaging.send_text(sender_id, chunk)
            if i > 0:
                time.sleep(0.5)  # 分条发送时添加延迟 (Add delay when sending in chunks)

    except Exception as e:
        log.error(f"[flush] error for {sender_id}: {e}", exc_info=True)
        try:
            messaging.send_text(sender_id, f"Sorry, an error occurred while processing the message：{e}")
        except Exception:
            pass


def debounce_message(sender_id, text, images=None, group_ctx=None):
    """将消息加入去重缓冲区
    Add message to debounce buffer
    """
    with _debounce_lock:
        frag = {"text": text, "images": images or []}
        if group_ctx:
            frag["group_ctx"] = group_ctx
        _debounce_buffers.setdefault(sender_id, []).append(frag)
        old_timer = _debounce_timers.get(sender_id)
        if old_timer:
            old_timer.cancel()
        timer = threading.Timer(DEBOUNCE_SECONDS, _debounce_flush, args=[sender_id])
        timer.daemon = True
        timer.start()
        _debounce_timers[sender_id] = timer
        count = len(_debounce_buffers[sender_id])
    log.info(f"[debounce] {sender_id}: buffered #{count}")


def _register_pending(sender_id):
    """Register a pending download. Reset debounce timer, flush waits for all pending.
    注册待处理下载。重置去重定时器，刷新等待所有待处理完成。
    """
    with _debounce_lock:
        _debounce_pending[sender_id] = _debounce_pending.get(sender_id, 0) + 1
        if sender_id not in _debounce_pending_since:
            _debounce_pending_since[sender_id] = time.time()
        # Reset timer (重置定时器)
        old_timer = _debounce_timers.get(sender_id)
        if old_timer:
            old_timer.cancel()
        timer = threading.Timer(DEBOUNCE_SECONDS, _debounce_flush, args=[sender_id])
        timer.daemon = True
        timer.start()
        _debounce_timers[sender_id] = timer
        pending = _debounce_pending[sender_id]
    log.info(f"[debounce] {sender_id}: registered pending download (total pending: {pending})")


def _resolve_pending(sender_id, text, images=None):
    """After download: add result to buffer, decrement pending count, reset timer.
    下载完成后：将结果添加到缓冲区，减少待处理计数，重置定时器。
    """
    with _debounce_lock:
        _debounce_pending[sender_id] = max(0, _debounce_pending.get(sender_id, 0) - 1)
        frag = {"text": text, "images": images or []}
        _debounce_buffers.setdefault(sender_id, []).append(frag)
        # Reset timer(shorter delay after download, faster response)
        # 重置定时器（下载后更短延迟，更快响应）
        old_timer = _debounce_timers.get(sender_id)
        if old_timer:
            old_timer.cancel()
        pending = _debounce_pending[sender_id]
        flush_delay = 0.5 if pending == 0 else DEBOUNCE_SECONDS
        timer = threading.Timer(flush_delay, _debounce_flush, args=[sender_id])
        timer.daemon = True
        timer.start()
        _debounce_timers[sender_id] = timer
        count = len(_debounce_buffers[sender_id])
    log.info(f"[debounce] {sender_id}: resolved pending, buffered #{count} (remaining pending: {pending}, flush_delay={flush_delay}s)")

# ============================================================
#  Callback Processing - 回调处理
# ============================================================

def _download_media(msg_data, media_type="file"):
    """Download media file, return local path or None
    下载媒体文件，返回本地路径或 None

    Three download paths (by priority):
    三种下载路径（按优先级）:
    1. Has fileId -> /cloud/wxWorkDownload (work messaging format) (企业微信格式)
    2. Has fileAuthKey -> /cloud/wxDownload (personal format, images often use this) (个人格式，图片常用)
    3. Has fileHttpUrl -> direct HTTP download (fallback) (直接 HTTP 下载，备用)

    media_type used to infer messaging platform fileType: image=1 video=4 voice/file=5
    media_type 用于推断消息平台 fileType: image=1 video=4 voice/file=5
    """
    file_id = msg_data.get("fileId", "")
    file_aes_key = msg_data.get("fileAeskey", msg_data.get("fileAesKey", ""))
    file_auth_key = msg_data.get("fileAuthkey", msg_data.get("fileAuthKey", ""))
    file_size = msg_data.get("fileSize", msg_data.get("fileBigSize", 0))

    # Infer messaging platform fileType
    # 推断消息平台 fileType
    ft_map = {"image": 1, "GIF": 1, "video_kw": 4, "voice": 5, "file": 5}
    file_type = ft_map.get(media_type, 5)

    # Path 1: work messaging format (has fileId)
    # 路径 1：企业微信格式（有 fileId）
    if file_id and file_aes_key:
        log.info(f"[media] trying wxWorkDownload (fileId={file_id[:20]}..., fileType={file_type})")
        path = messaging.download_wx_work(file_id, file_aes_key, file_size, file_type=file_type)
        if path:
            return path

    # Path 2: personal format (has fileAuthKey + URL)
    # 路径 2：个人微信格式（有 fileAuthKey + URL）
    if file_auth_key:
        file_url = (msg_data.get("fileBigHttpUrl") or msg_data.get("fileMiddleHttpUrl") or
                    msg_data.get("fileThumbHttpUrl") or msg_data.get("fileHttpUrl") or "")
        if file_url:
            log.info(f"[media] trying wxDownload (authKey, fileType={file_type})")
            path = messaging.download_wx(file_aes_key, file_auth_key, file_url, file_size, file_type=file_type)
            if path:
                return path

    # Path 3: direct HTTP download (fallback)
    # 路径 3：直接 HTTP 下载（备用方案）
    direct_url = (msg_data.get("fileHttpUrl") or msg_data.get("fileUrl") or "")
    if direct_url:
        log.info(f"[media] trying direct HTTP download")
        ext = messaging.get_ext(direct_url) or ".bin"
        tmp_path = f"/tmp/agent-recv-{int(time.time())}{ext}"
        try:
            urllib.request.urlretrieve(direct_url, tmp_path)
            return tmp_path
        except Exception as e:
            log.error(f"[media] direct download failed: {e}")

    log.error(f"[media] all download methods failed, keys={list(msg_data.keys())}")
    return None


def _handle_media_message(sender_id, msg_data, media_type, filename=""):
    """Handle received multimedia message: register pending immediately, async download, persist, notify LLM
    处理收到的多媒体消息：立即注册待处理，异步下载，持久化，通知 LLM
    """
    if str(sender_id) not in USERS:
        messaging.send_text(sender_id, "Sorry, you have not activated the AI assistant service.")
        return

    # Register pending immediately to prevent premature debounce flush
    # 立即注册待处理以防止过早刷新去重缓冲区
    _register_pending(sender_id)
    threading.Thread(
        target=_async_media_download,
        args=(sender_id, msg_data, media_type, filename),
        daemon=True
    ).start()


def _async_media_download(sender_id, msg_data, media_type, filename=""):
    """Async download media file, resolve pending on completion
    异步下载媒体文件，完成后解析待处理
    """
    try:
        user_config = USERS[str(sender_id)]
        user_files_dir = os.path.join(user_config["workspace"], "files")
        os.makedirs(user_files_dir, exist_ok=True)
        file_size = msg_data.get("fileSize", 0)

        desc_parts = [f"[User sent {media_type}]"]
        if filename:
            desc_parts.append(f"Filename: {filename}")
        if file_size:
            size_kb = file_size / 1024
            desc_parts.append(f"Size: {size_kb/1024:.1f}MB" if size_kb > 1024 else f"Size: {size_kb:.0f}KB")

        tmp_path = _download_media(msg_data, media_type)
        image_paths = []

        if tmp_path:
            saved_path = save_media_file(tmp_path, media_type, filename, files_dir=user_files_dir)
            desc_parts.append(f"Saved to: {saved_path}")
            if media_type == "image":
                image_paths.append(saved_path)
        else:
            desc_parts.append("(file download failed)")

        _resolve_pending(sender_id, "\n".join(desc_parts), images=image_paths)
    except Exception as e:
        log.error(f"[media] async download error for {sender_id}: {e}", exc_info=True)
        _resolve_pending(sender_id, f"[User sent {media_type}, processing failed: {e}]")


def _handle_voice_message(sender_id, msg_data):
    """Handle voice message: register pending immediately, async download + ASR
    处理语音消息：立即注册待处理，异步下载 + ASR 语音识别
    """
    if str(sender_id) not in USERS:
        messaging.send_text(sender_id, "Sorry, you have not activated the AI assistant service.")
        return

    # Register pending immediately to prevent premature debounce flush
    # 立即注册待处理以防止过早刷新去重缓冲区
    _register_pending(sender_id)
    threading.Thread(
        target=_async_voice_process,
        args=(sender_id, msg_data),
        daemon=True
    ).start()


def _async_voice_process(sender_id, msg_data):
    """Async download voice + ASR, resolve pending on completion
    异步下载语音 + ASR 识别，完成后解析待处理
    """
    try:
        user_config = USERS[str(sender_id)]
        user_files_dir = os.path.join(user_config["workspace"], "files")
        os.makedirs(user_files_dir, exist_ok=True)

        tmp_path = _download_media(msg_data, "voice")
        if not tmp_path:
            _resolve_pending(sender_id, "[User sent voice message, but download failed]")
            return

        saved_path = save_media_file(tmp_path, "voice", files_dir=user_files_dir)

        text = xfyun_asr(saved_path)
        if text:
            _resolve_pending(sender_id, f"[voice-to-text] {text}")
        else:
            # Immediately notify user voice was unclear
            # 立即通知用户语音不清晰
            try:
                messaging.send_text(sender_id, "Could not understand the voice message. Please try again or type it.")
            except Exception as e:
                log.error(f"[asr] failed to send tip: {e}")
            _resolve_pending(sender_id, f"[User sent voice message，ASR failed, user has been notified to resend]\nSaved to: {saved_path}")
    except Exception as e:
        log.error(f"[voice] async process error for {sender_id}: {e}", exc_info=True)
        _resolve_pending(sender_id, f"[User sent voice message, processing failed: {e}]")


def handle_callback(data):
    """处理消息平台回调
    Handle messaging platform callback
    """
    if isinstance(data, dict) and "testMsg" in data:
        log.info(f"[callback] test: {data['testMsg']}")
        return
    if not isinstance(data, dict):
        return

    messages = data.get("data", [])
    if isinstance(messages, dict):
        messages = [messages]
    elif not isinstance(messages, list):
        return

    for msg in messages:
        if not isinstance(msg, dict):
            continue

        cmd = msg.get("cmd")
        sender_id = msg.get("senderId")
        msg_type = msg.get("msgType")
        msg_data = msg.get("msgData", {})
        if not isinstance(msg_data, dict):
            msg_data = {}

        # Skip messages from self
        # 跳过来自自己的消息
        if str(sender_id) == str(msg.get("userId")):
            continue

        # Group chat detection
        # 群聊检测
        from_room_id = str(msg.get("fromRoomId", 0) or 0)
        is_group = from_room_id != "0"

        if is_group:
            # Gate 1: config opt-in
            # 门控 1：配置启用检查
            if not CONFIG.get("group_chat", {}).get("enabled", False):
                continue
            # Gate 2: only respond to @ mentions (non-empty atList = @-mentioned)
            # 门控 2：仅响应@提及（atList 非空=被@）
            at_list = msg_data.get("atList", [])
            if not at_list:
                # Non-@ message: silently store in context buffer
                # 非@消息：静默存储到上下文缓冲区
                if cmd == 15000 and msg_type in (0, 2, 1011):
                    msg_content = msg_data.get("content", "")
                    if msg_content:
                        sender_name = _resolve_sender_name(sender_id)
                        buf = _group_context_buffers.setdefault(
                            from_room_id, deque(maxlen=GROUP_CONTEXT_MAX))
                        buf.append({"sender": sender_name, "text": msg_content[:200]})
                        log.info("[group] buffered context in room %s from %s", from_room_id, sender_name)
                continue
            # Optional: exact match AI wechat_id
            # 可选：精确匹配 AI 微信号
            ai_id = CONFIG.get("messaging", {}).get("wechat_id", "")
            if ai_id and not any(str(a.get("wxid", a.get("userId", ""))) == ai_id for a in at_list):
                continue
            log.info("[group] room=%s sender=%s", from_room_id, sender_id)

        if cmd == 15000:
            if msg_type in (0, 2, 1011):
                content = msg_data.get("content", "")
                if content:
                    log.info(f"[callback] text from {sender_id}: {content[:100]}")
                    if is_group:
                        sender_name = _resolve_sender_name(sender_id)
                        content = _strip_at_mention(content)
                        if not content:
                            continue
                        debounce_key = "group_%s" % from_room_id
                        group_ctx = {"group_id": from_room_id, "sender_id": sender_id}
                        context_str = _format_group_context(from_room_id)
                        if context_str:
                            group_ctx["recent_context"] = context_str
                        debounce_message(debounce_key, "[%s] %s" % (sender_name, content),
                                         group_ctx=group_ctx)
                    else:
                        debounce_message(sender_id, content)
            elif msg_type in (7, 14, 101):
                log.info(f"[callback] image from {sender_id}")
                if is_group:
                    sender_name = _resolve_sender_name(sender_id)
                    debounce_key = "group_%s" % from_room_id
                    debounce_message(debounce_key, "[%s] [sent an image]" % sender_name,
                                     group_ctx={"group_id": from_room_id, "sender_id": sender_id})
                else:
                    _handle_media_message(sender_id, msg_data, "image")
            elif msg_type in (22, 23, 103):
                log.info(f"[callback] video from {sender_id}")
                _handle_media_message(sender_id, msg_data, "video_kw")
            elif msg_type in (15, 20, 102):
                filename = msg_data.get("filename", msg_data.get("fileName", "unknown file"))
                log.info(f"[callback] file from {sender_id}: {filename}")
                _handle_media_message(sender_id, msg_data, "file", filename)
            elif msg_type in (29, 104):
                log.info(f"[callback] gif from {sender_id}")
                _handle_media_message(sender_id, msg_data, "GIF")
            elif msg_type == 16:
                log.info(f"[callback] voice from {sender_id}")
                _handle_voice_message(sender_id, msg_data)
            elif msg_type == 13:
                title = msg_data.get("title", "")
                url = msg_data.get("linkUrl", msg_data.get("url", ""))
                log.info(f"[callback] link from {sender_id}: {title}")
                debounce_message(sender_id, f"[User shared a link]\nTitle: {title}\nURL: {url}")
            elif msg_type == 6:
                # Extract all possible location fields
                label = msg_data.get("label", msg_data.get("poiname", ""))
                lat = msg_data.get("latitude", msg_data.get("lat", ""))
                lng = msg_data.get("longitude", msg_data.get("lng", ""))
                address = msg_data.get("address", msg_data.get("addr", ""))
                poiname = msg_data.get("poiname", msg_data.get("poiName", ""))
                log.info(f"[callback] location from {sender_id}: label={label}, lat={lat}, lng={lng}, addr={address}, poi={poiname}, keys={list(msg_data.keys())}")
                # Build complete location description for LLM
                parts = []
                if label or poiname:
                    parts.append(f"Name: {label or poiname}")
                if address:
                    parts.append(f"Address: {address}")
                if lat and lng:
                    parts.append(f"Coordinates: {lat},{lng}")
                if parts:
                    loc_desc = "; ".join(parts)
                    debounce_message(sender_id, f"[User sent location] {loc_desc}")
                else:
                    # Hardcoded reply, bypass LLM (same as ASR failure pattern)
                    messaging.send_text(sender_id, "I cannot see the exact location you sent. Please tell me where you are in text.")
                    log.info(f"[callback] location from {sender_id}: all fields empty, replied directly")
            elif msg_type == 26:
                # Red envelope
                log.info(f"[callback] red packet from {sender_id}")
                debounce_message(sender_id, "[User sent a red envelope. You cannot view or claim it. Just express thanks.]")
            elif msg_type == 78:
                # Mini program
                title = msg_data.get("title", msg_data.get("sourcedisplayname", ""))
                log.info(f"[callback] miniprogram(78) from {sender_id}: {title}")
                debounce_message(sender_id, f"[User shared a mini program: {title}，You cannot open it, only see the title]")
            elif msg_type == 123:
                # Rich text
                content = msg_data.get("content", "")
                log.info(f"[callback] richtext from {sender_id}")
                debounce_message(sender_id, f"[User sent rich text message, you can only see the text part]\n{content[:300]}" if content else "[User sent rich text message, you can only see the text part]")
            elif msg_type == 141:
                # Video channel
                title = msg_data.get("title", msg_data.get("desc", ""))
                log.info(f"[callback] video_channel from {sender_id}: {title}")
                debounce_message(sender_id, f"[User shared video channel content: {title}，You cannot play or view the video, only see the title]")
            elif msg_type == 146:
                # Livestream
                title = msg_data.get("title", "")
                log.info(f"[callback] livestream from {sender_id}: {title}")
                debounce_message(sender_id, f"[User shared a livestream: {title}，You cannot watch the livestream, only see the title]")
            elif msg_type in (47, 8):
                # Sticker / custom emoji
                log.info(f"[callback] sticker from {sender_id}")
                debounce_message(sender_id, "[User sent a sticker, you cannot see the specific content]")
            elif msg_type == 49:
                # App message (quoted reply / mini program / article etc.)
                title = msg_data.get("title", "")
                desc = msg_data.get("desc", msg_data.get("description", ""))
                url = msg_data.get("url", msg_data.get("linkUrl", ""))
                content = msg_data.get("content", "")
                parts = [f"[User sent an app message]"]
                if title:
                    parts.append(f"Title: {title}")
                if desc:
                    parts.append(f"Description: {desc}")
                if url:
                    parts.append(f"URL: {url}")
                if content and not title and not desc:
                    # May be a quoted reply, content contains XML
                    parts.append(f"Content: {content[:200]}")
                log.info(f"[callback] appmsg from {sender_id}: title={title}")
                debounce_message(sender_id, "\n".join(parts))
            elif msg_type in (33, 36):
                # Mini program
                title = msg_data.get("title", msg_data.get("sourcedisplayname", ""))
                log.info(f"[callback] miniprogram from {sender_id}: {title}")
                debounce_message(sender_id, f"[User shared a mini program: {title}，You cannot open it, only see the title]")
            elif msg_type in (41, 42):
                # Name card (41=document confirm, 42=compat)
                nickname = msg_data.get("nickname", msg_data.get("nickName", "unknown"))
                log.info(f"[callback] namecard from {sender_id}: {nickname}")
                debounce_message(sender_id, f"[User sent a contact card: {nickname}]")
            else:
                # Unknown type — do not silently drop, notify LLM
                content = msg_data.get("content", msg_data.get("title", ""))
                preview = f"，Content: {content[:80]}" if content else ""
                debounce_message(sender_id, f"[Received a message (type {msg_type}), cannot parse yet{preview}]")
        elif cmd == 15500:
            log.info(f"[callback] sys cmd=15500 type={msg_type}")
        elif cmd == 11016:
            log.info(f"[callback] account status: {msg_data.get('code', 0)}")

# ============================================================
#  HTTP Server - HTTP 服务器
# ============================================================

class Handler(BaseHTTPRequestHandler):
    """HTTP 请求处理器
    HTTP request handler
    """
    def do_GET(self):
        """处理 GET 请求 - 健康检查
        Handle GET request - health check
        """
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": "ok", "service": "agent"}).encode())

    _MAX_BODY = 10 * 1024 * 1024  # 10MB (最大请求体 10MB)

    def do_POST(self):
        """处理 POST 请求 - 消息回调
        Handle POST request - message callback
        """
        length = int(self.headers.get("Content-Length", 0))
        if length > self._MAX_BODY:
            self.send_response(413)  # Payload Too Large
            self.end_headers()
            return
        body = self.rfile.read(length)

        try:
            data = json.loads(body.decode("utf-8"))
        except Exception as e:
            log.error(f"[http] parse error: {e}")
            self.send_response(400)  # Bad Request
            self.end_headers()
            return

        # /api/chat — LLM reply for Jetson voice (sync or SSE stream)
        if self.path == "/api/chat":
            msg = data.get("message", "")
            session_key = data.get("session_key", "voice")
            stream = data.get("stream", False)
            if not msg:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":"message required"}')
                return

            from datetime import datetime, timezone, timedelta
            cst = timezone(timedelta(hours=8))
            now = datetime.now(cst).strftime("%Y-%m-%d %H:%M:%S")
            tagged_msg = f"[Source: voice assistant | Beijing time: {now}]" + chr(10) + msg

            if stream:
                # SSE streaming response
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("X-Accel-Buffering", "no")
                    self.end_headers()
                    for chunk in llm.chat_stream(tagged_msg, session_key, user_config=USERS.get(next(iter(USERS), ""))):
                        sse = json.dumps({"choices":[{"delta":{"content": chunk}}]},
                                         ensure_ascii=False)
                        sse_line = "data: " + sse + chr(10) + chr(10)
                        self.wfile.write(sse_line.encode())
                        self.wfile.flush()
                    done_line = "data: [DONE]" + chr(10) + chr(10)
                    self.wfile.write(done_line.encode())
                    self.wfile.flush()
                except Exception as e:
                    log.error(f"[api/chat] stream error: {e}", exc_info=True)
                return
            else:
                # Synchronous response (original path)
                try:
                    reply = llm.chat(tagged_msg, session_key, user_config=USERS.get(next(iter(USERS), "")))
                    result = json.dumps({"reply": reply}, ensure_ascii=False)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(result.encode("utf-8"))
                except Exception as e:
                    log.error(f"[api/chat] error: {e}")
                    self.send_response(500)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": str(e)}).encode())
                return

        # Other routes: send 200 immediately, process async
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"")

        if self.path == "/test":
            msg = data.get("message", "")
            if msg:
                def _test():
                    reply = llm.chat(msg, "test", user_config=USERS.get(next(iter(USERS), "")))
                    log.info(f"[test] reply: {reply[:200]}")
                threading.Thread(target=_test, daemon=True).start()
            return

        threading.Thread(target=handle_callback, args=(data,), daemon=True).start()

    def log_message(self, format, *args):
        pass

# ============================================================
#  Main - 主函数
# ============================================================

def main():
    """主入口函数
    Main entry function
    """
    scheduler.start()
    log.info(f"[agent] starting on port {PORT}")
    log.info(f"[agent] workspace={WORKSPACE}")
    log.info(f"[agent] users={list(USERS.keys())}")
    log.info(f"[agent] model={CONFIG['models']['default']}")
    log.info(f"[agent] files_dir={FILES_DIR}")
    if XFYUN_CONFIG:
        log.info(f"[agent] xfyun ASR enabled (app_id={XFYUN_CONFIG.get('app_id', '?')})")

    # ThreadingMixIn: each request in independent thread, prevents single connection from blocking
    # ThreadingMixIn：每个请求在独立线程中，防止单个连接阻塞
    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    server = ThreadedHTTPServer(("0.0.0.0", PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("[agent] shutting down")
        try:
            import mcp_client
            mcp_client.shutdown()
        except Exception:
            pass
        server.server_close()


if __name__ == "__main__":
    main()
