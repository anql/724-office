"""
MCP 客户端 — 连接外部 MCP 服务器，将其工具注册到 Agent 中

MCP (Model Context Protocol) 是一种标准化协议，用于连接 AI Agent 与外部工具/服务。

自实现 JSON-RPC（无 MCP SDK），零新增依赖。
MCP 协议仅需 3 个方法：initialize, tools/list, tools/call。

核心功能:
1. 连接 MCP 服务器（stdio 或 HTTP 传输）
2. 工具发现（tools/list）
3. 工具调用（tools/call）
4. 自动重连（崩溃后恢复）
5. 热重载（不重启 Agent 更新配置）
6. 工具命名空间（servername__toolname）

使用方法（由 tools.py 调用）:
  mcp_client.init(config)           # 连接所有 config["mcp_servers"]
  mcp_client.get_all_tool_defs()    # 返回 OpenAI function calling 格式
  mcp_client.execute(name, args)    # 调用工具（name = servername__toolname）
  mcp_client.reload(config)         # 热重载配置
  mcp_client.shutdown()             # 关闭所有服务器进程

传输方式:
- stdio: 通过子进程 stdin/stdout 通信（本地服务器）
- HTTP: 通过 HTTP POST 通信（远程服务器）

错误处理:
- 超时检测（30 秒）
- 脏标记（dirty flag）检测不可靠连接
- 自动重连（崩溃后尝试一次）
- 优雅关闭（先尝试正常关闭，失败则 kill）

设计原则:
- 零外部依赖（纯标准库）
- 线程安全（锁保护）
- 流式 JSON-RPC（支持 npm 警告等非 JSON 输出）
- 工具命名空间隔离（防止命名冲突）
"""

import json
import logging
import os
import subprocess
import threading
import urllib.request

log = logging.getLogger("agent")

# ============================================================
#  MCPServer — Single MCP Server Connection
# ============================================================

class MCPServer:
    """Manage one MCP server's lifecycle and JSON-RPC communication"""

    def __init__(self, name, config):
        self.name = name
        self.config = config
        self.transport = config.get("transport", "stdio")
        self._proc = None
        self._lock = threading.Lock()
        self._req_id = 0
        self._tools = []
        self._dirty = False  # Mark unreliable after timeout, force reconnect

    # ------ Lifecycle ------

    def start(self):
        """Start server process (stdio) or verify connectivity (HTTP), then handshake"""
        if self.transport == "stdio":
            self._start_stdio()
        self._initialize()
        self._discover_tools()
        log.info("[mcp] %s: connected, %d tools" % (self.name, len(self._tools)))

    def shutdown(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.stdin.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            log.info("[mcp] %s: shut down" % self.name)

    def _start_stdio(self):
        cmd = self.config.get("command", "")
        args = self.config.get("args", [])
        env = {**os.environ, **self.config.get("env", {})}
        self._proc = subprocess.Popen(
            [cmd] + args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )

    def _reconnect(self):
        """Reconnect once after crash"""
        log.warning("[mcp] %s: reconnecting..." % self.name)
        try:
            self.shutdown()
        except Exception:
            pass
        try:
            if self.transport == "stdio":
                self._start_stdio()
            self._initialize()
            self._discover_tools()
            log.info("[mcp] %s: reconnected, %d tools" % (self.name, len(self._tools)))
            return True
        except Exception as e:
            log.error("[mcp] %s: reconnect failed: %s" % (self.name, e))
            return False

    # ------ JSON-RPC ------

    def _next_id(self):
        self._req_id += 1
        return self._req_id

    def _request(self, method, params=None):
        msg = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            msg["params"] = params
        if self.transport == "stdio":
            return self._stdio_request(msg)
        else:
            return self._http_request(msg)

    def _stdio_request(self, msg):
        """stdio transport: write JSON+newline to stdin, read response from stdout"""
        with self._lock:
            if not self._proc or self._proc.poll() is not None:
                raise ConnectionError("MCP server %s process not running" % self.name)

            line = json.dumps(msg) + "\n"
            self._proc.stdin.write(line.encode())
            self._proc.stdin.flush()

            result_holder = [None]
            error_holder = [None]

            def _read():
                try:
                    while True:
                        raw = self._proc.stdout.readline()
                        if not raw:
                            error_holder[0] = ConnectionError(
                                "MCP server %s: stdout EOF" % self.name)
                            return
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            resp = json.loads(raw)
                            result_holder[0] = resp
                            return
                        except json.JSONDecodeError:
                            continue  # Skip non-JSON lines (npm warnings etc.)
                except Exception as e:
                    error_holder[0] = e

            reader = threading.Thread(target=_read, daemon=True)
            reader.start()
            reader.join(timeout=30)

            if reader.is_alive():
                self._dirty = True
                raise TimeoutError("MCP server %s: request timed out (30s)" % self.name)
            if error_holder[0]:
                raise error_holder[0]

            resp = result_holder[0]
            if resp is None:
                raise ConnectionError("MCP server %s: no response" % self.name)
            if "error" in resp:
                err = resp["error"]
                raise RuntimeError("MCP server %s: %s (code=%s)" % (
                    self.name, err.get("message", ""), err.get("code", "?")))
            return resp.get("result")

    def _http_request(self, msg):
        """HTTP transport: POST JSON-RPC to server URL"""
        url = self.config.get("url", "")
        body = json.dumps(msg).encode()
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                resp = json.loads(r.read())
        except Exception as e:
            raise ConnectionError("MCP server %s HTTP error: %s" % (self.name, e))

        if "error" in resp:
            err = resp["error"]
            raise RuntimeError("MCP server %s: %s (code=%s)" % (
                self.name, err.get("message", ""), err.get("code", "?")))
        return resp.get("result")

    # ------ MCP Protocol ------

    def _initialize(self):
        self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "agent", "version": "2.0"},
        })
        notif = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        if self.transport == "stdio" and self._proc:
            with self._lock:
                self._proc.stdin.write((json.dumps(notif) + "\n").encode())
                self._proc.stdin.flush()

    def _discover_tools(self):
        result = self._request("tools/list")
        self._tools = result.get("tools", []) if result else []

    def call_tool(self, tool_name, arguments):
        if self._dirty:
            log.info("[mcp] %s: dirty flag set, reconnecting before call" % self.name)
            self._dirty = False
            if not self._reconnect():
                return "[error] MCP server %s reconnect failed" % self.name
        try:
            result = self._request("tools/call", {
                "name": tool_name, "arguments": arguments or {}})
        except (ConnectionError, TimeoutError) as e:
            log.warning("[mcp] %s: call failed (%s), trying reconnect" % (self.name, e))
            if self.transport == "stdio" and self._reconnect():
                result = self._request("tools/call", {
                    "name": tool_name, "arguments": arguments or {}})
            else:
                raise

        if not result:
            return ""
        content = result.get("content", [])
        parts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    parts.append(item.get("text", ""))
                else:
                    parts.append(json.dumps(item, ensure_ascii=False))
            else:
                parts.append(str(item))
        return "\n".join(parts) if parts else json.dumps(result, ensure_ascii=False)

    def get_tool_defs(self):
        """Convert MCP tool definitions to OpenAI function calling format

        Namespace: servername__toolname (double underscore)
        """
        defs = []
        for t in self._tools:
            mcp_name = t.get("name", "")
            namespaced = "%s__%s" % (self.name, mcp_name)
            schema = t.get("inputSchema", {"type": "object", "properties": {}})
            defs.append({
                "type": "function",
                "function": {
                    "name": namespaced,
                    "description": t.get("description", "MCP tool: %s" % mcp_name),
                    "parameters": schema,
                },
            })
        return defs


# ============================================================
#  Module-level API
# ============================================================

_servers = {}


def init(config):
    """Connect all configured MCP servers"""
    mcp_config = config.get("mcp_servers", {})
    if not mcp_config:
        return
    for name, srv_config in mcp_config.items():
        try:
            server = MCPServer(name, srv_config)
            server.start()
            _servers[name] = server
        except Exception as e:
            log.error("[mcp] %s: failed to start: %s" % (name, e))


def get_all_tool_defs():
    defs = []
    for server in _servers.values():
        defs.extend(server.get_tool_defs())
    return defs


def execute(name, args):
    parts = name.split("__", 1)
    if len(parts) != 2:
        return "[error] invalid MCP tool name: %s" % name
    server_name, tool_name = parts
    server = _servers.get(server_name)
    if not server:
        return "[error] MCP server not found: %s" % server_name
    try:
        return server.call_tool(tool_name, args)
    except Exception as e:
        log.error("[mcp] %s call error: %s" % (name, e))
        return "[error] MCP tool %s failed: %s" % (name, e)


def reload(config):
    """Hot-reload: close old connections, reconnect with new config"""
    old_names = set(_servers.keys())
    shutdown()
    init(config)
    new_names = set(_servers.keys())
    return new_names - old_names, old_names - new_names, len(_servers)


def shutdown():
    for name, server in _servers.items():
        try:
            server.shutdown()
        except Exception as e:
            log.error("[mcp] %s shutdown error: %s" % (name, e))
    _servers.clear()
    log.info("[mcp] all servers shut down")
