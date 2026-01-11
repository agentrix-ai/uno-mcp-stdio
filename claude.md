# Uno MCP Stdio - Claude 项目指南

## 项目概述

`uno-mcp-stdio` 是 Uno MCP Gateway 的本地 stdio 代理客户端。它解决了不支持 OAuth 认证的 MCP 客户端（如 Manus、Cherry Studio）无法连接需要认证的 MCP 服务器的问题。

### 核心价值

- **兼容所有 MCP 客户端**：使用所有客户端都支持的 stdio 传输
- **本地认证管理**：在本地安全存储 OAuth token
- **透明代理**：对客户端透明，就像直接连接 gateway

### 架构关系

```
┌─────────────────┐     stdio      ┌─────────────────┐     HTTPS      ┌─────────────────┐
│   MCP Client    │ ◄────────────► │  uno-mcp-stdio  │ ◄────────────► │  Uno Gateway    │
│  (不支持OAuth)   │                │   (本地代理)     │   + Bearer     │   (远程服务)     │
└─────────────────┘                └─────────────────┘                └─────────────────┘
                                           │
                                   ~/.uno-mcp/credentials.json
```

## 技术栈

| 组件 | 技术选型 |
|------|----------|
| MCP SDK | mcp (官方 Python SDK) |
| HTTP 客户端 | httpx |
| 配置管理 | pydantic-settings |
| 包管理 | uv |
| Python 版本 | 3.11+ |

## 目录结构

```
uno-mcp-stdio/
├── src/
│   └── uno_mcp_stdio/
│       ├── __init__.py           # 包初始化
│       ├── main.py               # CLI 入口
│       ├── config.py             # 配置管理
│       ├── stdio_server.py       # MCP stdio server 核心实现
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── token_manager.py  # Token 存储、刷新、PKCE
│       │   └── callback_server.py # OAuth 回调 HTTP 服务器
│       └── gateway/
│           ├── __init__.py
│           └── proxy.py          # 代理请求到远程 gateway
├── pyproject.toml
├── README.md
└── claude.md
```

## 核心模块说明

### 1. stdio_server.py - MCP Server 实现

使用 MCP Python SDK 实现 stdio 传输的 server：

```python
class UnoStdioServer:
    # 处理 tools/list - 代理到 gateway 获取工具列表
    # 处理 tools/call - 代理到 gateway 执行工具
    # 处理 uno_auth_required - 启动 OAuth 认证流程
```

关键点：
- 如果未认证，`tools/list` 返回一个 `uno_auth_required` 工具
- 用户调用该工具触发 OAuth 认证流程
- 认证成功后，重新调用 `tools/list` 获取真实工具列表

### 2. token_manager.py - Token 管理

负责：
- **OAuth 元数据获取**：从 gateway 的 `/.well-known/oauth-authorization-server` 获取端点信息
- **动态客户端注册**：RFC 7591，自动注册到 MCPMarket，存储到 `~/.uno-mcp/client.json`
- Token 存储（`~/.uno-mcp/credentials.json`）
- Token 刷新（使用 refresh_token）
- PKCE 生成（code_verifier, code_challenge）
- OAuth URL 构建（使用动态获取的端点）

### 3. callback_server.py - OAuth 回调

临时 HTTP 服务器：
- 动态分配端口（避免冲突）
- 等待 OAuth 回调
- 验证 state 参数
- 返回成功/失败页面

### 4. proxy.py - Gateway 代理

代理 MCP 请求到远程 gateway：
- 附加 Authorization header
- 处理 401 自动刷新/清除 token
- 转换 JSON-RPC 响应

## 认证流程详解

```
1. Client 调用 tools/list
   │
   ▼
2. stdio_server 检查 token
   │
   ├─ 有效 → 代理到 gateway 获取工具列表
   │
   └─ 无/过期 → 返回 uno_auth_required 工具
      │
      ▼
3. Client 调用 uno_auth_required
   │
   ▼
4. 启动临时 HTTP 服务器 (localhost:随机端口)
   │
   ▼
5. 生成 OAuth URL (PKCE)，尝试打开浏览器
   │
   ▼
6. 用户在浏览器授权
   │
   ▼
7. MCPMarket 回调到 localhost:{port}/callback
   │
   ▼
8. 用 code 交换 token，存储到文件
   │
   ▼
9. 返回认证成功，Client 重新调用 tools/list
```

## 配置说明

环境变量（前缀 `UNO_`）：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `UNO_GATEWAY_URL` | Gateway MCP 端点 | `https://uno.mcpmarket.cn/mcp` |
| `UNO_MCPMARKET_URL` | MCPMarket 地址 | `https://mcpmarket.cn` |
| `UNO_OAUTH_CLIENT_ID` | OAuth 客户端 ID | `uno-stdio` |
| `UNO_CREDENTIALS_PATH` | Token 存储路径 | `~/.uno-mcp/credentials.json` |
| `UNO_DEBUG` | 调试模式 | `false` |
| `UNO_CALLBACK_TIMEOUT` | OAuth 回调超时 | `300` (秒) |

## 开发规范

### 日志输出

所有日志必须输出到 stderr，避免干扰 stdio 通信：

```python
def _log(self, message: str):
    import sys
    print(f"[Module] {message}", file=sys.stderr)
```

### 错误处理

定义专用异常：

```python
class AuthenticationRequired(Exception):
    """需要认证"""
    pass

class GatewayError(Exception):
    """Gateway 错误"""
    pass
```

### 异步设计

所有 I/O 操作使用 async/await：

```python
async def get_valid_token(self) -> Optional[str]:
    ...

async def send_request(self, method: str, ...) -> Dict:
    ...
```

## 常见开发任务

### 添加新的 MCP 方法支持

1. 在 `stdio_server.py` 的 `_setup_handlers` 中添加处理器
2. 在 `proxy.py` 中添加对应的代理方法

### 修改 Token 存储位置

修改 `config.py` 中的 `credentials_path` 默认值，或设置环境变量 `UNO_CREDENTIALS_PATH`

### 测试认证流程

```bash
# 清除已有 token
rm ~/.uno-mcp/credentials.json

# 调试模式运行
UNO_DEBUG=true uv run uno-mcp-stdio
```

### 本地开发

```bash
cd uno-mcp-stdio
uv sync
uv run uno-mcp-stdio
```

## 与 uno-mcp 的关系

| 项目 | 角色 | 运行位置 |
|------|------|----------|
| `uno-mcp` | HTTP MCP Gateway | 远程服务器 |
| `uno-mcp-stdio` | Stdio 代理客户端 | 用户本地 |

`uno-mcp-stdio` 是 `uno-mcp` 的客户端，通过 HTTP 调用远程 gateway。

## 注意事项

1. **不要在 stdout 输出**：会破坏 stdio 通信
2. **Token 安全**：credentials.json 包含敏感信息，不要提交到 git
3. **回调端口**：使用动态端口，避免冲突
4. **超时设置**：OAuth 回调默认等待 5 分钟

