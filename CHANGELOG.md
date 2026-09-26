# Changelog

## 0.2.1

- 适配 MCP Python SDK 2.x：低层 `Server` 改为构造参数 `on_list_tools` / `on_call_tool`，返回 `ListToolsResult` / `CallToolResult`，工具列表变更通知改走 `ctx.session.send_tool_list_changed()`。
- 依赖改为 `mcp>=2.2,<3`，避免再解析到已删除 `Server.list_tools` 的版本，也避免下一个大版本无上限装崩。
- `__version__` 与包版本对齐为 0.2.1。

## 0.2.0

- 增加 Link 模式认证（`--link`）：远程客户端通过授权链接与授权码完成登录，不依赖本机浏览器回调。
