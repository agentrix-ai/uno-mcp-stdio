# Changelog

## 0.2.1

- 将 `mcp` 依赖限制为 `>=1.0,<2`，修复 `uvx uno-mcp-stdio` 在 mcp 2.x 下启动即崩溃（`'Server' object has no attribute 'list_tools'`）。
- `__version__` 与包版本对齐为 0.2.1。

## 0.2.0

- 增加 Link 模式认证（`--link`）：远程客户端通过授权链接与授权码完成登录，不依赖本机浏览器回调。
