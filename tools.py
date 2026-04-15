"""
Tool Registry — Orchestration Layer
工具注册表 — 编排层

All LLM-callable tool definitions + implementations, split across domain modules:
所有 LLM 可调用的工具定义和实现，分布在各个域模块中：

  tools_base.py      — registry, decorator, helpers (注册表、装饰器、辅助函数)
  tools_messaging.py — exec/message/files/schedule/media (执行/消息/文件/调度/媒体)
  tools_video.py     — trim/bgm/generate_video (剪辑/背景音乐/生成视频)
  tools_search.py    — web_search/memory/recall (网络搜索/记忆/回忆)
  tools_admin.py     — diagnose/audit/plugins/mcp/archive (诊断/审计/插件/MCP/归档)
  tools_page.py      — render_page (交互式 HTML 页面生成)
  tools_mirror.py    — soul_report/future_self (AI 镜像/灵魂报告/未来自我)

## Adding a new tool: 添加新工具
1. Write a function in the corresponding domain module (在对应域模块中编写函数)
2. Decorate with @tool (使用@tool 装饰器)

No other files need to be modified. (无需修改其他文件)

## Architecture: 架构说明
- 工具注册表采用装饰器模式
- 每个工具在定义时自动注册到全局_registry
- LLM 通过 get_definitions() 获取所有工具定义
- 通过 execute() 函数调用具体工具实现
"""

# Import sub-modules (triggers @tool registration)
# 导入子模块（触发@tool 注册）
# noqa: F401 表示"已导入但未使用"，实际是通过导入触发装饰器注册
from tools_base import get_definitions, execute, _strip_markdown, _split_message  # noqa: F401
import tools_messaging  # noqa: F401
import tools_video  # noqa: F401
import tools_search  # noqa: F401
import tools_admin  # noqa: F401
import tools_page  # noqa: F401
import tools_mirror  # noqa: F401


def init_extra(config):
    """Called by main entry point to pass extra configuration
    主入口调用此函数传递额外配置
    
    初始化各子模块所需的配置：
    1. 搜索引擎 API 密钥
    2. 视频生成 API 配置
    3. 插件加载
    4. MCP 服务器连接
    
    参数:
        config: 完整配置字典（从 config.json 加载）
    """
    # Search engine config (搜索引擎配置)
    tools_search.init_search_config(config)
    # Video API config (视频 API 配置)
    tools_video.set_video_config(config.get("video_api", {}))
    # Plugin loading (插件加载)
    tools_admin._load_plugins()
    # MCP servers (MCP 服务器连接)
    tools_admin._load_mcp_servers(config)

# Import sub-modules (triggers @tool registration)
from tools_base import get_definitions, execute, _strip_markdown, _split_message  # noqa: F401
import tools_messaging  # noqa: F401
import tools_video  # noqa: F401
import tools_search  # noqa: F401
import tools_admin  # noqa: F401
import tools_page  # noqa: F401
import tools_mirror  # noqa: F401


def init_extra(config):
    """Called by main entry point to pass extra configuration"""
    # Search engine config
    tools_search.init_search_config(config)
    # Video API config
    tools_video.set_video_config(config.get("video_api", {}))
    # Plugin loading
    tools_admin._load_plugins()
    # MCP servers
    tools_admin._load_mcp_servers(config)
