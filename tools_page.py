"""
可视化页面工具 — 生成交互式 HTML 页面，通过链接卡片发送

每个页面都是独立的 HTML 文件（ECharts CDN + 内联数据），24 小时后自动清理。

功能说明:
- 支持 6 种图表模板：折线图 (line)、柱状图 (bar)、饼图 (pie)、雷达图 (radar)、表格 (table)、复合报告 (report)
- 使用 ECharts 库渲染交互式图表
- 页面自动过期清理机制（24 小时）
- 通过 CDN 上传和链接卡片发送给用户

使用场景:
- 数据对比（3+ 选项）
- 趋势展示（5+ 数据点）
- 分布分析（3+ 类别）
- 任何需要可视化的结构化数据

模板类型:
- line: 趋势图，适合时间序列数据
- bar: 对比图，适合类别比较
- pie: 占比图，适合比例分布
- radar: 多维图，适合能力/特征分析
- table: 表格，适合详细数据列表
- report: 复合报告，支持多章节 + 图表混合
"""

import json
import logging
import os
import time
import uuid

import messaging
from tools_base import tool

log = logging.getLogger("agent")

PAGES_DIR = "/pages"
PAGE_EXPIRY = 24 * 3600  # 24h


def _get_base_url():
    """读取页面基础 URL
    
    从 config.json 读取 page_base_url 配置，用于构建可访问的页面链接。
    如果配置不存在，使用默认值。
    
    返回:
        str: 页面基础 URL，如 "http://your-server-ip/p"
    
    配置说明:
        page_base_url: 生成的 HTML 页面的公开访问地址前缀
        需要配置为外部可访问的 URL，用户才能通过链接卡片访问页面
    """
    config_path = os.environ.get("AGENT_CONFIG", "config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        return cfg.get("page_base_url", "http://your-server-ip/p")
    except Exception:
        return "http://your-server-ip/p"


def cleanup_expired_pages():
    """清理过期页面
    
    扫描 PAGES_DIR 目录，删除超过 24 小时的 HTML 页面文件。
    在每次生成新页面时自动调用，保持目录整洁。
    
    返回:
        int: 清理的文件数量
    
    清理逻辑:
        1. 检查 PAGES_DIR 目录是否存在
        2. 遍历所有 .html 文件
        3. 检查文件修改时间，超过 24 小时则删除
        4. 记录清理数量到日志
    
    安全处理:
        - 使用 try-except 防止删除失败导致程序崩溃
        - 仅删除 .html 后缀文件，避免误删
    """
    if not os.path.isdir(PAGES_DIR):
        return 0
    now = time.time()
    removed = 0
    try:
        for f in os.listdir(PAGES_DIR):
            if not f.endswith(".html"):
                continue
            fp = os.path.join(PAGES_DIR, f)
            try:
                if now - os.path.getmtime(fp) > PAGE_EXPIRY:
                    os.remove(fp)
                    removed += 1
            except OSError:
                pass
    except Exception as e:
        log.warning(f"[pages] cleanup error: {e}")
    if removed:
        log.info(f"[pages] cleaned up {removed} expired pages")
    return removed


# -- HTML template framework ------------------------------------------------

_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    background: #f5f3ef;
    color: #374151;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", sans-serif;
    font-size: 15px;
    line-height: 1.7;
    padding: 20px 16px;
    min-height: 100vh;
}
h1 {
    font-size: 20px;
    font-weight: 600;
    color: #0f2b5b;
    margin-bottom: 20px;
    text-align: center;
    letter-spacing: 0.5px;
    padding-bottom: 12px;
    border-bottom: 2px solid #c8952e;
}
h2 {
    font-size: 16px;
    font-weight: 600;
    color: #0f2b5b;
    margin: 24px 0 12px;
    padding-bottom: 8px;
    border-bottom: 2px solid #c8952e;
}
.chart-box {
    width: 100%;
    height: 320px;
    margin: 16px 0;
    background: #ffffff;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
    border-top: 3px solid #c8952e;
}
.loading {
    display: flex;
    align-items: center;
    justify-content: center;
    height: 100%;
    color: #9ca3af;
    font-size: 14px;
}
table {
    width: 100%;
    border-collapse: collapse;
    margin: 16px 0;
    font-size: 14px;
    background: #ffffff;
    border-radius: 12px;
    overflow: hidden;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
}
th {
    background: #0f2b5b;
    color: #ffffff;
    padding: 12px 10px;
    text-align: left;
    font-weight: 500;
    font-size: 13px;
    letter-spacing: 0.3px;
}
td {
    padding: 11px 10px;
    border-bottom: 1px solid #f0f0f0;
    color: #374151;
}
tr:last-child td { border-bottom: none; }
tr:hover td { background: #f8fafc; }
.section {
    margin: 16px 0;
    padding: 16px;
    background: #ffffff;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.06), 0 1px 2px rgba(0,0,0,0.04);
    border-left: 3px solid #c8952e;
}
.section p {
    margin: 8px 0;
    color: #4b5563;
}
.footer {
    text-align: center;
    color: #9ca3af;
    font-size: 12px;
    margin-top: 32px;
    padding-top: 16px;
    border-top: 1px solid #c8952e;
    letter-spacing: 0.3px;
}
"""

_COLORS = "['#1a56db','#c8952e','#6b9bd2','#e8c87a','#94a3b8','#d4a853','#3b82f6']"

_ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"


def _html_wrap(title, body_content, has_chart=True):
    """生成完整的 HTML 页面包装器
    
    将标题、内容和样式组合成完整的 HTML 页面。
    包含响应式设计、ECharts CDN 引用、SEO 控制等。
    
    参数:
        title: 页面标题（会进行 HTML 转义防止 XSS）
        body_content: 页面主体内容（HTML 片段）
        has_chart: 是否需要引入 ECharts 库（默认 True）
    
    返回:
        str: 完整的 HTML 文档字符串
    
    页面特性:
        - 响应式设计，适配移动端
        - 中文语言标记 (zh-CN)
        - 禁止搜索引擎索引 (noindex, nofollow)
        - 24 小时有效期提示
        - 统一的视觉风格（通过 _CSS 定义）
    
    安全处理:
        - 标题进行 HTML 实体转义，防止 XSS 攻击
        - 转义字符：& < > "
    """
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    echarts_tag = f'<script src="{_ECHARTS_CDN}"></script>' if has_chart else ""
    # Escape title for HTML (转义标题防止 XSS)
    safe_title = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    return (
        '<!DOCTYPE html>\n<html lang="zh-CN">\n<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no">\n'
        f'<meta property="og:title" content="{safe_title}">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        f'<title>{safe_title}</title>\n'
        f'{echarts_tag}\n'
        f'<style>{_CSS}</style>\n'
        '</head>\n<body>\n'
        f'<h1>{safe_title}</h1>\n'
        f'{body_content}\n'
        f'<div class="footer">AI Agent &middot; Valid for 24h</div>\n'
        '</body>\n</html>'
    )


def _chart_init_js(chart_id, data, setup_code):
    """生成 ECharts 图表初始化 JavaScript 代码块
    
    创建等待 CDN 加载完成后初始化图表的 JS 代码。
    使用轮询机制确保 ECharts 库完全加载后再执行。
    
    参数:
        chart_id: 图表容器的 DOM 元素 ID
        data: 图表数据对象（会序列化为 JSON）
        setup_code: 图表配置代码（setOption 调用等）
    
    返回:
        str: 完整的 <script> 标签内容
    
    工作原理:
        1. 等待 DOMContentLoaded 事件
        2. 每 100ms 检查 echarts 对象是否可用
        3. 库加载完成后初始化图表实例
        4. 绑定窗口 resize 事件实现自适应
        5. 停止轮询避免资源浪费
    
    设计考虑:
        - 轮询机制：CDN 加载时间不确定，需要等待
        - 100ms 间隔：平衡响应速度和资源消耗
        - resize 监听：确保移动端缩放时图表正常显示
    """
    data_json = json.dumps(data, ensure_ascii=False)
    return (
        "<script>\n"
        "document.addEventListener('DOMContentLoaded', function() {\n"
        f"  var el = document.getElementById('{chart_id}');\n"
        "  var intv = setInterval(function() {\n"
        "    if (typeof echarts !== 'undefined') {\n"
        "      clearInterval(intv);\n"
        f"      var d = {data_json};\n"
        f"      var chart = echarts.init(el);\n"
        f"      {setup_code}\n"
        "      window.addEventListener('resize', function() { chart.resize(); });\n"
        "    }\n"
        "  }, 100);\n"
        "});\n"
        "</script>\n"
    )


# -- 6 templates -------------------------------------------------------------

def _render_line(title, data):
    """渲染折线图（趋势图）
    
    适合展示时间序列数据、趋势变化、多系列对比。
    
    参数:
        title: 图表标题
        data: 数据对象，格式：
            {
                "x": ["标签 1", "标签 2", ...],  # X 轴分类
                "series": [
                    {"name": "系列 1", "values": [值 1, 值 2, ...]},
                    {"name": "系列 2", "values": [值 1, 值 2, ...]}
                ]
            }
    
    返回:
        str: 完整的 HTML 页面字符串
    
    图表特性:
        - 平滑曲线 (smooth: true)
        - 多系列支持，自动图例
        - 透明背景，适配页面风格
        - 轴标签颜色统一
        - 网格边距优化
    
    使用场景:
        - 每日消息量趋势
        - 工具使用频率变化
        - 多指标时间序列对比
    """
    setup = (
        "chart.setOption({\n"
        "  backgroundColor: 'transparent',\n"
        "  tooltip: { trigger: 'axis' },\n"
        "  legend: { data: d.series.map(function(s){ return s.name; }), textStyle: { color: '#374151' } },\n"
        "  grid: { left: 40, right: 20, top: 40, bottom: 30 },\n"
        "  xAxis: { type: 'category', data: d.x, axisLabel: { color: '#6b7280' } },\n"
        "  yAxis: { type: 'value', axisLabel: { color: '#6b7280' }, splitLine: { lineStyle: { color: '#e5e7eb' } } },\n"
        "  series: d.series.map(function(s) {\n"
        "    return { name: s.name, type: 'line', data: s.values, smooth: true, symbolSize: 6 };\n"
        "  }),\n"
        f"  color: {_COLORS}\n"
        "});\n"
    )
    body = (
        '<div id="chart" class="chart-box"><div class="loading">Loading...</div></div>\n'
        + _chart_init_js("chart", data, setup)
    )
    return _html_wrap(title, body)


def _render_bar(title, data):
    """渲染柱状图（对比图）
    
    适合展示类别对比、排名、数量统计。
    
    参数:
        title: 图表标题
        data: 数据对象，格式同折线图：
            {
                "x": ["分类 1", "分类 2", ...],
                "series": [
                    {"name": "系列 1", "values": [值 1, 值 2, ...]}
                ]
            }
    
    返回:
        str: 完整的 HTML 页面字符串
    
    图表特性:
        - 自动旋转 X 轴标签（超过 6 个分类时旋转 30 度）
        - 最大柱宽限制（40px），避免过宽
        - 多系列支持
        - 透明背景
    
    使用场景:
        - 工具使用频率排名
        - 不同类别的数量对比
        - 多用户数据对比
    """
    setup = (
        "chart.setOption({\n"
        "  backgroundColor: 'transparent',\n"
        "  tooltip: { trigger: 'axis' },\n"
        "  legend: { data: d.series.map(function(s){ return s.name; }), textStyle: { color: '#374151' } },\n"
        "  grid: { left: 40, right: 20, top: 40, bottom: 30 },\n"
        "  xAxis: { type: 'category', data: d.x, axisLabel: { color: '#888', rotate: d.x.length > 6 ? 30 : 0 } },\n"
        "  yAxis: { type: 'value', axisLabel: { color: '#6b7280' }, splitLine: { lineStyle: { color: '#e5e7eb' } } },\n"
        "  series: d.series.map(function(s) {\n"
        "    return { name: s.name, type: 'bar', data: s.values, barMaxWidth: 40 };\n"
        "  }),\n"
        f"  color: {_COLORS}\n"
        "});\n"
    )
    body = (
        '<div id="chart" class="chart-box"><div class="loading">Loading...</div></div>\n'
        + _chart_init_js("chart", data, setup)
    )
    return _html_wrap(title, body)


def _render_pie(title, data):
    """渲染饼图（占比图）
    
    适合展示比例分布、构成分析、份额统计。
    
    参数:
        title: 图表标题
        data: 数据对象，格式：
            {
                "items": [
                    {"name": "类别 1", "value": 数值 1},
                    {"name": "类别 2", "value": 数值 2}
                ]
            }
    
    返回:
        str: 完整的 HTML 页面字符串
    
    图表特性:
        - 环形图设计（内径 35%，外径 65%）
        - 悬停高亮效果（阴影）
        - 百分比显示（tooltip 格式：名称：数值 (百分比%)）
        - 统一字体颜色
    
    使用场景:
        - 话题分布比例
        - 时间分配构成
        - 资源占用份额
    """
    setup = (
        "chart.setOption({\n"
        "  backgroundColor: 'transparent',\n"
        "  tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },\n"
        "  series: [{\n"
        "    type: 'pie', radius: ['35%', '65%'],\n"
        "    label: { color: '#374151', fontSize: 13 },\n"
        "    data: d.items,\n"
        "    emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(26,86,219,0.3)' } }\n"
        "  }],\n"
        f"  color: {_COLORS}\n"
        "});\n"
    )
    body = (
        '<div id="chart" class="chart-box"><div class="loading">Loading...</div></div>\n'
        + _chart_init_js("chart", data, setup)
    )
    return _html_wrap(title, body)


def _render_radar(title, data):
    """渲染雷达图（多维分析图）
    
    适合展示能力分布、多维度对比、特征分析。
    
    参数:
        title: 图表标题
        data: 数据对象，格式：
            {
                "indicators": [
                    {"name": "维度 1", "max": 100},  # 或简化为字符串 "维度 1"
                    "维度 2",  # 简写形式，max 默认 100
                    ...
                ],
                "series": [
                    {"name": "系列 1", "values": [值 1, 值 2, ...]}
                ]
            }
    
    返回:
        str: 完整的 HTML 页面字符串
    
    图表特性:
        - 支持字符串简写（自动设置 max=100）
        - 交替背景色区域（便于读数）
        - 面积填充（透明度 15%）
        - 多系列对比
    
    使用场景:
        - 用户行为维度分析（如 AI Mirror 中的行为画像）
        - 能力/技能评估
        - 多维度产品对比
    """
    setup = (
        "var indicators = d.indicators.map(function(ind) {\n"
        "  if (typeof ind === 'string') return { name: ind, max: 100 };\n"
        "  return { name: ind.name, max: ind.max || 100 };\n"
        "});\n"
        "chart.setOption({\n"
        "  backgroundColor: 'transparent',\n"
        "  tooltip: {},\n"
        "  legend: { data: d.series.map(function(s){ return s.name; }), textStyle: { color: '#374151' } },\n"
        "  radar: {\n"
        "    indicator: indicators,\n"
        "    axisName: { color: '#374151' },\n"
        "    splitArea: { areaStyle: { color: ['#f8fafc', '#ffffff'] } },\n"
        "    splitLine: { lineStyle: { color: '#e5e7eb' } }\n"
        "  },\n"
        "  series: [{\n"
        "    type: 'radar',\n"
        "    data: d.series.map(function(s) {\n"
        "      return { name: s.name, value: s.values, areaStyle: { opacity: 0.15 } };\n"
        "    })\n"
        "  }],\n"
        f"  color: {_COLORS}\n"
        "});\n"
    )
    body = (
        '<div id="chart" class="chart-box"><div class="loading">Loading...</div></div>\n'
        + _chart_init_js("chart", data, setup)
    )
    return _html_wrap(title, body)


def _render_table(title, data):
    """渲染表格（数据列表）
    
    适合展示详细数据、对比清单、结构化信息。
    
    参数:
        title: 页面标题
        data: 数据对象，格式：
            {
                "columns": ["列名 1", "列名 2", ...],
                "rows": [
                    ["值 1", "值 2", ...],  # 第一行
                    ["值 1", "值 2", ...],  # 第二行
                    ...
                ]
            }
    
    返回:
        str: 完整的 HTML 页面字符串（不含图表）
    
    表格特性:
        - 响应式设计，横向滚动适配移动端
        - 固定表头样式（深蓝背景）
        - 行悬停高亮效果
        - 自动边框和阴影
    
    使用场景:
        - 任务清单
        - 数据对比表
        - 详细报告数据
    """
    cols = data.get("columns", [])
    rows = data.get("rows", [])
    header = "".join(f"<th>{c}</th>" for c in cols)
    body_rows = ""
    for row in rows:
        cells = "".join(f"<td>{cell}</td>" for cell in row)
        body_rows += f"<tr>{cells}</tr>\n"

    body = (
        '<div style="overflow-x:auto;">\n'
        f'<table>\n<thead><tr>{header}</tr></thead>\n'
        f'<tbody>{body_rows}</tbody>\n</table>\n</div>'
    )
    return _html_wrap(title, body, has_chart=False)


def _render_report(title, data):
    """渲染复合报告（多章节 + 图表混合）
    
    最强大的模板，支持多个章节，每章可包含文字内容和嵌入式图表。
    适合生成完整的分析报告、数据总结等。
    
    参数:
        title: 报告标题
        data: 数据对象，格式：
            {
                "sections": [
                    {
                        "heading": "章节标题",
                        "content": "章节文字内容（支持多行）",
                        "chart": {  # 可选
                            "type": "line"|"bar"|"pie",
                            "data": {...}  # 对应图表的数据格式
                        }
                    },
                    ...
                ]
            }
    
    返回:
        str: 完整的 HTML 页面字符串
    
    报告结构:
        - 每个章节独立卡片样式
        - 章节标题统一风格
        - 文字内容自动分段
        - 图表嵌入章节内部
        - 自动检测是否需要 ECharts
    
    使用场景:
        - AI Mirror 行为分析报告
        - 项目进度总结
        - 数据分析报告
        - 多维度对比分析
    """
    sections_html = ""
    chart_count = 0

    for i, sec in enumerate(data.get("sections", [])):
        heading = sec.get("heading", "")
        content = sec.get("content", "")
        chart = sec.get("chart")

        sections_html += f'<div class="section">\n<h2>{heading}</h2>\n'
        if content:
            for p in content.split("\n"):
                p = p.strip()
                if p:
                    sections_html += f"<p>{p}</p>\n"

        if chart and isinstance(chart, dict):
            chart_id = f"chart_{i}"
            chart_type = chart.get("type", "bar")
            chart_data = chart.get("data", {})

            sections_html += f'<div id="{chart_id}" class="chart-box"><div class="loading">Loading...</div></div>\n'

            if chart_type in ("line", "bar"):
                setup = (
                    "chart.setOption({\n"
                    "  backgroundColor: 'transparent',\n"
                    "  tooltip: { trigger: 'axis' },\n"
                    "  legend: { data: d.series.map(function(s){ return s.name; }), textStyle: { color: '#374151' } },\n"
                    "  grid: { left: 40, right: 20, top: 40, bottom: 30 },\n"
                    "  xAxis: { type: 'category', data: d.x, axisLabel: { color: '#6b7280' } },\n"
                    "  yAxis: { type: 'value', axisLabel: { color: '#6b7280' }, splitLine: { lineStyle: { color: '#e5e7eb' } } },\n"
                    f"  series: d.series.map(function(s) {{ return {{ name: s.name, type: '{chart_type}', data: s.values, smooth: true }}; }}),\n"
                    f"  color: {_COLORS}\n"
                    "});\n"
                )
            elif chart_type == "pie":
                setup = (
                    "chart.setOption({\n"
                    "  backgroundColor: 'transparent',\n"
                    "  tooltip: { trigger: 'item' },\n"
                    "  series: [{ type: 'pie', radius: ['35%','65%'], label: { color: '#374151' }, data: d.items }],\n"
                    f"  color: {_COLORS}\n"
                    "});\n"
                )
            else:
                setup = ""

            if setup:
                sections_html += _chart_init_js(chart_id, chart_data, setup)
                chart_count += 1

        sections_html += "</div>\n"

    return _html_wrap(title, sections_html, has_chart=(chart_count > 0))


# -- Template routing --------------------------------------------------------

_TEMPLATES = {
    "line": _render_line,
    "bar": _render_bar,
    "pie": _render_pie,
    "radar": _render_radar,
    "table": _render_table,
    "report": _render_report,
}


# -- Tool definition ---------------------------------------------------------

@tool("render_page",
      "生成交互式可视化页面并通过链接卡片发送给用户。\n\n"
      "重要规则：当回复包含以下情况时，必须调用此工具生成可视化，而不是纯文本列表：\n"
      "- 对比数据：3+ 选项的对比\n"
      "- 趋势数据：5+ 数据点的时间序列\n"
      "- 分布数据：3+ 类别的占比分析\n\n"
      "模板类型:\n"
      "- line: 折线图，适合趋势分析\n"
      "- bar: 柱状图，适合类别对比\n"
      "- pie: 饼图，适合占比分布\n"
      "- radar: 雷达图，适合多维分析\n"
      "- table: 表格，适合详细数据\n"
      "- report: 复合报告，支持多章节 + 图表混合",
      {"title": {"type": "string", "description": "页面标题（同时用作链接卡片标题）"},
       "template": {"type": "string", "enum": ["line", "bar", "pie", "radar", "table", "report"],
                     "description": "模板类型"},
       "data": {"type": "object", "description": "数据对象，格式因模板而异：\n"
                "- line/bar: {x:[...], series:[{name,values}]}\n"
                "- pie: {items:[{name,value}]}\n"
                "- radar: {indicators:[...], series:[{name,values}]}\n"
                "- table: {columns:[...], rows:[[...]]}\n"
                "- report: {sections:[{heading, content?, chart?}]}"},
       "desc": {"type": "string", "description": "链接卡片描述文字（可选，省略时自动生成）"}},
      ["title", "template", "data"])  # 必填参数
def tool_render_page(args, ctx):
    """渲染页面工具主函数
    
    核心流程:
    1. 清理过期页面（自动维护）
    2. 验证模板类型
    3. 生成 HTML 内容
    4. 写入文件
    5. 构建访问 URL
    6. 发送链接卡片给用户
    
    参数:
        args: 工具参数，包含 title/template/data/desc
        ctx: 上下文，包含 owner_id 等信息
    
    返回:
        str: 成功时返回页面 URL，失败时返回错误信息
    
    错误处理:
        - 模板不存在：返回可用模板列表
        - 渲染失败：记录日志并返回错误
        - 写入失败：记录日志并返回错误
        - 发送失败：返回 URL 并提示发送失败
    
    安全特性:
        - 使用 UUID 生成随机文件名，防止猜测
        - 自动创建目录，避免路径错误
        - 24 小时过期机制，避免磁盘占用
    """
    title = args["title"]
    template = args["template"]
    data = args["data"]
    desc = args.get("desc", "")
    owner_id = ctx.get("owner_id")

    # Piggyback cleanup of expired pages (顺便清理过期页面)
    cleanup_expired_pages()

    # Validate template (验证模板类型)
    render_fn = _TEMPLATES.get(template)
    if not render_fn:
        return f"[error] Unknown template: {template}, available: {', '.join(_TEMPLATES.keys())}"

    # Generate HTML (生成 HTML 内容)
    try:
        html = render_fn(title, data)
    except Exception as e:
        log.error(f"[pages] render error: {e}", exc_info=True)
        return f"[error] Page render failed: {e}"

    # Write file (写入文件)
    page_id = uuid.uuid4().hex[:8]  # 8 位随机 ID
    filename = f"{page_id}.html"
    filepath = os.path.join(PAGES_DIR, filename)

    if not os.path.isdir(PAGES_DIR):
        os.makedirs(PAGES_DIR, exist_ok=True)

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html)
    except Exception as e:
        log.error(f"[pages] write error: {e}")
        return f"[error] File write failed: {e}"

    # Build URL (构建访问 URL)
    base_url = _get_base_url()
    page_url = f"{base_url}/{filename}"

    # Send link card (发送链接卡片)
    if not desc:
        desc = f"Click to view: {title}"

    if owner_id:
        try:
            result = messaging.send_link(owner_id, title, desc, page_url)
            if result.get("code") != 0:
                log.warning(f"[pages] send_link failed: {result}")
                return f"Page generated: {page_url}\n(Link card send failed: {result.get('msg', '?')})"
        except Exception as e:
            log.warning(f"[pages] send_link error: {e}")
            return f"Page generated: {page_url}\n(Link card send failed: {e})"

    log.info(f"[pages] rendered {template} page: {page_url}")
    return f"Visualization page generated and sent: {page_url}"
