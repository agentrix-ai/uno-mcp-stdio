"""
MCP Stdio Server 实现

使用 MCP Python SDK 实现 stdio 传输的 MCP server。
代理请求到远程 Uno Gateway。
"""

import sys
import json
import asyncio
from typing import Optional

from mcp.server import Server, NotificationOptions, ServerRequestContext
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
)

from . import __version__

from .config import settings
from .auth import token_manager, CallbackServer
from .gateway import gateway_proxy, AuthenticationRequired, GatewayError


class UnoStdioServer:
    """Uno MCP Stdio Server"""
    
    def __init__(self, link_mode: bool = False):
        """
        初始化 Uno MCP Stdio Server
        
        Args:
            link_mode: 是否使用链接模式（用于 Manus 等远程服务器场景）
        """
        self._authenticated = False
        self._tools_cache: Optional[list] = None
        self._link_mode = link_mode
        # mcp 2.x：处理器在构造时注册，不再有 list_tools/call_tool 装饰器。
        self.server = Server(
            "uno-mcp-stdio",
            version=__version__,
            on_list_tools=self._on_list_tools,
            on_call_tool=self._on_call_tool,
        )
    
    def _get_notification_options(self) -> NotificationOptions:
        """获取通知选项，声明支持 tools_changed 通知"""
        return NotificationOptions(
            prompts_changed=False,
            resources_changed=False,
            tools_changed=True  # 声明支持工具列表变更通知
        )
    
    def _log(self, message: str):
        """输出日志到 stderr（避免干扰 stdio 通信）"""
        print(f"[UnoStdio] {message}", file=sys.stderr, flush=True)
    
    def _auth_input_schema(self) -> dict:
        """uno_auth 的入参。Link 模式多一个 code。"""
        properties: dict = {
            "action": {
                "type": "string",
                "enum": ["login", "logout", "status"],
                "description": "操作类型：login(登录/重新登录)、logout(退出登录)、status(查看状态)。默认为 login",
            }
        }
        if self._link_mode:
            properties["code"] = {
                "type": "string",
                "description": "授权码。在链接模式下，用户访问认证链接完成授权后，将页面显示的授权码填入此参数",
            }
        return {"type": "object", "properties": properties, "required": []}

    @staticmethod
    def _tool_schema(raw: object) -> dict:
        """协议要求 input_schema 根上有 type=object。"""
        if not isinstance(raw, dict):
            return {"type": "object"}
        if "type" not in raw:
            return {"type": "object", **raw}
        return raw

    async def _notify_tools_changed(self, session) -> None:
        """认证状态变化后通知客户端刷新工具列表。"""
        if session is None:
            return
        try:
            await session.send_tool_list_changed()
            self._log("已发送 tools/list_changed 通知")
        except Exception as e:
            self._log(f"发送通知失败（客户端可能不支持）: {e}")

    async def _on_list_tools(
        self,
        ctx: ServerRequestContext,
        params: PaginatedRequestParams | None,
    ) -> ListToolsResult:
        """处理 tools/list。返回完整 ListToolsResult，不再依赖 SDK 自动包装。"""
        del ctx, params
        self._log("收到 tools/list 请求")

        is_authenticated = self._authenticated or bool(await token_manager.get_valid_token())

        try:
            response = await gateway_proxy.list_tools()

            if "result" in response and "tools" in response["result"]:
                tools_data = response["result"]["tools"]
                self._tools_cache = tools_data
                tools = []
                has_pending = token_manager.has_pending_session()

                if is_authenticated:
                    auth_description = "🔐 认证管理工具。当前状态：✅ 已登录。支持的操作：login(重新登录)、logout(退出登录)、status(查看状态)"
                elif has_pending:
                    auth_description = "🔐 认证管理工具。当前状态：⏳ 等待输入授权码。请将认证页面显示的授权码通过 code 参数传入完成认证"
                else:
                    auth_description = "🔐 认证管理工具。当前状态：❌ 未登录。请调用此工具完成认证后才能使用其他工具。支持的操作：login(登录)、status(查看状态)"

                tools.append(Tool(
                    name="uno_auth",
                    description=auth_description,
                    input_schema=self._auth_input_schema(),
                ))

                for t in tools_data:
                    tools.append(Tool(
                        name=t["name"],
                        description=t.get("description", ""),
                        input_schema=self._tool_schema(
                            t.get("inputSchema", t.get("input_schema"))
                        ),
                    ))

                self._log(f"返回 {len(tools)} 个工具 (已认证: {is_authenticated})")
                return ListToolsResult(tools=tools)

            self._log(f"Gateway 返回格式异常: {response}")
            return ListToolsResult(tools=[])

        except GatewayError as e:
            self._log(f"获取工具列表失败: {e}")
            return ListToolsResult(tools=[
                Tool(
                    name="uno_auth",
                    description="🔐 认证管理工具。请调用此工具获取认证链接。支持的操作：login(登录)、logout(退出)、status(查看状态)",
                    input_schema=self._auth_input_schema(),
                )
            ])

    async def _on_call_tool(
        self,
        ctx: ServerRequestContext,
        params: CallToolRequestParams,
    ) -> CallToolResult:
        """处理 tools/call。异常转成 is_error 结果，避免变成 JSON-RPC 协议错误。"""
        try:
            return await self._dispatch_call(ctx, params)
        except Exception as e:
            self._log(f"tools/call 未处理异常: {e}")
            return CallToolResult(
                content=[TextContent(
                    type="text",
                    text=json.dumps({
                        "error": "internal_error",
                        "message": str(e),
                    }, ensure_ascii=False),
                )],
                is_error=True,
            )

    async def _dispatch_call(
        self,
        ctx: ServerRequestContext,
        params: CallToolRequestParams,
    ) -> CallToolResult:
        name = params.name
        arguments = params.arguments or {}
        self._log(f"收到 tools/call 请求: {name}")

        if name == "uno_auth":
            action = arguments.get("action", "login")
            code = arguments.get("code")
            contents = await self._handle_auth_request(
                action=action, code=code, session=ctx.session
            )
            return CallToolResult(content=contents, is_error=False)

        try:
            await self._ensure_authenticated()
        except AuthenticationRequired:
            return self._text_result({
                "error": "authentication_required",
                "message": "需要认证，请先调用 uno_auth 工具",
            })

        try:
            response = await gateway_proxy.call_tool(name, arguments, request_id=1)

            if "result" in response:
                result = response["result"]
                if "content" in result:
                    contents = []
                    for item in result["content"]:
                        if item.get("type") == "text":
                            contents.append(TextContent(
                                type="text",
                                text=item.get("text", ""),
                            ))
                    return CallToolResult(content=contents, is_error=False)
                return self._text_result(result, indent=2)
            if "error" in response:
                return self._text_result({
                    "error": response["error"].get("code"),
                    "message": response["error"].get("message"),
                })
            return self._text_result(response)

        except AuthenticationRequired:
            token_manager.clear_credentials()
            self._authenticated = False
            return self._text_result({
                "error": "authentication_expired",
                "message": "认证已过期，请重新调用 uno_auth 工具",
            })
        except GatewayError as e:
            return self._text_result({
                "error": "gateway_error",
                "message": str(e),
            })

    @staticmethod
    def _text_result(payload: object, indent: int | None = None) -> CallToolResult:
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps(payload, ensure_ascii=False, indent=indent),
            )],
            is_error=False,
        )
    
    async def _ensure_authenticated(self):
        """确保已认证"""
        if self._authenticated:
            return
        
        # 检查是否有有效 token
        token = await token_manager.get_valid_token()
        if token:
            self._authenticated = True
            return
        
        raise AuthenticationRequired("需要认证")
    
    async def _handle_auth_request(
        self,
        action: str = "login",
        code: str = None,
        session=None,
    ) -> list[TextContent]:
        """
        处理认证请求
        
        Args:
            action: 操作类型
                - login: 登录或重新登录
                - logout: 退出登录
                - status: 查看认证状态
            code: 授权码（Link 模式下使用）
        """
        self._log(f"处理认证请求: action={action}, code={'***' if code else 'None'}, link_mode={self._link_mode}")
        
        # 处理状态查询
        if action == "status":
            token = await token_manager.get_valid_token()
            has_pending = token_manager.has_pending_session()
            
            if token:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "authenticated",
                        "message": "✅ 当前已登录",
                        "hint": "可使用 action='logout' 退出登录，或 action='login' 重新登录"
                    }, ensure_ascii=False)
                )]
            elif has_pending:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "pending",
                        "message": "⏳ 等待输入授权码",
                        "hint": "请访问认证链接完成授权，然后将页面显示的授权码通过 code 参数传入"
                    }, ensure_ascii=False)
                )]
            else:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "not_authenticated",
                        "message": "❌ 当前未登录",
                        "hint": "可使用 action='login' 进行登录"
                    }, ensure_ascii=False)
                )]
        
        # 处理退出登录
        if action == "logout":
            token = await token_manager.get_valid_token()
            if token:
                token_manager.clear_credentials()
                token_manager.clear_pending_session()  # 同时清除 pending session
                self._authenticated = False
                self._log("用户已退出登录")
                
                await self._notify_tools_changed(session)

                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "logged_out",
                        "message": "✅ 已成功退出登录",
                        "hint": "如需重新登录，请调用此工具并设置 action='login'"
                    }, ensure_ascii=False)
                )]
            else:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "not_authenticated",
                        "message": "当前未登录，无需退出"
                    }, ensure_ascii=False)
                )]
        
        # 处理登录请求 (action == "login" 或其他)
        
        # Link 模式：如果提供了 code，尝试完成认证
        if self._link_mode and code:
            return await self._handle_link_mode_complete(code, session=session)
        
        # Link 模式：没有 code，生成认证链接
        if self._link_mode:
            return await self._handle_link_mode_start()
        
        # 本地模式：原有的浏览器认证流程
        return await self._handle_local_mode_auth(session=session)
    
    async def _handle_link_mode_start(self) -> list[TextContent]:
        """
        Link 模式：生成认证链接
        
        返回认证 URL，用户需要在自己的设备上访问完成认证，
        然后将页面显示的授权码传回。
        """
        self._log("Link 模式：生成认证链接")
        
        # 如果已有 token，先清除（实现重新登录）
        existing_token = await token_manager.get_valid_token()
        if existing_token:
            self._log("检测到已有 token，清除后重新认证")
            token_manager.clear_credentials()
            self._authenticated = False
        
        # 清除可能存在的旧 pending session
        token_manager.clear_pending_session()
        
        # 创建新的认证会话
        session_info = await token_manager.create_link_mode_session()
        
        if not session_info:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "failed",
                    "error": "session_creation_failed",
                    "message": "❌ 创建认证会话失败，请检查网络连接"
                }, ensure_ascii=False)
            )]
        
        auth_url = session_info["auth_url"]
        self._log(f"认证链接已生成: {auth_url[:50]}...")
        
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "link_generated",
                "message": "🔗 请复制以下链接到浏览器完成认证",
                "auth_url": auth_url,
                "instructions": [
                    "1. 复制上面的 auth_url 链接",
                    "2. 在浏览器中打开该链接",
                    "3. 在 MCPMarket 完成登录/授权",
                    "4. 授权完成后，页面会显示一个授权码",
                    "5. 将授权码复制，再次调用此工具并设置 code 参数",
                    "   例如：uno_auth(code='你的授权码')"
                ],
                "next_step": "获取授权码后，调用 uno_auth(code='授权码') 完成认证"
            }, ensure_ascii=False, indent=2)
        )]
    
    async def _handle_link_mode_complete(self, code: str, session=None) -> list[TextContent]:
        """
        Link 模式：使用授权码完成认证
        
        Args:
            code: 用户从认证页面获取的授权码
        """
        self._log(f"Link 模式：使用授权码完成认证")
        
        # 检查是否有 pending session
        if not token_manager.has_pending_session():
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "failed",
                    "error": "no_pending_session",
                    "message": "❌ 没有待完成的认证会话，请先调用 uno_auth() 获取认证链接"
                }, ensure_ascii=False)
            )]
        
        # 使用授权码完成认证
        credentials = await token_manager.complete_link_mode_auth(code)
        
        if credentials:
            self._authenticated = True
            self._log("Link 模式认证成功！")
            
            await self._notify_tools_changed(session)

            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": "✅ 认证成功！现在可以使用 Uno 的工具了。"
                }, ensure_ascii=False)
            )]
        else:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "failed",
                    "error": "token_exchange_failed",
                    "message": "❌ 授权码验证失败，请检查授权码是否正确，或重新获取认证链接"
                }, ensure_ascii=False)
            )]
    
    async def _handle_local_mode_auth(self, session=None) -> list[TextContent]:
        """
        本地模式：使用浏览器完成认证（原有流程）
        """
        self._log("本地模式：启动浏览器认证流程")
        
        # 如果已有 token，先清除（实现重新登录）
        existing_token = await token_manager.get_valid_token()
        if existing_token:
            self._log("检测到已有 token，清除后重新认证")
            token_manager.clear_credentials()
            self._authenticated = False
        
        # 生成 PKCE 参数
        code_verifier, code_challenge = token_manager.generate_pkce()
        state = token_manager.generate_state()
        
        # 启动回调服务器
        callback_server = CallbackServer()
        port = callback_server.start(expected_state=state)
        redirect_uri = callback_server.get_redirect_uri()
        
        # 动态注册客户端（或使用已有的注册信息）
        self._log("检查客户端注册...")
        client_id = await token_manager.ensure_client_registered(redirect_uri)
        if not client_id:
            callback_server.stop()
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "failed",
                    "error": "client_registration_failed",
                    "message": "客户端注册失败，请检查网络连接"
                }, ensure_ascii=False)
            )]
        
        self._log(f"使用 client_id: {client_id}")
        
        # 生成认证 URL（异步方法，从 well-known 获取端点）
        auth_url = await token_manager.build_auth_url(redirect_uri, state, code_challenge, client_id)
        
        if not auth_url:
            callback_server.stop()
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "failed",
                    "error": "oauth_metadata_failed",
                    "message": "无法获取 OAuth 元数据，请检查 Gateway 连接"
                }, ensure_ascii=False)
            )]
        
        # 尝试自动打开浏览器
        browser_opened = token_manager.open_auth_url(auth_url)
        
        self._log(f"认证 URL: {auth_url}")
        self._log("等待用户完成认证...")
        
        # 等待回调
        callback_data = callback_server.wait_for_callback()
        callback_server.stop()
        
        if not callback_data:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "timeout",
                    "message": "认证超时，请重试",
                    "auth_url": auth_url
                }, ensure_ascii=False)
            )]
        
        if not callback_data.get("success"):
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "failed",
                    "error": callback_data.get("error"),
                    "message": callback_data.get("error_description", "认证失败")
                }, ensure_ascii=False)
            )]
        
        # 交换 token
        auth_code = callback_data.get("code")
        credentials = await token_manager.exchange_code_for_token(
            code=auth_code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            client_id=client_id
        )
        
        if credentials:
            self._authenticated = True
            self._log("认证成功！")
            
            await self._notify_tools_changed(session)

            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "success",
                    "message": "✅ 认证成功！现在可以使用 Uno 的工具了。"
                }, ensure_ascii=False)
            )]
        else:
            return [TextContent(
                type="text",
                text=json.dumps({
                    "status": "failed",
                    "message": "Token 交换失败，请重试"
                }, ensure_ascii=False)
            )]
    
    async def run(self):
        """运行 stdio server"""
        self._log("Uno MCP Stdio Server 启动中...")
        
        # 检查是否已有有效 token
        token = await token_manager.get_valid_token()
        if token:
            self._authenticated = True
            self._log("已有有效 token，无需认证")
        else:
            self._log("需要认证，等待客户端调用 uno_auth")
        
        # 运行 stdio server
        async with stdio_server() as (read_stream, write_stream):
            self._log("Stdio server 已就绪")
            # 创建初始化选项，声明支持 tools_changed 通知
            init_options = self.server.create_initialization_options(
                notification_options=self._get_notification_options()
            )
            await self.server.run(
                read_stream,
                write_stream,
                init_options
            )
        
        # 清理
        await gateway_proxy.close()
        self._log("Uno MCP Stdio Server 已关闭")


async def run_server(link_mode: bool = False):
    """
    运行服务器入口
    
    Args:
        link_mode: 是否使用链接模式（用于 Manus 等远程服务器场景）
    """
    server = UnoStdioServer(link_mode=link_mode)
    await server.run()

