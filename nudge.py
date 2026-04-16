"""
Nudge Registry — 提示注册表

检测 LLM"有工具但不使用"时自动注入提示的系统。

核心原理:
Code-level implementation of Principle 2: don't rely on prompts to constrain behavior,
use structure to make errors impossible.
原则 2 的代码级实现：不依赖提示词约束行为，用结构让错误不可能发生。

当 LLM 搜索到结果但忘记发送位置卡片，或说"已记录"但没调用 write_file 时，
系统自动注入提示消息，让 LLM 再运行一轮执行。

使用方法（在 llm.py 工具循环末尾）:
    nudge_msg = check_nudges(tools_called, reply_text, tool_results)
    if nudge_msg:
        messages.append({"role": "user", "content": nudge_msg})
        continue  # Let LLM run one more iteration (让 LLM 再运行一轮)

内置规则:
1. search_nearby->send_location: 搜索附近返回结果但未发送位置卡片
2. said_recorded->write_file: 说"已记录"但未调用 write_file
3. said_scheduled->schedule: 说"已安排"但未调用 schedule
4. structured_data->render_page: 有结构化数据但未调用 render_page
5. self_reflect->soul_report: 进行行为分析但未生成灵魂报告

设计原则:
- 结构性纠正：不依赖 LLM 记忆，用代码强制检查
- 最小干预：只在必要时注入提示
- 防止死循环：max_fires 限制触发次数
- 可扩展：通过 register() 添加新规则

工作流程:
1. LLM 回复后，检查已调用的工具和回复文本
2. 匹配 nudge 规则（触发函数返回 True）
3. 如果触发且未达上限，注入提示消息
4. LLM 收到提示后重新运行一轮，执行遗漏的操作

技术实现:
- 规则注册表模式（_nudge_rules 列表）
- 触发函数（trigger_fn）判断是否满足条件
- 触发计数（_fire_counts）防止无限循环
- 上下文对象（ctx）传递工具调用、回复文本、工具结果

扩展方法:
    register(
        "规则名称",
        lambda ctx: 触发条件，
        "注入给 LLM 的提示文本",
        max_fires=1  # 最大触发次数
    )
"""

import logging
import re

log = logging.getLogger("agent")

# ============================================================
#  Nudge Rule Registry - 提示规则注册表
# ============================================================

_nudge_rules = []  # 提示规则列表


def register(name, trigger_fn, message, max_fires=1):
    """Register a nudge rule.
    注册提示规则
    
    参数:
        name: 规则名称
        trigger_fn: 触发函数，签名 trigger_fn(ctx) -> bool
            ctx = {"tools_called": set, "reply_text": str, "tool_results": dict}
        message: 注入给 LLM 的提示文本
        max_fires: 每次聊天会话最大触发次数（防止死循环）
    
    工作原理:
        - 在 LLM 回复后检查是否满足触发条件
        - 如果满足则注入提示消息，让 LLM 重新运行一轮
        - 通过 max_fires 防止无限循环
    """
    _nudge_rules.append({
        "name": name,
        "trigger": trigger_fn,
        "message": message,
        "max_fires": max_fires,
    })


# ============================================================
#  Built-in Nudge Rules
# ============================================================

def _search_nearby_no_location(ctx):
    """search_nearby returned results but LLM didn't call send_location"""
    if "search_nearby" not in ctx["tools_called"]:
        return False
    if "send_location" in ctx["tools_called"]:
        return False
    for name, result in ctx.get("tool_results", {}).items():
        if name == "search_nearby" and result and "[error]" not in str(result)[:50]:
            return True
    return False


def _said_recorded_no_write(ctx):
    """LLM said 'noted/recorded' but didn't call write_file"""
    if "write_file" in ctx["tools_called"]:
        return False
    if "read_file" in ctx["tools_called"]:
        return False
    text = ctx.get("reply_text", "")
    return bool(re.search(r"(?:noted|recorded|saved|got it|written down)", text, re.I))


def _said_scheduled_no_schedule(ctx):
    """LLM said 'scheduled/set up' a task but didn't call schedule"""
    if "schedule" in ctx["tools_called"]:
        return False
    text = ctx.get("reply_text", "")
    return bool(re.search(
        r"(?:reminder|alarm|task|schedule).*(?:set up|created|arranged|done)|"
        r"(?:set up|created|arranged|done).*(?:reminder|alarm|task|schedule)",
        text, re.I
    ))


def _structured_data_no_render(ctx):
    """Reply contains structured data but didn't call render_page"""
    if "render_page" in ctx["tools_called"]:
        return False
    text = ctx.get("reply_text", "")
    lines = text.strip().splitlines()
    data_lines = sum(1 for line in lines
                     if re.search(r'[\d.]+\s*[%$]|[\d.]+\s*/\s*[\d.]+', line))
    return data_lines >= 3


# Register 4 initial rules
register(
    "search_nearby->send_location",
    _search_nearby_no_location,
    "[system] search_nearby returned location results, but you did not send location cards. "
    "Please use the send_location tool to send each found location to the user. "
    "Users expect clickable location cards, not plain text.",
)

register(
    "said_recorded->write_file",
    _said_recorded_no_write,
    "[system] You said 'noted/recorded', but didn't call write_file to persist it. "
    "Conversation memory gets truncated — only writing to a file counts as truly recorded. "
    "Please immediately use write_file to save to the appropriate memory/ file.",
)

register(
    "said_scheduled->schedule",
    _said_scheduled_no_schedule,
    "[system] You said a reminder/task was set up, but didn't call the schedule tool. "
    "Please immediately call the schedule tool to create the task. "
    "A verbal promise is not execution.",
)

register(
    "structured_data->render_page",
    _structured_data_no_render,
    "[system] Your reply contains structured comparison data. "
    "Please call render_page to generate a visual table for easier reading.",
)


# ============================================================
#  Check Entry Point
# ============================================================

# Per-chat fire counts (reset at start of each chat)
_fire_counts = {}  # rule_name -> count


def reset():
    """Called at start of each new chat session to reset fire counts."""
    _fire_counts.clear()


def check_nudges(tools_called, reply_text, tool_results=None):
    """Check if any nudge rules trigger. Returns nudge message or None.

    tool_results: {tool_name: result_str} from the most recent tool loop iteration
    """
    ctx = {
        "tools_called": tools_called,
        "reply_text": reply_text,
        "tool_results": tool_results or {},
    }

    for rule in _nudge_rules:
        name = rule["name"]
        fired = _fire_counts.get(name, 0)
        if fired >= rule["max_fires"]:
            continue
        try:
            if rule["trigger"](ctx):
                _fire_counts[name] = fired + 1
                log.info("[nudge] triggered: %s (fire %d/%d)", name, fired + 1, rule["max_fires"])
                return rule["message"]
        except Exception as e:
            log.error("[nudge] error in rule %s: %s", name, e)

    return None


# -- AI Mirror: self-reflection -> soul_report --

def _self_reflect_no_report(ctx):
    """LLM is giving verbal behavior analysis but didn't use soul_report"""
    if "soul_report" in ctx["tools_called"]:
        return False
    text = ctx.get("reply_text", "")
    if len(text) < 60:
        return False
    return bool(re.search(
        r"I\'ve observed|I notice that you|looking at your conversations"
        r"|your habits|your patterns|your recent behavior"
        r"|I suggest you|you need to improve|you tend to",
        text, re.I
    ))


register(
    "self_reflect->soul_report",
    _self_reflect_no_report,
    "[system] The user seems to be seeking self-reflection/behavior analysis. "
    "You can use the soul_report tool to generate a data-driven behavioral profile report, "
    "which is more convincing than verbal analysis. Consider calling soul_report.",
)
