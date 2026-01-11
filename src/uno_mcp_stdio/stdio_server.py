"""
MCP Stdio Server 实现

使用 MCP Python SDK 实现 stdio 传输的 MCP server。
代理请求到远程 Uno Gateway。
"""

import sys
import json
import asyncio
from typing import Optional

from mcp.server import Server, NotificationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    Tool,
    TextContent,
    CallToolResult,
    ListToolsResult,
)

from .config import settings
from .auth import token_manager, CallbackServer
from .gateway import gateway_proxy, AuthenticationRequired, GatewayError


class UnoStdioServer:
    """Uno MCP Stdio Server"""
    
    def __init__(self):
        self.server = Server("uno-mcp-stdio")
        self._authenticated = False
        self._tools_cache: Optional[list] = None
        self._setup_handlers()
    
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
    
    def _setup_handlers(self):
        """设置 MCP 请求处理器"""
        
        @self.server.list_tools()
        async def handle_list_tools() -> list[Tool]:
            """处理 tools/list 请求"""
            self._log("收到 tools/list 请求")
            
            # 检查是否已认证
            is_authenticated = self._authenticated or bool(await token_manager.get_valid_token())
            
            # 获取工具列表（proxy 内部会自动处理 default token）
            try:
                response = await gateway_proxy.list_tools()
                
                if "result" in response and "tools" in response["result"]:
                    tools_data = response["result"]["tools"]
                    self._tools_cache = tools_data
                    
                    # 转换为 MCP Tool 对象
                    tools = []
                    
                    # 始终在列表开头添加认证工具（用于首次认证、重新认证、退出登录等）
                    if is_authenticated:
                        auth_description = "🔐 认证管理工具。当前状态：✅ 已登录。支持的操作：login(重新登录)、logout(退出登录)、status(查看状态)"
                    else:
                        auth_description = "🔐 认证管理工具。当前状态：❌ 未登录。请调用此工具完成认证后才能使用其他工具。支持的操作：login(登录)、status(查看状态)"
                    
                    tools.append(Tool(
                        name="uno_auth",
                        description=auth_description,
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": ["login", "logout", "status"],
                                    "description": "操作类型：login(登录/重新登录)、logout(退出登录)、status(查看状态)。默认为 login"
                                }
                            },
                            "required": []
                        }
                    ))
                    
                    for t in tools_data:
                        tools.append(Tool(
                            name=t["name"],
                            description=t.get("description", ""),
                            inputSchema=t.get("inputSchema", {"type": "object"})
                        ))
                    
                    self._log(f"返回 {len(tools)} 个工具 (已认证: {is_authenticated})")
                    return tools
                else:
                    self._log(f"Gateway 返回格式异常: {response}")
                    return []
                    
            except GatewayError as e:
                self._log(f"获取工具列表失败: {e}")
                # 如果获取失败，返回认证工具
                return [
                    Tool(
                        name="uno_auth",
                        description="🔐 认证管理工具。请调用此工具获取认证链接。支持的操作：login(登录)、logout(退出)、status(查看状态)",
                        inputSchema={
                            "type": "object",
                            "properties": {
                                "action": {
                                    "type": "string",
                                    "enum": ["login", "logout", "status"],
                                    "description": "操作类型：login(登录/重新登录)、logout(退出登录)、status(查看状态)。默认为 login"
                                }
                            },
                            "required": []
                        }
                    )
                ]
        
        @self.server.call_tool()
        async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
            """处理 tools/call 请求"""
            self._log(f"收到 tools/call 请求: {name}")
            
            # 处理认证请求
            if name == "uno_auth":
                action = arguments.get("action", "login")
                return await self._handle_auth_request(action=action)
            
            # 检查认证
            try:
                await self._ensure_authenticated()
            except AuthenticationRequired:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": "authentication_required",
                        "message": "需要认证，请先调用 uno_auth 工具"
                    }, ensure_ascii=False)
                )]
            
            # 代理到 gateway
            try:
                response = await gateway_proxy.call_tool(name, arguments, request_id=1)
                
                if "result" in response:
                    result = response["result"]
                    # 返回工具调用结果
                    if "content" in result:
                        contents = []
                        for item in result["content"]:
                            if item.get("type") == "text":
                                contents.append(TextContent(
                                    type="text",
                                    text=item.get("text", "")
                                ))
                        return contents
                    else:
                        return [TextContent(
                            type="text",
                            text=json.dumps(result, ensure_ascii=False, indent=2)
                        )]
                elif "error" in response:
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "error": response["error"].get("code"),
                            "message": response["error"].get("message")
                        }, ensure_ascii=False)
                    )]
                else:
                    return [TextContent(
                        type="text",
                        text=json.dumps(response, ensure_ascii=False)
                    )]
                    
            except AuthenticationRequired:
                token_manager.clear_credentials()
                self._authenticated = False
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": "authentication_expired",
                        "message": "认证已过期，请重新调用 uno_auth 工具"
                    }, ensure_ascii=False)
                )]
            except GatewayError as e:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": "gateway_error",
                        "message": str(e)
                    }, ensure_ascii=False)
                )]
    
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
    
    async def _handle_auth_request(self, action: str = "login") -> list[TextContent]:
        """
        处理认证请求
        
        Args:
            action: 操作类型
                - login: 登录或重新登录
                - logout: 退出登录
                - status: 查看认证状态
        """
        self._log(f"处理认证请求: action={action}")
        
        # 处理状态查询
        if action == "status":
            token = await token_manager.get_valid_token()
            if token:
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "status": "authenticated",
                        "message": "✅ 当前已登录",
                        "hint": "可使用 action='logout' 退出登录，或 action='login' 重新登录"
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
                self._authenticated = False
                self._log("用户已退出登录")
                
                # 发送工具列表变更通知
                try:
                    session = self.server.request_context.session
                    await session.send_tool_list_changed()
                    self._log("已发送 tools/list_changed 通知")
                except Exception as e:
                    self._log(f"发送通知失败（客户端可能不支持）: {e}")
                
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
        
        # 返回认证信息
        auth_message = {
            "status": "authentication_required",
            "message": "请在浏览器中完成认证",
            "auth_url": auth_url,
            "browser_opened": browser_opened,
            "instructions": [
                "1. 点击上面的链接或复制到浏览器打开",
                "2. 在 MCPMarket 完成登录/授权",
                "3. 授权后页面会自动关闭",
                "4. 返回这里继续使用"
            ]
        }
        
        self._log(f"认证 URL: {auth_url}")
        self._log("等待用户完成认证...")
        
        # 先返回认证链接
        # 注意：这里需要异步等待回调，但 MCP 的 call_tool 是同步返回的
        # 所以我们需要在后台等待，同时返回信息给用户
        
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
        code = callback_data.get("code")
        credentials = await token_manager.exchange_code_for_token(
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            client_id=client_id
        )
        
        if credentials:
            self._authenticated = True
            self._log("认证成功！")
            
            # 发送工具列表变更通知，让客户端刷新工具列表
            try:
                session = self.server.request_context.session
                await session.send_tool_list_changed()
                self._log("已发送 tools/list_changed 通知")
            except Exception as e:
                self._log(f"发送通知失败（客户端可能不支持）: {e}")
            
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


async def run_server():
    """运行服务器入口"""
    server = UnoStdioServer()
    await server.run()

