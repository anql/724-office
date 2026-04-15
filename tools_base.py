"""
Tool Registry Base — registry, decorator, helpers
工具注册表基类 — 注册表、装饰器、辅助函数

All tool sub-modules import from here.
所有工具子模块从这里导入。
"""

import json
import re
import logging
import os
import random

log = logging.getLogger("agent")

# ============================================================
#  Tool Registry - 工具注册表
# ============================================================

_registry = {}  # name -> {"fn", "definition"} (工具名称 -> 函数和定义)


def tool(name, description, properties, required=None):
    """Decorator: register an LLM tool
    装饰器：注册一个 LLM 工具
    """
    def decorator(fn):
        _registry[name] = {
            "fn": fn,
            "definition": {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        **({"required": required} if required else {}),
                    },
                },
            },
        }
        return fn
    return decorator


def get_definitions():
    """Return all tool OpenAI function calling definitions
    返回所有工具的 OpenAI 函数调用定义
    """
    return [entry["definition"] for entry in _registry.values()]


# Context profile — filter tools by session type to reduce token usage
# 上下文配置 — 按会话类型过滤工具以减少 token 使用
# voice: keep only core interaction tools (~15)
# voice：仅保留核心交互工具（约 15 个）
# scheduler: exclude scheduling tools to prevent circular creation (~25)
# scheduler：排除调度工具防止循环创建（约 25 个）
# group: exclude dangerous tools + admin tools (~20)
# group：排除危险工具 + 管理工具（约 20 个）
# default: full set (conservative start)
# default：完整集合（保守开始）
_TOOL_EXCLUDE_PROFILES = {
    "voice": {
        "trim_video", "add_bgm", "generate_video", "code_audit", "diagnose",
        "task_history", "create_tool", "list_custom_tools", "remove_tool",
        "reload_mcp", "compact_memory", "compact_guides", "asr_check",
        "daily_digest", "archive", "render_page", "self_check",
        "send_namecard", "send_location", "search_nearby",
        "soul_report", "future_self",
    },
    "scheduler": {
        "schedule", "list_schedules", "remove_schedule",  # Prevent circular creation (防止循环创建)
        "trim_video", "add_bgm", "generate_video",
        "create_tool", "list_custom_tools", "remove_tool",
        "reload_mcp",
        "soul_report", "future_self",
    },
    "group": {
        "exec", "edit_file",  # GROUP_RESTRICTED (群聊受限)
        "code_audit", "diagnose", "self_check", "asr_check",
        "create_tool", "list_custom_tools", "remove_tool",
        "reload_mcp", "compact_memory", "compact_guides",
        "daily_digest", "archive", "task_history",
        "soul_report", "future_self",
    },
}


def get_filtered_definitions(session_key="", is_group=False):
    """Return filtered tool definitions by context profile.
    根据上下文配置返回过滤后的工具定义。

    Reduces token usage: voice saves ~18KB/request, scheduler saves ~15KB/request.
    减少 token 使用：voice 每请求节省约 18KB，scheduler 每请求节省约 15KB。
    """
    if is_group:
        profile = "group"
    elif session_key == "voice" or session_key.startswith("voice"):
        profile = "voice"
    elif session_key.startswith("scheduler"):
        profile = "scheduler"
    else:
        profile = "default"

    exclude = _TOOL_EXCLUDE_PROFILES.get(profile, set())
    if not exclude:
        defs = [entry["definition"] for entry in _registry.values()]
    else:
        defs = [entry["definition"] for name, entry in _registry.items()
                if name not in exclude]

    log.info("[tools] profile=%s, tools=%d (excluded=%d)", profile, len(defs), len(exclude))
    return defs


# ============================================================
#  Pre-reply — Status hints for long-running tools - 预回复提示
# ============================================================

_TOOL_HINTS = {
    "web_search": [
        "Let me search that for you",
        "One moment, looking it up",
        "Searching the web...",
    ],
    "generate_video": [
        "Video generation started, will send when ready",
        "Starting video generation, takes a few minutes",
    ],
    "code_audit": [
        "Running code health check",
        "One moment, checking the code",
    ],
    "send_file": [
        "One moment, sending the file",
        "Processing the file for you",
    ],
    "send_image": [
        "Sending the image now",
        "Image coming right up",
    ],
    "send_video": [
        "Processing the video for you",
        "Sending the video now",
    ],
    "recall": [
        "Let me check my memory",
        "Thinking back...",
    ],
    "search_memory": [
        "Searching my records",
        "Looking through my notes",
    ],
}


def _pre_reply(tool_name, ctx):
    """Send status hint to user before tool execution
    工具执行前发送状态提示给用户
    """
    # Scheduled tasks don't send hints (weather/news go straight to result)
    # 调度任务不发送提示（天气/新闻直接发送结果）
    if ctx.get("session_key", "").startswith("scheduler"):
        return
    # Max 1 hint per chat() call (prevent spam from multi-tool searches)
    # 每次 chat() 调用最多 1 个提示（防止多工具搜索时刷屏）
    if ctx.get("_pre_reply_sent"):
        return
    # Don't send during bootstrap (LLM handles its own intro)
    # 引导期间不发送（LLM 自己处理介绍）
    workspace = ctx.get("workspace", "")
    if workspace and not os.path.exists(os.path.join(workspace, ".bootstrapped")):
        return
    hints = _TOOL_HINTS.get(tool_name)
    if not hints:
        return
    hint = random.choice(hints)
    to_id = ctx.get("group_id") if ctx.get("is_group") else ctx.get("owner_id")
    if not to_id:
        return
    try:
        import messaging
        messaging.send_text(to_id, hint)
        ctx["_pre_reply_sent"] = True
        log.info(f"[pre_reply] {tool_name} -> \"{hint}\"")
    except Exception as e:
        log.warning(f"[pre_reply] failed: {e}")


# Tools restricted in group chat (write_file/schedule allowed: groups need file gen + reminders)
# 群聊中受限的工具（write_file/schedule 允许：群聊需要文件生成 + 提醒）
GROUP_RESTRICTED = {"exec", "edit_file"}


# Circuit breaker: consecutive failure count (per-session)
# 熔断器：连续失败计数（每会话）
_tool_fail_counts = {}  # (session_key, tool_name) -> count (失败次数)
_CIRCUIT_BREAKER_THRESHOLD = 3  # 熔断阈值


def execute(name, args, ctx):
    """Execute tool, return result string. Triggers circuit breaker after 3 consecutive failures.
    执行工具，返回结果字符串。连续 3 次失败后触发熔断器。
    """
    log.info(f"[tool] {name}({json.dumps(args, ensure_ascii=False)[:200]})")

    # Restrict dangerous tools in group chat
    # 群聊中限制危险工具
    if ctx.get("is_group") and name in GROUP_RESTRICTED:
        log.warning("[tool] %s blocked in group chat", name)
        return "[error] this tool is not available in group chat, please DM me"

    # Circuit breaker check
    # 熔断器检查
    fail_key = (ctx.get("session_key", ""), name)
    if _tool_fail_counts.get(fail_key, 0) >= _CIRCUIT_BREAKER_THRESHOLD:
        log.warning("[tool] %s circuit breaker triggered (>=%d consecutive failures)",
                    name, _CIRCUIT_BREAKER_THRESHOLD)
        return (f"[error] {name} has failed {_CIRCUIT_BREAKER_THRESHOLD} consecutive times, "
                "temporarily disabled. Please try a different approach or inform the user.")

    # Pre-reply status hint
    # 预回复状态提示
    _pre_reply(name, ctx)

    entry = _registry.get(name)
    if not entry:
        return f"[error] unknown tool: {name}"
    try:
        result = entry["fn"](args, ctx)
        # Success: reset failure count
        # 成功：重置失败计数
        _tool_fail_counts.pop(fail_key, None)
        # Global safety net: prevent any tool's oversized output from blowing up context
        # 全局安全网：防止任何工具的超大输出撑爆上下文
        if isinstance(result, str) and len(result) > 12000:
            log.warning("[tool] %s output truncated: %d -> 12000", name, len(result))
            trunc_msg = "\n... [truncated at 12000/%d chars]" % len(result)
            result = result[:12000] + trunc_msg
        return result
    except Exception as e:
        log.error(f"[tool] {name} error: {e}", exc_info=True)
        _tool_fail_counts[fail_key] = _tool_fail_counts.get(fail_key, 0) + 1
        count = _tool_fail_counts[fail_key]
        if count >= _CIRCUIT_BREAKER_THRESHOLD:
            return (f"[error] {name} failed {count} consecutive times: {e}. "
                    "This tool is temporarily disabled, please try a different approach.")
        return f"[error] {e} (retryable, {count} failures so far)"

# ============================================================
#  Shared Helpers - 共享辅助函数
# ============================================================

def _resolve_path(path, workspace):
    """解析路径，防止目录遍历攻击
    Resolve path, prevent directory traversal attack
    """
    resolved = os.path.realpath(os.path.join(workspace, path))
    ws_real = os.path.realpath(workspace)
    if not resolved.startswith(ws_real + os.sep) and resolved != ws_real:
        raise ValueError('path traversal blocked: %s' % path)
    return resolved


def _strip_markdown(text):
    """Convert markdown to mobile-friendly plain text.
    将 Markdown 转换为适合移动设备的纯文本。
    """
    lines = text.split("\n")
    out = []
    in_table = False
    headers = []
    for line in lines:
        stripped = line.strip()
        if re.match(r"^\|[\s\-:|]+\|$", stripped):
            in_table = True
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not in_table:
                headers = cells
                in_table = True
                continue
            else:
                if headers and len(headers) == len(cells):
                    parts = ["%s: %s" % (h, c) for h, c in zip(headers, cells) if c]
                    out.append("  " + " | ".join(parts))
                else:
                    out.append("  " + " | ".join(cells))
                continue
        else:
            if in_table:
                in_table = False
                headers = []
        out.append(line)
    text = "\n".join(out)
    # 移除加粗 (Remove bold)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    # 移除斜体 (Remove italic)
    text = re.sub(r"(?<![\w])\*(.+?)\*(?![\w])", r"\1", text)
    # 移除标题 (Remove headers)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # 移除分隔线 (Remove separators)
    text = re.sub(r"^[\s]*[-*]{3,}[\s]*$", "", text, flags=re.MULTILINE)
    # 移除行内代码 (Remove inline code)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # 压缩多余空行 (Compress extra blank lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def _split_message(text, max_bytes=1800):
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
