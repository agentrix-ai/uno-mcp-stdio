# Uno MCP Stdio

[![PyPI version](https://badge.fury.io/py/uno-mcp-stdio.svg)](https://pypi.org/project/uno-mcp-stdio/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Local stdio proxy for Uno MCP Gateway** - Provides local proxy for MCP clients that don't support OAuth authentication.

## 🎯 Problem Solved

Many MCP clients (such as Manus, Cherry Studio) don't support OAuth 2.0 authentication and cannot directly connect to MCP servers that require authentication.

`uno-mcp-stdio` acts as a local proxy:
1. Communicates with MCP clients using stdio mode (supported by all clients)
2. Securely stores OAuth tokens locally
3. Proxies requests to remote Uno Gateway, automatically attaching authentication information

```
┌─────────────────┐     stdio      ┌─────────────────┐     HTTPS      ┌─────────────────┐
│   MCP Client    │ ◄────────────► │  uno-mcp-stdio  │ ◄────────────► │  Uno Gateway    │
│ (No OAuth)      │                │  (Local Proxy)  │   + Bearer     │  (Remote)       │
└─────────────────┘                └─────────────────┘                └─────────────────┘
```

## 🚀 Quick Start

### Installation

```bash
# Run directly with uvx (recommended)
uvx uno-mcp-stdio

# Or install with pip
pip install uno-mcp-stdio
uno-mcp-stdio
```

### First Run

OAuth authentication is required on first run:

```bash
$ uvx uno-mcp-stdio
🔐 Authentication required
📋 Please open the following link in your browser to complete authentication:
   https://mcpmarket.cn/oauth/authorize?...

⏳ Waiting for authentication...
✅ Authentication successful! Token saved
🚀 Uno MCP Stdio is ready
```

### Configure MCP Client

Configure stdio server in your MCP client:

**Manus / Cherry Studio Configuration Example:**

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

**If installed with pip:**

```json
{
  "mcpServers": {
    "uno": {
      "command": "uno-mcp-stdio"
    }
  }
}
```

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `UNO_GATEWAY_URL` | Uno Gateway URL | `https://uno.mcpmarket.cn/mcp` |
| `UNO_CREDENTIALS_PATH` | Token storage path | `~/.uno-mcp/credentials.json` |
| `UNO_DEBUG` | Debug mode | `false` |

### Token Storage

Authenticated tokens are stored in `~/.uno-mcp/credentials.json`:

```json
{
  "access_token": "xxx",
  "refresh_token": "xxx",
  "expires_at": 1736345678,
  "token_type": "Bearer"
}
```

### Clear Authentication

```bash
# Delete token file to re-authenticate
rm ~/.uno-mcp/credentials.json
```

## 🔐 Authentication Flow

```
1. Start uno-mcp-stdio
   │
   ▼
2. Check ~/.uno-mcp/credentials.json
   │
   ├─ Valid token → Proxy requests directly
   │
   └─ No/expired token → Start authentication flow
      │
      ▼
3. Start temporary HTTP server (localhost:random port)
   │
   ▼
4. Generate OAuth URL, display to user
   │
   ▼
5. User completes authorization in browser
   │
   ▼
6. MCPMarket callback to local server
   │
   ▼
7. Exchange token, save to file
   │
   ▼
8. Close temporary server, start proxying
```

## 🛠️ Development

```bash
# Clone repository
git clone https://github.com/agentrix-ai/uno-mcp-stdio.git
cd uno-mcp-stdio

# Install dependencies
uv sync

# Run
uv run uno-mcp-stdio

# Debug mode
UNO_DEBUG=true uv run uno-mcp-stdio
```

## 📄 License

MIT

## 🌐 Languages

- [English](README.md) (current)
- [中文](README_zh.md)
