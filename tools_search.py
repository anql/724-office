"""
Search Tools — web_search + memory/recall
搜索工具 — 网络搜索 + 记忆/回忆
"""

import json
import os
import subprocess
import urllib.request
import urllib.parse

from tools_base import tool, log

_search_keys = {}  # set by init_search_config() (搜索 API 密钥)

def init_search_config(config):
    """初始化搜索配置
    Initialize search configuration
    """
    global _search_keys
    _search_keys = {
        "tavily": config.get("tavily_api_key", ""),
        "bocha": config.get("bocha_api_key", ""),
        "github": config.get("github_token", ""),
        "huggingface": config.get("huggingface_token", ""),
    }

def _tavily_search(query, count=5):
    """Tavily API search — high quality for English content, returns original excerpts and links
    Tavily API 搜索 — 英文内容质量高，返回原始摘要和链接
    
    Tavily 是一个 AI 驱动的搜索引擎，特点：
    - 返回 AI 生成的答案摘要
    - 提供相关性评分
    - 包含原始内容片段
    
    参数:
        query: 搜索关键词
        count: 返回结果数量，默认 5 条
    
    返回:
        格式化的搜索结果字符串
    """
    api_key = _search_keys.get("tavily", "")
    if not api_key:
        return "[error] Tavily API key not configured"

    # 构建 API 请求
    url = "https://api.tavily.com/search"
    body = json.dumps({
        "api_key": api_key,
        "query": query,
        "search_depth": "advanced",  # 高级搜索模式
        "include_answer": True,      # 包含 AI 生成的答案
        "max_results": count,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return f"[error] Tavily search failed: {e}"

    parts = []
    # 添加 AI 生成的答案摘要
    answer = data.get("answer")
    if answer:
        parts.append("== AI Summary ==\n" + answer)

    # 处理搜索结果
    results = data.get("results", [])
    if not results:
        return answer or "No relevant results found."

    items = []
    for i, item in enumerate(results[:count], 1):
        title = item.get("title", "")
        content = item.get("content", "")[:300]  # 限制内容长度
        link = item.get("url", "")
        score = item.get("score", 0)  # 相关性评分
        items.append(f"{i}. {title} (relevance: {score:.2f})\n   {content}\n   Link: {link}")
    parts.append("\n\n".join(items))
    return "\n\n".join(parts)


def _bocha_search(query, count=5):
    """Bocha API general web search
    博查 API 通用网页搜索
    
    博查是一个中文搜索引擎 API，特点：
    - 适合中文内容搜索
    - 返回网页摘要
    - 支持自定义结果数量
    
    参数:
        query: 搜索关键词
        count: 返回结果数量，默认 5 条
    
    返回:
        格式化的搜索结果字符串
    """
    api_key = _search_keys.get("bocha", "")
    if not api_key:
        return "[error] Bocha API key not configured"

    # 构建 API 请求
    url = "https://api.bochaai.com/v1/web-search"
    body = json.dumps({"query": query, "count": count, "summary": True}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",  # Bearer Token 认证
    })
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        return f"[error] Bocha search failed: {e}"

    results = []
    # 解析返回的网页结果
    web_pages = data.get("data", {}).get("webPages", {}).get("value", [])
    if not web_pages:
        return "No relevant results found."
    for i, item in enumerate(web_pages[:count], 1):
        title = item.get("name", "")
        snippet = item.get("summary", item.get("snippet", ""))
        link = item.get("url", "")
        results.append(f"{i}. {title}\n   {snippet}\n   Link: {link}")
    return "\n\n".join(results)


def _github_search(query, count=5):
    """GitHub public API search: search repos first, then code, merge and dedupe
    GitHub 公开 API 搜索：先搜索仓库，再搜索代码，合并并去重
    
    GitHub API 搜索策略：
    1. 优先搜索仓库（repository），按 star 数排序
    2. 如果仓库结果少于 2 个，补充搜索代码（code）
    3. 去重处理，避免重复显示同一仓库
    
    参数:
        query: 搜索关键词
        count: 返回结果数量，默认 5 条
    
    返回:
        格式化的 GitHub 搜索结果字符串
    """
    headers = {
        "Accept": "application/vnd.github.v3+json",  # GitHub API v3 版本
        "User-Agent": "ai-agent",  # 用户代理标识
    }
    results = []

    # 1. Search repositories (name + description + README)
    # 搜索仓库（包含名称、描述、README）
    encoded = urllib.parse.quote(query)  # URL 编码查询词
    url = "https://api.github.com/search/repositories?q=%s&sort=stars&per_page=%d" % (encoded, count)
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        for item in data.get("items", [])[:count]:
            name = item.get("full_name", "")  # 完整仓库名 user/repo
            desc = (item.get("description") or "")[:150]  # 描述限制 150 字
            stars = item.get("stargazers_count", 0)  # Star 数量
            link = item.get("html_url", "")  # GitHub 链接
            lang = item.get("language", "")  # 主要编程语言
            updated = (item.get("updated_at") or "")[:10]  # 最后更新日期
            line = "%s ⭐%d" % (name, stars)
            if lang:
                line += " [%s]" % lang
            if updated:
                line += " (updated %s)" % updated
            line += "\n   %s\n   Link: %s" % (desc, link)
            results.append(line)
    except Exception as e:
        results.append("[repo search error: %s]" % e)

    # 2. If repo results < 2, supplement with code search
    # 如果仓库结果少于 2 个，补充搜索代码
    if len(results) < 2:
        try:
            code_url = "https://api.github.com/search/code?q=%s&per_page=%d" % (encoded, count)
            req = urllib.request.Request(code_url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                code_data = json.loads(resp.read())
            seen_repos = set()  # 已见过的仓库集合（去重）
            for item in code_data.get("items", []):
                repo = item.get("repository", {})
                repo_name = repo.get("full_name", "")
                if repo_name and repo_name not in seen_repos:
                    seen_repos.add(repo_name)
                    desc = (repo.get("description") or "")[:150]
                    link = repo.get("html_url", "")
                    results.append("%s (from code search)\n   %s\n   Link: %s" % (repo_name, desc, link))
                    if len(seen_repos) >= count:
                        break
        except Exception:
            pass  # Code search is supplementary, don't report errors (代码搜索是补充，不报错)

    if not results:
        return "No relevant projects found on GitHub."
    return "\n\n".join("%d. %s" % (i, r) for i, r in enumerate(results, 1))


def _huggingface_search(query, count=5):
    """HuggingFace API search for models
    HuggingFace API 搜索模型
    
    HuggingFace 是 AI 模型托管平台，特点：
    - 搜索机器学习/深度学习模型
    - 按下载量排序（热门优先）
    - 显示模型类型（pipeline_tag）
    
    参数:
        query: 搜索关键词（模型名称或类型）
        count: 返回结果数量，默认 5 条
    
    返回:
        格式化的 HuggingFace 搜索结果字符串
    
    降级策略：
        如果 API 搜索失败，回退到 Bocha 网页搜索
    """
    encoded = urllib.parse.quote(query)
    # API 参数说明：
    # sort=downloads: 按下载量排序
    # direction=-1: 降序（下载量多的在前）
    # limit=count: 限制结果数量
    url = f"https://huggingface.co/api/models?search={encoded}&sort=downloads&direction=-1&limit={count}"
    req = urllib.request.Request(url, headers={"User-Agent": "ai-agent"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except Exception as e:
        # Fallback to web search (降级到网页搜索)
        return _bocha_search(f"huggingface {query}", count)

    if not data:
        return "No relevant models found on HuggingFace."
    results = []
    for i, item in enumerate(data[:count], 1):
        model_id = item.get("modelId", item.get("id", ""))  # 模型 ID
        downloads = item.get("downloads", 0)  # 下载次数
        likes = item.get("likes", 0)  # 点赞数
        pipeline = item.get("pipeline_tag", "")  # 模型类型（如 text-generation, image-classification）
        results.append(f"{i}. {model_id} (downloads: {downloads}, likes: {likes})" +
                       (f" [{pipeline}]" if pipeline else "") +
                       f"\n   Link: https://huggingface.co/{model_id}")
    return "\n\n".join(results)


@tool("web_search", "Search the web. Supports multiple search sources. "
      "source=auto uses dual-engine (Tavily + Bocha) by default, specific keywords route to specialized sources. "
      "source=tavily for Tavily (English-optimized, returns excerpts + AI summary). "
      "source=github for GitHub. source=web for Bocha. source=all for all sources.",
      {"query": {"type": "string", "description": "Search keywords"},
       "source": {"type": "string", "description": "Search source: auto/web/tavily/github/huggingface/all",
                  "enum": ["auto", "web", "tavily", "github", "huggingface", "all"]},
       "count": {"type": "integer", "description": "Number of results (default 5)"}},
      ["query"])
def tool_web_search(args, ctx):
    """网络搜索工具
    Web search tool
    
    支持多种搜索源：
    - auto: 自动选择（根据关键词智能路由）
    - web: 博查搜索（中文优化）
    - tavily: Tavily 搜索（英文优化，带 AI 摘要）
    - github: GitHub 代码/仓库搜索
    - huggingface: HuggingFace 模型搜索
    - all: 全部搜索源
    
    参数:
        query: 搜索关键词
        source: 搜索源选择
        count: 返回结果数量
    
    返回:
        格式化的搜索结果
    """
    query = args["query"]
    source = args.get("source", "auto")
    count = args.get("count", 5)

    # 自动模式：根据关键词智能选择搜索源
    if source == "auto":
        ql = query.lower()
        # HuggingFace 相关关键词 → 使用 huggingface 搜索
        if any(kw in ql for kw in ["huggingface", "hugging face", "hf model"]):
            source = "huggingface"
        # GitHub 相关关键词 → 使用 github 搜索
        elif any(kw in ql for kw in ["github.com", "github repo"]):
            source = "github"
        # 验证类查询：包含项目/工具名 + 验证意图 → 使用多引擎搜索
        elif any(kw in ql for kw in ["does it exist", "is it real", "verify", "exist",
                                      "skill", "plugin", "mcp", "tool",
                                      "open source", "repo"]):
            source = "all"  # 多引擎搜索，全面验证
        else:
            source = "web+tavily"  # 默认双引擎搜索

    # 根据选择的搜索源执行搜索
    if source == "github":
        return _github_search(query, count)
    elif source == "tavily":
        return _tavily_search(query, count)
    elif source == "web+tavily":
        # Dual engine: Tavily + Bocha, return both results
        # 双引擎搜索：Tavily + 博查，返回两个结果
        parts = []
        tav = _tavily_search(query, count)
        if tav and "[error]" not in tav:
            parts.append("== Tavily ==\n" + tav)
        bocha = _bocha_search(query, count)
        if bocha and "[error]" not in bocha:
            parts.append("== Bocha ==\n" + bocha)
        return "\n\n".join(parts) if parts else "No search results."
    elif source == "huggingface":
        return _huggingface_search(query, count)
    elif source == "all":
        # 全部搜索源：每个源分配一半数量（最少 3 条）
        parts = []
        tav = _tavily_search(query, max(count // 2, 3))
        if tav and "[error]" not in tav:
            parts.append("== Tavily ==\n" + tav)
        gh = _github_search(query, max(count // 2, 3))
        if gh and "[error]" not in gh:
            parts.append("== GitHub ==\n" + gh)
        bocha = _bocha_search(query, max(count // 2, 3))
        if bocha and "[error]" not in bocha:
            parts.append("== Bocha ==\n" + bocha)
        return "\n\n".join(parts) if parts else "No results from any search source."
    else:
        # 默认使用博查搜索
        return _bocha_search(query, count)

# --- Memory search tools - 记忆搜索工具 ---

@tool("search_memory", "Search memory files. Keyword search in workspace/memory/ directory, "
      "returns matching content snippets and filenames. More precise and efficient than reading all of MEMORY.md.",
      {"query": {"type": "string", "description": "Search keywords (space-separated for multiple)"},
       "scope": {"type": "string", "description": "Scope: all (default, all memory files), long (MEMORY.md only), daily (daily logs only)"}},
      ["query"])
def tool_search_memory(args, ctx):
    """搜索记忆文件
    Search memory files
    
    使用 grep 在 memory 目录中进行关键词搜索，特点：
    - 比读取整个 MEMORY.md 更精确高效
    - 支持范围筛选（全部/长期记忆/日记）
    - 返回匹配的行号和文件名
    
    参数:
        query: 搜索关键词（空格分隔多个关键词）
        scope: 搜索范围
            - all: 全部记忆文件（默认）
            - long: 仅 MEMORY.md（长期记忆）
            - daily: 仅日记文件（2*.md）
    
    返回:
        匹配结果（最多显示 30 条）
    """
    query = args["query"]
    scope = args.get("scope", "all")
    memory_dir = os.path.join(ctx["workspace"], "memory")

    if not os.path.isdir(memory_dir):
        return "Memory directory does not exist."

    # 构建 grep 命令参数
    # -r: 递归搜索
    # -i: 忽略大小写
    # -n: 显示行号
    # --include=*.md: 只搜索.md 文件
    grep_args = ["grep", "-r", "-i", "-n", "--include=*.md"]
    if scope == "long":
        # 只搜索长期记忆文件
        target = os.path.join(memory_dir, "MEMORY.md")
        if not os.path.exists(target):
            return "MEMORY.md does not exist."
        grep_args = ["grep", "-i", "-n", "--", query, target]
    elif scope == "daily":
        # 只搜索日记文件（2*.md 格式如 2024-01-01.md）
        grep_args.extend(["--include=2*.md", "--", query, memory_dir])
    else:
        # 搜索所有记忆文件
        grep_args.extend(["--", query, memory_dir])

    try:
        result = subprocess.run(grep_args, capture_output=True, text=True, timeout=10)
        output = result.stdout.strip()
        if not output:
            return "No memories found containing '%s'." % query

        lines = output.split("\n")
        # 限制返回结果数量，防止过多
        if len(lines) > 30:
            return "\n".join(lines[:30]) + ("\n... %d matches total, showing first 30" % len(lines))
        return "%d matches:\n%s" % (len(lines), "\n".join(lines))
    except Exception as e:
        return "[error] search failed: %s" % e


# --- Semantic memory retrieval - 语义记忆检索 ---

@tool('recall', 'Semantic search through long-term memory. Use when the user asks about previous '
      'conversations or needs to recall historical information. Smarter than search_memory '
      '(vector semantic matching vs keyword matching).',
      {'query': {'type': 'string', 'description': 'Search keywords or question'}},
      ['query'])
def tool_recall(args, ctx):
    """语义记忆检索
    Semantic memory retrieval
    
    使用向量语义搜索长期记忆，特点：
    - 比 search_memory 更智能（语义匹配 vs 关键词匹配）
    - 适合用户询问历史对话或需要回忆信息时使用
    - 使用 LanceDB 向量数据库进行相似度搜索
    
    参数:
        query: 搜索关键词或问题
    
    返回:
        相关的记忆内容
    
    与 search_memory 的区别:
        - search_memory: 关键词精确匹配，适合查找特定内容
        - recall: 语义模糊匹配，适合回忆相关概念
    """
    import memory as mem_mod
    # 从记忆系统检索相关内容，top_k=10 返回最相关的 10 条
    result = mem_mod.retrieve(args['query'], ctx['session_key'], top_k=10)
    return result or 'No relevant memories found.'
