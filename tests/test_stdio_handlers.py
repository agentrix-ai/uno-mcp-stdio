"""mcp 2.x 低层 handler 的返回形状。不访问网络，也不写真实凭据。"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

from mcp.types import CallToolRequestParams

from uno_mcp_stdio import stdio_server as mod
from uno_mcp_stdio.gateway import GatewayError


def _ctx():
    session = MagicMock()
    session.send_tool_list_changed = AsyncMock()
    return MagicMock(session=session)


def test_server_registers_constructor_handlers_not_decorators():
    server = mod.UnoStdioServer()
    assert server.server.get_request_handler("tools/list") is not None
    assert server.server.get_request_handler("tools/call") is not None
    assert not hasattr(server.server, "list_tools")
    assert not hasattr(server.server, "call_tool")


def test_list_tools_prefixes_auth_tool(monkeypatch):
    gateway_tools = [
        {
            "name": f"remote_{i}",
            "description": "read",
            "inputSchema": {"properties": {}},
        }
        for i in range(7)
    ]

    async def scenario():
        monkeypatch.setattr(mod.token_manager, "get_valid_token", AsyncMock(return_value=None))
        monkeypatch.setattr(mod.token_manager, "has_pending_session", lambda: False)
        monkeypatch.setattr(
            mod.gateway_proxy,
            "list_tools",
            AsyncMock(return_value={"result": {"tools": gateway_tools}}),
        )
        server = mod.UnoStdioServer()
        result = await server._on_list_tools(None, None)
        names = [tool.name for tool in result.tools]
        assert names[0] == "uno_auth"
        assert names[1:] == [f"remote_{i}" for i in range(7)]
        assert len(names) == 8
        assert result.tools[1].input_schema["type"] == "object"
        assert "code" not in result.tools[0].input_schema["properties"]

    asyncio.run(scenario())


def test_list_tools_gateway_error_returns_only_auth(monkeypatch):
    async def scenario():
        monkeypatch.setattr(mod.token_manager, "get_valid_token", AsyncMock(return_value=None))
        monkeypatch.setattr(
            mod.gateway_proxy,
            "list_tools",
            AsyncMock(side_effect=GatewayError("down")),
        )
        server = mod.UnoStdioServer(link_mode=True)
        result = await server._on_list_tools(None, None)
        assert [tool.name for tool in result.tools] == ["uno_auth"]
        assert "code" in result.tools[0].input_schema["properties"]

    asyncio.run(scenario())


def test_uno_auth_status_needs_no_credentials(monkeypatch):
    async def scenario():
        monkeypatch.setattr(mod.token_manager, "get_valid_token", AsyncMock(return_value=None))
        monkeypatch.setattr(mod.token_manager, "has_pending_session", lambda: False)
        server = mod.UnoStdioServer()
        result = await server._on_call_tool(
            _ctx(),
            CallToolRequestParams(name="uno_auth", arguments={"action": "status"}),
        )
        body = json.loads(result.content[0].text)
        assert result.is_error is False
        assert body["status"] == "not_authenticated"

    asyncio.run(scenario())


def test_link_mode_login_returns_auth_url_without_notifying(monkeypatch):
    async def scenario():
        monkeypatch.setattr(mod.token_manager, "get_valid_token", AsyncMock(return_value=None))
        monkeypatch.setattr(mod.token_manager, "clear_pending_session", lambda: None)
        monkeypatch.setattr(
            mod.token_manager,
            "create_link_mode_session",
            AsyncMock(return_value={"auth_url": "https://example.test/oauth/start", "state": "state-id"}),
        )
        server = mod.UnoStdioServer(link_mode=True)
        ctx = _ctx()
        result = await server._on_call_tool(
            ctx,
            CallToolRequestParams(name="uno_auth", arguments={"action": "login"}),
        )
        body = json.loads(result.content[0].text)
        assert body["status"] == "link_generated"
        assert body["auth_url"] == "https://example.test/oauth/start"
        ctx.session.send_tool_list_changed.assert_not_awaited()

    asyncio.run(scenario())


def test_call_tool_exception_becomes_is_error(monkeypatch):
    async def scenario():
        monkeypatch.setattr(
            mod.token_manager,
            "get_valid_token",
            AsyncMock(side_effect=RuntimeError("boom")),
        )
        server = mod.UnoStdioServer()
        result = await server._on_call_tool(
            _ctx(),
            CallToolRequestParams(name="uno_auth", arguments={"action": "status"}),
        )
        body = json.loads(result.content[0].text)
        assert result.is_error is True
        assert body["error"] == "internal_error"

    asyncio.run(scenario())
