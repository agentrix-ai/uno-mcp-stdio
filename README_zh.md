# Uno MCP Stdio

[![PyPI version](https://badge.fury.io/py/uno-mcp-stdio.svg)](https://pypi.org/project/uno-mcp-stdio/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Local stdio proxy for Uno MCP Gateway** - 为不支持 OAuth 认证的 MCP 客户端提供本地代理。

## 🎯 解决什么问题

许多 MCP 客户端（如 Manus、Cherry Studio）不支持 OAuth 2.0 认证，无法直接连接需要认证的 MCP 服务器。

`uno-mcp-stdio` 作为本地代理：
1. 使用 stdio 模式与 MCP 客户端通信（所有客户端都支持）
2. 在本地安全存储 OAuth token
3. 代理请求到远程 Uno Gateway，自动附加认证信息

```
┌─────────────────┐     stdio      ┌─────────────────┐     HTTPS      ┌─────────────────┐
│   MCP Client    │ ◄────────────► │  uno-mcp-stdio  │ ◄────────────► │  Uno Gateway    │
│  (不支持OAuth)   │                │   (本地代理)     │   + Bearer     │   (远程服务)     │
└─────────────────┘                └─────────────────┘                └─────────────────┘
```

## 🚀 快速开始

### 安装

```bash
# 使用 uvx 直接运行（推荐）
uvx uno-mcp-stdio

# 或使用 pip 安装
pip install uno-mcp-stdio
uno-mcp-stdio
```

### 首次运行

首次运行时需要 OAuth 认证：

```bash
$ uvx uno-mcp-stdio
🔐 需要登录认证
📋 请在浏览器中打开以下链接完成认证：
   https://mcpmarket.cn/oauth/authorize?...

⏳ 等待认证完成...
✅ 认证成功！Token 已保存
🚀 Uno MCP Stdio 已就绪
```

### 配置 MCP 客户端

在 MCP 客户端中配置 stdio server：

**Manus / Cherry Studio 配置示例：**

```json
{
  "mcpServers": {
    "uno": {
      "command": "uvx",
      "args": ["uno-mcp-stdio"]
    }
  }
}
```

**如果使用 pip 安装：**

```json
{
  "mcpServers": {
    "uno": {
      "command": "uno-mcp-stdio"
    }
  }
}
```

## ⚙️ 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `UNO_GATEWAY_URL` | Uno Gateway 地址 | `https://uno.mcpmarket.cn/mcp` |
| `UNO_CREDENTIALS_PATH` | Token 存储路径 | `~/.uno-mcp/credentials.json` |
| `UNO_DEBUG` | 调试模式 | `false` |

### Token 存储

认证后的 token 存储在 `~/.uno-mcp/credentials.json`：

```json
{
  "access_token": "xxx",
  "refresh_token": "xxx",
  "expires_at": 1736345678,
  "token_type": "Bearer"
}
```

### 清除认证

```bash
# 删除 token 文件重新认证
rm ~/.uno-mcp/credentials.json
```

## 🔐 认证流程

```
1. 启动 uno-mcp-stdio
   │
   ▼
2. 检查 ~/.uno-mcp/credentials.json
   │
   ├─ 有效 token → 直接代理请求
   │
   └─ 无/过期 token → 启动认证流程
      │
      ▼
3. 启动临时 HTTP 服务器 (localhost:随机端口)
   │
   ▼
4. 生成 OAuth URL，显示给用户
   │
   ▼
5. 用户在浏览器完成授权
   │
   ▼
6. MCPMarket 回调到本地服务器
   │
   ▼
7. 交换 token，存储到文件
   │
   ▼
8. 关闭临时服务器，开始代理
```

## 🛠️ 开发

```bash
# 克隆项目
git clone https://github.com/xray918/uno-mcp-stdio.git
cd uno-mcp-stdio

# 安装依赖
uv sync

# 运行
uv run uno-mcp-stdio

# 调试模式
UNO_DEBUG=true uv run uno-mcp-stdio
```

## 📄 License

MIT

## 🌐 Languages

- [English](README.md)
- [中文](README_zh.md) (current)