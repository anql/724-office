# 7/24 Office -- 自进化 AI Agent 系统

一个生产级运行的 AI agent，使用 **约 10,000 行纯 Python** 构建，**零框架依赖**。没有 LangChain，没有 LlamaIndex，没有 CrewAI -- 只有标准库 + 几个小型包。

**36 个工具。20 个文件。模块化架构。7×24 小时运行。**

使用 AI 协同开发工具独立构建。为多用户 7×24 小时生产运行。

---

# 7/24 Office -- Self-Evolving AI Agent System

A production-running AI agent built in **~10,000 lines of pure Python** with **zero framework dependency**. No LangChain, no LlamaIndex, no CrewAI -- just the standard library + a few small packages.

**36 tools. 20 files. Modular architecture. Runs 24/7.**

Built solo with AI co-development tools. Production 24/7 across multiple users.

## v2.0 新功能

- **模块化工具架构** -- 从单体 `tools.py` 拆分为 7 个领域模块
- **群聊支持** -- 独立的群聊容器，支持 @ 提及门控
- **AI 镜像** -- 行为画像报告（`soul_report`）+ 未来自我对话模式（`future_self`）
- **助推系统** -- 结构化行为纠正：自动检测 LLM 有工具但不使用的情况
- **动态工具过滤** -- 5 种上下文配置（语音/调度器/群聊/诊断/默认）以减少 token 浪费
- **预算感知系统提示** -- 系统提示组装期间的 token 预算跟踪
- **非活跃守卫** -- 自动跳过休眠用户的 cron 任务（3 天阈值）
- **断路器** -- 每次会话连续失败 3 次后禁用工具
- **交互式可视化** -- 基于 ECharts 的 HTML 页面，通过 `render_page`（折线/柱状/饼图/雷达/表格/报告）
- **容器协调** -- 路由器启动时自动从路由表重建缺失的容器
- **指数退避重试** -- 消息 API 调用重试 3 次，延迟 2/4/8 秒
- **会话自动归档** -- 每日黑盒记录所有对话

## What's New in v2.0

- **Modular tool architecture** -- Split from monolithic `tools.py` into 7 domain modules
- **Group chat support** -- Independent container for group conversations with @-mention gating
- **AI Mirror** -- Behavioral profile reports (`soul_report`) + future-self dialogue mode (`future_self`)
- **Nudge system** -- Structural behavior correction: auto-detects when LLM has tools but doesn't use them
- **Dynamic tool filtering** -- 5 context profiles (voice/scheduler/group/diagnostic/default) to reduce token waste
- **Budget-aware system prompt** -- Token budget tracking during system prompt assembly
- **Inactivity guard** -- Auto-skip cron tasks for dormant users (3-day threshold)
- **Circuit breaker** -- Disable tools after 3 consecutive failures per session
- **Interactive visualization** -- ECharts-based HTML pages via `render_page` (line/bar/pie/radar/table/report)
- **Container reconciliation** -- Router auto-rebuilds missing containers from routing table on startup
- **Exponential backoff retry** -- Messaging API calls retry 3x with 2/4/8s delays
- **Session auto-archiving** -- Daily black box recording of all conversations

## 功能特性

- **工具使用循环** -- OpenAI 兼容的函数调用，自动重试，每次对话最多 20 次迭代
- **三层记忆** -- 会话历史 + LLM 压缩的长期记忆 + LanceDB 向量检索
- **MCP/插件系统** -- 通过 JSON-RPC（stdio 或 HTTP）连接外部 MCP 服务器，无需重启即可热加载
- **运行时工具创建** -- Agent 可以在运行时编写、保存和加载新的 Python 工具（`create_tool`）
- **自修复** -- 每日自检、会话健康诊断、错误日志分析、失败时自动通知
- **Cron 调度** -- 一次性和重复性任务，重启后持久化，时区感知，非活跃守卫
- **多租户路由器** -- 基于 Docker 的自动配置，每用户一个容器，健康检查，协调机制
- **多模态** -- 图像/视频/文件/语音/链接处理，ASR（语音转文字），通过 base64 的视觉能力
- **网络搜索** -- 多引擎（Tavily、Bocha、GitHub、HuggingFace），自动路由，默认双引擎
- **视频处理** -- 剪辑（智能静音检测）、添加背景音乐、通过 API 的 AI 视频生成
- **消息集成** -- 可插拔的消息平台，支持防抖、消息分割、流式媒体上传
- **群聊** -- 独立容器、@提及门控、上下文缓冲区（最后 20 条消息）、说话人识别

## Features

- **Tool Use Loop** -- OpenAI-compatible function calling with automatic retry, up to 20 iterations per conversation
- **Three-Layer Memory** -- Session history + LLM-compressed long-term memory + LanceDB vector retrieval
- **MCP/Plugin System** -- Connect external MCP servers via JSON-RPC (stdio or HTTP), hot-reload without restart
- **Runtime Tool Creation** -- The agent can write, save, and load new Python tools at runtime (`create_tool`)
- **Self-Repair** -- Daily self-check, session health diagnostics, error log analysis, auto-notification on failure
- **Cron Scheduling** -- One-shot and recurring tasks, persistent across restarts, timezone-aware, inactivity guard
- **Multi-Tenant Router** -- Docker-based auto-provisioning, one container per user, health-checked, reconciliation
- **Multimodal** -- Image/video/file/voice/link handling, ASR (speech-to-text), vision via base64
- **Web Search** -- Multi-engine (Tavily, Bocha, GitHub, HuggingFace) with auto-routing and dual-engine default
- **Video Processing** -- Trim (with intelligent silence detection), add BGM, AI video generation via API
- **Messaging Integration** -- Pluggable messaging platform with debounce, message splitting, streaming media upload
- **Group Chat** -- Independent container, @-mention gating, context buffer (last 20 messages), speaker identification

## Architecture

```
                    +-----------------+
                    |  Messaging      |
                    |  Platform       |
                    +--------+--------+
                             |
                    +--------v--------+
                    |   router.py     |  Multi-tenant routing
                    |  Auto-provision |  Container reconciliation
                    |  Group routing  |  Health checking
                    +--------+--------+
                             |
                    +--------v--------+
                    | xiaowang.py     |  Entry point
                    |  HTTP server    |  Callback handling
                    |  Debounce       |  Media download/ASR
                    |  Group support  |  Inactivity tracking
                    +--------+--------+
                             |
                    +--------v--------+
                    |    llm.py       |  Tool Use Loop (core)
                    |  Budget-aware   |  Session management
                    |  system prompt  |  Nudge integration
                    |  Multimodal     |  Memory injection
                    +--------+--------+
                             |
     +----------+----+------+------+----+-----------+
     |          |    |             |    |           |
+----v-----+ +-v----v--+ +-------v-+ +-v--------+ |
| tools_    | |tools_   | |tools_   | |tools_    | |
| messaging | |admin    | |search   | |video     | |
| send/file | |exec/diag| |web/mem  | |trim/bgm  | |
| schedule  | |plugin   | |recall   | |generate  | |
+-----------+ |MCP      | +---------+ +----------+ |
              +----+----+                           |
              +----v----+  +----------+  +----------v--+
              |tools_   |  |tools_    |  |  nudge.py   |
              |page     |  |mirror    |  |  5 rules    |
              |ECharts  |  |soul rpt  |  |  auto-hint  |
              |6 types  |  |future    |  +-------------+
              +---------+  |self      |
                           +----------+
              +--------------+--------------+
              |              |              |
       +------v------+  +---v--------+  +--v-----------+
       | memory.py   |  |scheduler.py|  | archive.py   |
       | 3-layer     |  | cron+once  |  | daily black  |
       | compress    |  | inactivity |  | box recorder |
       | deduplicate |  | guard      |  +--------------+
       | retrieve    |  +------------+
       +------+------+
              |
       +------v------+
       |mcp_client.py|  JSON-RPC over stdio/HTTP
       | Auto-reconnect + Hot-reload
       +-------------+
```

## 记忆系统

```
第一层：会话（短期）
  - 每个会话最后 40 条消息，JSON 文件
  - 溢出时触发压缩
  - 自动归档 >100KB 的会话

第二层：压缩（长期）
  - LLM 从淘汰的消息中提取结构化事实
  - 通过余弦相似度去重（阈值：0.92）
  - 作为向量存储在 LanceDB 中

第三层：检索（主动回忆）
  - 用户消息 -> 嵌入 -> 向量搜索
  - Top-K 相关记忆注入到系统提示
  - 预算感知注入（跟踪 token 使用）
```

## Memory System

```
Layer 1: Session (short-term)
  - Last 40 messages per session, JSON files
  - Overflow triggers compression
  - Auto-archive sessions >100KB

Layer 2: Compressed (long-term)
  - LLM extracts structured facts from evicted messages
  - Deduplication via cosine similarity (threshold: 0.92)
  - Stored as vectors in LanceDB

Layer 3: Retrieval (active recall)
  - User message -> embedding -> vector search
  - Top-K relevant memories injected into system prompt
  - Budget-aware injection (tracks token usage)
```

## 工具列表（36 个内置工具）

| 类别 | 模块 | 工具 |
|------|------|------|
| 核心 | `tools_admin` | `exec`, `message` |
| 文件 | `tools_admin` | `read_file`, `write_file`, `edit_file`, `list_files` |
| 调度 | `tools_messaging` | `schedule`, `list_schedules`, `remove_schedule` |
| 媒体发送 | `tools_messaging` | `send_image`, `send_file`, `send_video`, `send_link`, `send_location`, `send_namecard` |
| 视频 | `tools_video` | `trim_video`（自动剪辑静音）, `add_bgm`, `generate_video` |
| 搜索 | `tools_search` | `web_search`（Tavily+Bocha 双引擎）, `search_nearby`（地理编码+POI）, `search_memory`, `recall` |
| 可视化 | `tools_page` | `render_page`（通过 ECharts 的折线/柱状/饼图/雷达/表格/报告） |
| AI 镜像 | `tools_mirror` | `soul_report`（行为画像 HTML）, `future_self`（对话模式） |
| 诊断 | `tools_admin` | `self_check`, `diagnose`, `task_history`, `code_audit`, `asr_check`, `daily_digest` |
| 记忆 | `tools_admin` | `compact_memory`, `compact_guides` |
| 插件 | `tools_admin` | `create_tool`, `list_custom_tools`, `remove_tool` |
| MCP | `tools_admin` | `reload_mcp` |

## Tool List (36 built-in)

| Category | Module | Tools |
|----------|--------|-------|
| Core | `tools_admin` | `exec`, `message` |
| Files | `tools_admin` | `read_file`, `write_file`, `edit_file`, `list_files` |
| Scheduling | `tools_messaging` | `schedule`, `list_schedules`, `remove_schedule` |
| Media Send | `tools_messaging` | `send_image`, `send_file`, `send_video`, `send_link`, `send_location`, `send_namecard` |
| Video | `tools_video` | `trim_video` (auto-cut silence), `add_bgm`, `generate_video` |
| Search | `tools_search` | `web_search` (Tavily+Bocha dual-engine), `search_nearby` (geocoding+POI), `search_memory`, `recall` |
| Visualization | `tools_page` | `render_page` (line/bar/pie/radar/table/report via ECharts) |
| AI Mirror | `tools_mirror` | `soul_report` (behavioral profile HTML), `future_self` (dialogue mode) |
| Diagnostics | `tools_admin` | `self_check`, `diagnose`, `task_history`, `code_audit`, `asr_check`, `daily_digest` |
| Memory | `tools_admin` | `compact_memory`, `compact_guides` |
| Plugins | `tools_admin` | `create_tool`, `list_custom_tools`, `remove_tool` |
| MCP | `tools_admin` | `reload_mcp` |

## 模块结构

| 文件 | 行数 | 职责 |
|------|------|------|
| `xiaowang.py` | ~1040 | 入口：配置、HTTP 服务器、回调、防抖、ASR、群聊支持 |
| `llm.py` | ~1260 | LLM API + 工具使用循环 + 预算感知系统提示 + 助推集成 |
| `tools.py` | ~37 | 编排层（导入领域模块） |
| `tools_base.py` | ~314 | 注册表 + @tool 装饰器 + 动态过滤 + 断路器 |
| `tools_messaging.py` | ~550 | 消息/文件/调度/位置/名片工具 |
| `tools_admin.py` | ~860 | 执行/文件操作/诊断/插件/MCP 管理 |
| `tools_mirror.py` | ~716 | AI 镜像：soul_report + future_self |
| `tools_page.py` | ~470 | 交互式 HTML 页面生成（ECharts） |
| `tools_search.py` | ~293 | 多引擎网络搜索 + 记忆搜索 |
| `tools_video.py` | ~394 | 视频剪辑/背景音乐/生成 |
| `messaging.py` | ~447 | 消息平台 API 封装 + CDN 上传/下载 |
| `memory.py` | ~1100 | 三层记忆（会话 + 压缩 + 向量） |
| `scheduler.py` | ~652 | Cron + 一次性调度 + 非活跃守卫 |
| `router.py` | ~500+ | 多租户 Docker 路由器 + 自动配置 + 协调 |
| `mcp_client.py` | ~342 | MCP 协议客户端（JSON-RPC，零新依赖） |
| `nudge.py` | ~190 | 助推系统：检测工具误用，自动注入提示 |
| `archive.py` | ~204 | 每日会话归档（黑盒记录器） |
| `audit.py` | ~448 | 自动化 11 项代码审计 |

## Module Structure

| File | Lines | Responsibility |
|------|-------|---------------|
| `xiaowang.py` | ~1040 | Entry: config, HTTP server, callbacks, debounce, ASR, group support |
| `llm.py` | ~1260 | LLM API + tool use loop + budget-aware system prompt + nudge integration |
| `tools.py` | ~37 | Orchestration layer (imports domain modules) |
| `tools_base.py` | ~314 | Registry + @tool decorator + dynamic filtering + circuit breaker |
| `tools_messaging.py` | ~550 | Message/file/schedule/location/namecard tools |
| `tools_admin.py` | ~860 | Exec/file ops/diagnostics/plugins/MCP management |
| `tools_mirror.py` | ~716 | AI Mirror: soul_report + future_self |
| `tools_page.py` | ~470 | Interactive HTML page generation (ECharts) |
| `tools_search.py` | ~293 | Multi-engine web search + memory search |
| `tools_video.py` | ~394 | Video trim/BGM/generation |
| `messaging.py` | ~447 | Messaging platform API wrapper + CDN upload/download |
| `memory.py` | ~1100 | Three-layer memory (session + compressed + vector) |
| `scheduler.py` | ~652 | Cron + one-shot scheduling + inactivity guard |
| `router.py` | ~500+ | Multi-tenant Docker router + auto-provisioning + reconciliation |
| `mcp_client.py` | ~342 | MCP protocol client (JSON-RPC, zero new deps) |
| `nudge.py` | ~190 | Nudge system: detect tool misuse, auto-inject hints |
| `archive.py` | ~204 | Daily session archiving (black box recorder) |
| `audit.py` | ~448 | Automated 11-check code audit |

## 快速开始

### 方式 1：直接运行

```bash
git clone https://github.com/wangziqi06/724-office.git
cd 724-office
cp config.example.json config.json
# 在 config.json 中编辑你的 API 密钥

pip install croniter lancedb websocket-client pilk numpy httpx beautifulsoup4 pydub jieba fpdf2

mkdir -p workspace/memory workspace/files
python3 xiaowang.py
```

### 方式 2：Docker 部署（推荐）

```bash
# 复制 Dockerfile.example -> Dockerfile
# 复制 docker-compose.example.yml -> docker-compose.yml
# 在 .env 中编辑你的凭据

docker compose build
docker compose up -d
```

Agent 在端口 8080 上启动 HTTP 服务器。将你的消息平台 webhook 指向 `http://YOUR_SERVER:8080/`。

## Quick Start

### Option 1: Direct Run

```bash
git clone https://github.com/wangziqi06/724-office.git
cd 724-office
cp config.example.json config.json
# Edit config.json with your API keys

pip install croniter lancedb websocket-client pilk numpy httpx beautifulsoup4 pydub jieba fpdf2

mkdir -p workspace/memory workspace/files
python3 xiaowang.py
```

### Option 2: Docker Deployment (Recommended)

```bash
# Copy Dockerfile.example -> Dockerfile
# Copy docker-compose.example.yml -> docker-compose.yml
# Edit .env with your credentials

docker compose build
docker compose up -d
```

The agent starts an HTTP server on port 8080. Point your messaging platform webhook to `http://YOUR_SERVER:8080/`.

## 配置

查看 `config.example.json` 了解完整的配置结构。主要部分：

- **models** -- LLM 提供商（任何 OpenAI 兼容的 API）和故障转移链
- **messaging** -- 消息平台凭据和端点
- **memory** -- 三层记忆系统设置（嵌入 API、相似度阈值）
- **asr** -- 语音转文字 API 凭据
- **video_api** -- AI 视频生成 API
- **mcp_servers** -- MCP 服务器连接（stdio 或 HTTP 传输）
- **page_base_url** -- 生成的可视化页面的基础 URL

## Configuration

See `config.example.json` for the full configuration structure. Key sections:

- **models** -- LLM providers (any OpenAI-compatible API) with fallback chain
- **messaging** -- Messaging platform credentials and endpoints
- **memory** -- Three-layer memory system settings (embedding API, similarity threshold)
- **asr** -- Speech-to-text API credentials
- **video_api** -- AI video generation API
- **mcp_servers** -- MCP server connections (stdio or HTTP transport)
- **page_base_url** -- Base URL for generated visualization pages

## 设计原则

1. **零框架依赖** -- 每一行代码都可见且可调试。没有魔法。没有隐藏的抽象。
2. **模块化工具** -- 添加功能 = 在适当的领域模块中添加一个 `@tool` 装饰的函数。
3. **边缘可部署** -- 设计用于在 Jetson Orin Nano（8GB RAM，ARM64）上运行。RAM 预算低于 2GB。
4. **自进化** -- Agent 可以在运行时创建新工具，诊断自身问题，并通知所有者。
5. **结构化行为纠正** -- 不要用提示来修复 Agent 的错误。添加助推、钩子和验证。
6. **为删除而构建** -- 当模型变得更智能时，每个模块都应该可以干净地移除。
7. **上下文是最稀缺的资源** -- Token 预算是核心设计约束，而不是计算。

## Design Principles

1. **Zero framework dependency** -- Every line is visible and debuggable. No magic. No hidden abstractions.
2. **Modular tools** -- Adding a capability = adding one `@tool`-decorated function in the appropriate domain module.
3. **Edge-deployable** -- Designed to run on Jetson Orin Nano (8GB RAM, ARM64). RAM budget under 2GB.
4. **Self-evolving** -- The agent can create new tools at runtime, diagnose its own issues, and notify the owner.
5. **Structural behavior correction** -- Don't fix agent mistakes with prompts. Add nudges, hooks, and validation.
6. **Build for deletion** -- Every module should be cleanly removable when the model gets smarter.
7. **Context is the scarcest resource** -- Token budget is the core design constraint, not compute.

## 许可证

MIT

## License

MIT
