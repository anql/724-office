# 724-Office 7 小时学习计划

> **目标**：从零开始掌握 724-Office AI Agent 系统  
> **时长**：7 小时（分 7 个模块，每模块 1 小时）  
> **前置要求**：Python 基础、了解 LLM 基本概念

---

## 📅 学习安排

| 小时 | 模块 | 主题 | 目标 |
|-----|------|------|------|
| 1 | 模块一 | 系统概览与快速开始 | 理解架构，成功运行 |
| 2 | 模块二 | 工具系统深入 | 掌握 36 个内置工具 |
| 3 | 模块三 | 记忆系统详解 | 理解三层记忆机制 |
| 4 | 模块四 | AI 镜像与助推系统 | 掌握行为分析工具 |
| 5 | 模块五 | 调度与自动化 | 实现定时任务 |
| 6 | 模块六 | 多租户与部署 | Docker 部署实践 |
| 7 | 模块七 | 扩展与实战 | 自定义工具开发 |

---

## 模块一：系统概览与快速开始（第 1 小时）

### 学习目标
- ✅ 理解 724-Office 的核心设计理念
- ✅ 成功运行第一个 AI Agent
- ✅ 熟悉项目结构

### 学习内容（30 分钟）

**1.1 阅读 README（15 分钟）**
```bash
cd 724-office
cat README.md
```

**重点理解：**
- 零框架依赖的设计原则
- 模块化架构的优势
- 7 条设计原则的含义

**1.2 架构图解（15 分钟）**
```
核心组件：
├── xiaowang.py - 入口（HTTP 服务器、消息平台）
├── llm.py - LLM 核心（工具使用循环、预算感知）
├── tools_*.py - 7 个工具模块（36 个工具）
├── memory.py - 三层记忆系统
├── scheduler.py - 定时任务调度
└── router.py - 多租户路由器
```

### 实践操作（30 分钟）

**2.1 快速开始（20 分钟）**
```bash
# 方式 1：直接运行
cp config.example.json config.json
# 编辑 config.json 填入 API Key

pip install croniter lancedb websocket-client pilk numpy httpx beautifulsoup4 pydub jieba fpdf2

mkdir -p workspace/memory workspace/files
python3 xiaowang.py
```

**2.2 测试对话（10 分钟）**
```bash
# 通过消息平台发送第一条消息
"你好，请介绍一下你自己"
```

### 验收标准
- [ ] 能解释 7 条设计原则
- [ ] 成功启动 HTTP 服务器（端口 8080）
- [ ] 收到第一条 AI 回复

### 参考资源
- README.md - 项目介绍
- config.example.json - 配置模板
- xiaowang.py - 入口文件

---

## 模块二：工具系统深入（第 2 小时）

### 学习目标
- ✅ 掌握 36 个内置工具的分类和用途
- ✅ 理解工具调用机制
- ✅ 能够手动触发工具

### 学习内容（30 分钟）

**1.1 工具分类学习（15 分钟）**

| 类别 | 模块 | 工具数 | 核心工具 |
|------|------|--------|---------|
| 核心 | tools_admin | 2 | exec, message |
| 文件 | tools_admin | 4 | read_file, write_file, edit_file, list_files |
| 调度 | tools_messaging | 3 | schedule, list_schedules, remove_schedule |
| 媒体发送 | tools_messaging | 6 | send_image, send_file, send_video, send_link, send_location, send_namecard |
| 视频 | tools_video | 3 | trim_video, add_bgm, generate_video |
| 搜索 | tools_search | 4 | web_search, search_nearby, search_memory, recall |
| 可视化 | tools_page | 1 | render_page |
| AI 镜像 | tools_mirror | 2 | soul_report, future_self |
| 诊断 | tools_admin | 6 | self_check, diagnose, task_history, code_audit, asr_check, daily_digest |
| 记忆 | tools_admin | 2 | compact_memory, compact_guides |
| 插件 | tools_admin | 3 | create_tool, list_custom_tools, remove_tool |
| MCP | tools_admin | 1 | reload_mcp |

**1.2 工具调用机制（15 分钟）**
```python
# 工具使用循环（llm.py）
# 1. 用户消息 -> LLM
# 2. LLM 决定是否调用工具
# 3. 执行工具（最多 20 次迭代）
# 4. 返回结果给用户
```

### 实践操作（30 分钟）

**2.1 测试常用工具（20 分钟）**
```bash
# 测试文件操作
"请读取 README.md 文件"

# 测试网络搜索
"搜索一下最新的 AI 新闻"

# 测试可视化
"生成一个柱状图，显示 2024 年各月销售额：1 月 100 万，2 月 150 万，3 月 200 万"

# 测试调度
"提醒我明天上午 10 点开会"
```

**2.2 查看工具源码（10 分钟）**
```bash
# 查看工具定义
cat tools_admin.py | head -100
cat tools_base.py  # 工具注册和装饰器
```

### 验收标准
- [ ] 能说出 10 个以上工具的名称和用途
- [ ] 成功触发至少 3 个不同类型的工具
- [ ] 理解工具装饰器 @tool 的作用

### 参考资源
- README.md - 工具列表章节
- tools_base.py - 工具注册机制
- tools_*.py - 各工具模块源码

---

## 模块三：记忆系统详解（第 3 小时）

### 学习目标
- ✅ 理解三层记忆架构
- ✅ 掌握记忆压缩和检索机制
- ✅ 能够查看和管理记忆

### 学习内容（30 分钟）

**1.1 三层记忆架构（15 分钟）**

```
第一层：会话记忆（短期）
├── 每个会话最后 40 条消息
├── JSON 文件存储
├── 溢出时触发压缩
└── >100KB 自动归档

第二层：压缩记忆（长期）
├── LLM 提取结构化事实
├── 余弦相似度去重（阈值 0.92）
└── LanceDB 向量存储

第三层：检索记忆（主动回忆）
├── 用户消息 -> 嵌入 -> 向量搜索
├── Top-K 相关记忆注入系统提示
└── 预算感知注入（跟踪 token 使用）
```

**1.2 记忆工作流程（15 分钟）**
```python
# 记忆处理流程（memory.py）
用户消息 -> 嵌入模型 -> 向量搜索 -> Top-K 记忆 -> 注入系统提示 -> LLM 回复
```

### 实践操作（30 分钟）

**2.1 查看记忆文件（15 分钟）**
```bash
# 查看会话记忆
ls -lh workspace/memory/
cat workspace/memory/session_*.json

# 查看压缩记忆
cat workspace/memory/compressed_*.json
```

**2.2 测试记忆检索（15 分钟）**
```bash
# 第一次对话
"我最喜欢的颜色是蓝色，我喜欢吃川菜"

# 间隔一段时间后
"你还记得我喜欢什么颜色吗？"

# 查看记忆是否被检索
# 检查系统提示中是否注入了相关记忆
```

### 验收标准
- [ ] 能解释三层记忆的区别和联系
- [ ] 找到并阅读自己的会话记忆文件
- [ ] 成功测试记忆的长期保留

### 参考资源
- README.md - 记忆系统章节
- memory.py - 三层记忆实现
- workspace/memory/ - 记忆文件目录

---

## 模块四：AI 镜像与助推系统（第 4 小时）

### 学习目标
- ✅ 理解 AI 镜像的行为分析功能
- ✅ 掌握助推系统的工作原理
- ✅ 生成个人行为画像

### 学习内容（30 分钟）

**1.1 AI 镜像功能（15 分钟）**

**soul_report（行为画像）：**
- 分析用户的使用习惯
- 生成 HTML 格式的行为报告
- 包含工具使用频率、对话模式等

**future_self（未来自我对话）：**
- 与"未来的自己"对话
- 获取长期视角的建议
- 行为模式反思

**1.2 助推系统（15 分钟）**

**5 条助推规则（nudge.py）：**
1. 检测 LLM 有工具但不使用
2. 自动注入使用提示
3. 结构性行为纠正
4. 避免重复错误
5. 渐进式引导

### 实践操作（30 分钟）

**2.1 生成行为画像（15 分钟）**
```bash
# 请求生成行为报告
"请生成我的行为画像报告"

# 查看生成的 HTML 文件
open workspace/soul_report_*.html
```

**2.2 体验未来自我对话（15 分钟）**
```bash
# 开启未来自我模式
"我想和未来的自己对话"

# 提问
"一年后我会是什么样子？"
"我应该坚持什么习惯？"
```

### 验收标准
- [ ] 成功生成 soul_report 并查看
- [ ] 体验过 future_self 对话模式
- [ ] 能解释助推系统的 5 条规则

### 参考资源
- README.md - AI Mirror 章节
- tools_mirror.py - AI 镜像实现
- nudge.py - 助推系统实现
- workspace/soul_report_*.html - 生成的报告

---

## 模块五：调度与自动化（第 5 小时）

### 学习目标
- ✅ 掌握 Cron 调度系统
- ✅ 实现一次性任务
- ✅ 理解非活跃守卫机制

### 学习内容（30 分钟）

**1.1 Cron 调度（15 分钟）**

**调度类型：**
- **一次性任务**：指定时间执行一次
- **重复任务**：Cron 表达式，周期性执行

**调度特性：**
- 重启后持久化
- 时区感知
- 非活跃守卫（3 天无活动自动跳过）

**1.2 调度器实现（15 分钟）**
```python
# scheduler.py 核心功能
- 解析 Cron 表达式
- 检查任务到期
- 执行任务（调用工具）
- 记录执行历史
- 非活跃用户跳过
```

### 实践操作（30 分钟）

**2.1 创建定时任务（15 分钟）**
```bash
# 创建一次性任务
"提醒我 10 分钟后喝水"

# 创建重复任务
"每天早上 8 点提醒我看新闻"
"每周五下午 5 点写周报"

# 查看任务列表
"我有哪些定时任务？"
```

**2.2 测试非活跃守卫（15 分钟）**
```bash
# 查看调度器日志
cat workspace/scheduler.log

# 模拟非活跃用户
# （需要等待 3 天，或手动修改配置测试）
```

### 验收标准
- [ ] 成功创建至少 2 个定时任务
- [ ] 理解 Cron 表达式语法
- [ ] 能解释非活跃守卫的作用

### 参考资源
- README.md - Cron Scheduling 章节
- scheduler.py - 调度器实现
- tools_messaging.py - schedule 工具

---

## 模块六：多租户与部署（第 6 小时）

### 学习目标
- ✅ 理解 Docker 多租户架构
- ✅ 成功部署到生产环境
- ✅ 掌握健康检查和协调机制

### 学习内容（30 分钟）

**1.1 多租户路由器（15 分钟）**

**架构特点：**
- 每用户一个 Docker 容器
- 自动配置（auto-provisioning）
- 健康检查
- 容器协调（缺失自动重建）

**1.2 Docker 部署（15 分钟）**
```bash
# 部署步骤
1. 复制 Dockerfile.example -> Dockerfile
2. 复制 docker-compose.example.yml -> docker-compose.yml
3. 编辑 .env 填入凭据
4. docker compose build
5. docker compose up -d
```

### 实践操作（30 分钟）

**2.1 Docker 部署实践（20 分钟）**
```bash
# 准备部署文件
cp Dockerfile.example Dockerfile
cp docker-compose.example.yml docker-compose.yml

# 编辑 .env
vim .env
# 填入 API Key、消息平台凭据等

# 构建和启动
docker compose build
docker compose up -d

# 查看运行状态
docker compose ps
docker compose logs -f
```

**2.2 测试健康检查（10 分钟）**
```bash
# 手动停止一个容器
docker compose stop user1

# 观察路由器是否自动重建
docker compose ps

# 查看路由器日志
docker compose logs router
```

### 验收标准
- [ ] 成功通过 Docker Compose 部署
- [ ] 理解多租户隔离机制
- [ ] 能解释容器协调的工作原理

### 参考资源
- README.md - Multi-Tenant Router 章节
- router.py - 多租户路由器实现
- Dockerfile.example - Docker 配置
- docker-compose.example.yml - Docker Compose 配置

---

## 模块七：扩展与实战（第 7 小时）

### 学习目标
- ✅ 能够创建自定义工具
- ✅ 理解 MCP 插件系统
- ✅ 完成一个实战项目

### 学习内容（30 分钟）

**1.1 运行时工具创建（15 分钟）**

**create_tool 功能：**
- Agent 可以编写新的 Python 工具
- 保存到 tools_custom.py
- 热加载无需重启
- 支持删除自定义工具

**1.2 MCP 插件系统（15 分钟）**

**MCP 连接：**
- 通过 JSON-RPC 连接外部 MCP 服务器
- 支持 stdio 和 HTTP 传输
- 热加载无需重启
- 零新依赖

### 实践操作（30 分钟）

**2.1 创建自定义工具（20 分钟）**
```bash
# 方式 1：通过对话创建
"请创建一个工具，功能是查询天气，调用 OpenWeatherMap API"

# 方式 2：手动创建
cat >> tools_custom.py << 'EOF'
from tools_base import tool

@tool
def get_weather(city: str) -> str:
    """查询城市天气"""
    import requests
    api_key = "YOUR_API_KEY"
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}"
    response = requests.get(url)
    data = response.json()
    return f"{city} 天气：{data['weather'][0]['description']}"
EOF

# 测试新工具
"查询北京天气"
```

**2.2 实战项目（10 分钟）**
```bash
# 综合练习：创建一个自动化工作流
# 1. 每天早上 8 点定时任务
# 2. 搜索最新新闻
# 3. 生成摘要
# 4. 发送到邮箱

"请帮我设置一个自动化工作流：
每天早上 8 点搜索 AI 领域的最新新闻，
生成 300 字摘要，
发送到我的邮箱 xxx@example.com"
```

### 验收标准
- [ ] 成功创建至少 1 个自定义工具
- [ ] 理解 @tool 装饰器的用法
- [ ] 完成一个综合实战项目

### 参考资源
- README.md - Runtime Tool Creation 章节
- tools_admin.py - create_tool 实现
- tools_base.py - @tool 装饰器
- mcp_client.py - MCP 客户端实现

---

## 📚 学习检查清单

### 第 1 小时后
- [ ] 能解释 7 条设计原则
- [ ] 成功启动 HTTP 服务器
- [ ] 收到第一条 AI 回复

### 第 2 小时后
- [ ] 能说出 10 个以上工具的名称和用途
- [ ] 成功触发至少 3 个不同类型的工具
- [ ] 理解工具装饰器 @tool 的作用

### 第 3 小时后
- [ ] 能解释三层记忆的区别和联系
- [ ] 找到并阅读自己的会话记忆文件
- [ ] 成功测试记忆的长期保留

### 第 4 小时后
- [ ] 成功生成 soul_report 并查看
- [ ] 体验过 future_self 对话模式
- [ ] 能解释助推系统的 5 条规则

### 第 5 小时后
- [ ] 成功创建至少 2 个定时任务
- [ ] 理解 Cron 表达式语法
- [ ] 能解释非活跃守卫的作用

### 第 6 小时后
- [ ] 成功通过 Docker Compose 部署
- [ ] 理解多租户隔离机制
- [ ] 能解释容器协调的工作原理

### 第 7 小时后
- [ ] 成功创建至少 1 个自定义工具
- [ ] 理解 @tool 装饰器的用法
- [ ] 完成一个综合实战项目

---

## 🎓 进阶学习路径

完成 7 小时学习后，建议继续：

### 深入理解（+10 小时）
1. 阅读核心模块源码（llm.py, memory.py, scheduler.py）
2. 理解预算感知系统提示的实现
3. 研究向量检索和记忆压缩算法

### 扩展开发（+20 小时）
1. 开发 5 个以上自定义工具
2. 连接外部 MCP 服务器
3. 实现自定义消息平台集成

### 生产部署（+10 小时）
1. 部署到云服务器
2. 配置监控和告警
3. 性能优化和调优

---

## 📞 学习支持

### 常见问题
- **Q: 工具调用失败怎么办？**
  - A: 查看 `workspace/error.log`，检查 API Key 是否正确

- **Q: 记忆检索不准确？**
  - A: 调整 `config.json` 中的相似度阈值（默认 0.92）

- **Q: Docker 容器启动失败？**
  - A: 查看 `docker compose logs`，检查 .env 配置

### 获取帮助
- GitHub Issues: https://github.com/anql/724-office/issues
- 查看文档：README.md
- 查看源码：tools_*.py, llm.py, memory.py

---

## 🏆 结业证书

完成所有 7 个模块并通过验收标准后，恭喜你掌握了 724-Office AI Agent 系统！

**你已掌握：**
- ✅ 零框架依赖的 AI Agent 架构
- ✅ 36 个内置工具的使用
- ✅ 三层记忆系统的设计
- ✅ 行为分析和助推系统
- ✅ 定时任务和自动化
- ✅ Docker 多租户部署
- ✅ 自定义工具开发

**下一步：**
- 贡献代码到 GitHub
- 分享你的使用经验
- 开发更多实用工具

---

**最后更新**：2026-04-16  
**作者**：煎蛋侠 AI  
**许可证**：MIT
