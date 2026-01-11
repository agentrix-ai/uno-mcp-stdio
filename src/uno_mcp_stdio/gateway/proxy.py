"""
Gateway 代理

代理 MCP 请求到远程 Uno Gateway，附加 OAuth 认证头。
"""

import json
from typing import Dict, Any, Optional
import httpx

from ..config import settings
from ..auth import token_manager


# 允许使用 default token 的方法（只读操作）
READONLY_METHODS = {"initialize", "tools/list"}


class GatewayProxy:
    """Gateway 代理客户端"""
    
    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None
    
    def _log(self, message: str):
        """输出日志到 stderr"""
        import sys
        if settings.debug:
            print(f"[GatewayProxy] {message}", file=sys.stderr)
    
    async def _get_client(self) -> httpx.AsyncClient:
        """获取或创建 HTTP 客户端"""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client
    
    async def close(self):
        """关闭 HTTP 客户端"""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None
    
    async def send_request(
        self, 
        method: str, 
        params: Optional[Dict[str, Any]] = None,
        request_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        发送 MCP JSON-RPC 请求到 gateway
        
        Args:
            method: JSON-RPC 方法名
            params: 方法参数
            request_id: 请求 ID
            
        Returns:
            JSON-RPC 响应
            
        Raises:
            AuthenticationRequired: 需要认证（仅对非只读操作）
            GatewayError: Gateway 返回错误
        """
        # 获取真实 token
        access_token = await token_manager.get_valid_token()
        
        # 如果没有真实 token
        if not access_token:
            if method in READONLY_METHODS:
                # 只读操作：使用 default token
                access_token = settings.default_readonly_token
                self._log(f"使用 default token 执行: {method}")
            else:
                # 非只读操作：需要真实认证
                raise AuthenticationRequired("需要 OAuth 认证")
        
        # 构建请求
        payload = {
            "jsonrpc": "2.0",
            "method": method
        }
        
        if params:
            payload["params"] = params
        
        if request_id is not None:
            payload["id"] = request_id
        
        self._log(f"发送请求: method={method}, id={request_id}")
        
        # 发送请求
        client = await self._get_client()
        
        try:
            response = await client.post(
                settings.gateway_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}"
                }
            )
            
            # 处理 401 错误
            if response.status_code == 401:
                self._log("收到 401，token 可能已失效")
                # 如果是使用真实 token 收到 401，清除凭据
                if access_token != settings.default_readonly_token:
                    token_manager.clear_credentials()
                raise AuthenticationRequired("认证已过期，需要重新登录")
            
            # 处理其他错误
            if response.status_code != 200:
                self._log(f"Gateway 返回错误: {response.status_code}")
                raise GatewayError(
                    f"Gateway 返回 HTTP {response.status_code}",
                    status_code=response.status_code,
                    body=response.text
                )
            
            result = response.json()
            self._log(f"收到响应: {json.dumps(result, ensure_ascii=False)[:200]}")
            return result
            
        except httpx.RequestError as e:
            self._log(f"请求失败: {e}")
            raise GatewayError(f"网络请求失败: {e}")
    
    async def initialize(self) -> Dict[str, Any]:
        """发送 initialize 请求"""
        return await self.send_request("initialize", request_id=1)
    
    async def list_tools(self) -> Dict[str, Any]:
        """获取工具列表"""
        return await self.send_request("tools/list", request_id=2)
    
    async def call_tool(
        self, 
        name: str, 
        arguments: Dict[str, Any],
        request_id: int
    ) -> Dict[str, Any]:
        """调用工具（需要真实认证）"""
        return await self.send_request(
            "tools/call",
            params={"name": name, "arguments": arguments},
            request_id=request_id
        )


class AuthenticationRequired(Exception):
    """需要认证异常"""
    pass


class GatewayError(Exception):
    """Gateway 错误异常"""
    
    def __init__(
        self, 
        message: str, 
        status_code: Optional[int] = None,
        body: Optional[str] = None
    ):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


# 全局实例
gateway_proxy = GatewayProxy()
