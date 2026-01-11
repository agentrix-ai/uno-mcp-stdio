"""
Token 管理模块

负责 token 的存储、读取、刷新和验证。
支持从 gateway 获取 OAuth 元数据和动态客户端注册。
"""

import json
import time
import secrets
import hashlib
import base64
import webbrowser
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict, field
import httpx

from ..config import settings


@dataclass
class Credentials:
    """存储的认证信息"""
    access_token: str
    refresh_token: str
    expires_at: int  # Unix timestamp
    token_type: str = "Bearer"
    
    def is_expired(self, buffer_seconds: int = 60) -> bool:
        """检查 token 是否过期（提前 buffer_seconds 秒判定为过期）"""
        return time.time() >= (self.expires_at - buffer_seconds)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Credentials":
        """从字典创建"""
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
            token_type=data.get("token_type", "Bearer")
        )


@dataclass
class OAuthMetadata:
    """OAuth 服务器元数据（从 well-known 获取）"""
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: Optional[str] = None
    userinfo_endpoint: Optional[str] = None
    revocation_endpoint: Optional[str] = None
    scopes_supported: list = field(default_factory=list)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OAuthMetadata":
        """从字典创建"""
        return cls(
            issuer=data.get("issuer", ""),
            authorization_endpoint=data.get("authorization_endpoint", ""),
            token_endpoint=data.get("token_endpoint", ""),
            registration_endpoint=data.get("registration_endpoint"),
            userinfo_endpoint=data.get("userinfo_endpoint"),
            revocation_endpoint=data.get("revocation_endpoint"),
            scopes_supported=data.get("scopes_supported", [])
        )


@dataclass
class ClientRegistration:
    """动态注册的客户端信息"""
    client_id: str
    client_secret: Optional[str] = None
    redirect_uris: list = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ClientRegistration":
        """从字典创建"""
        return cls(
            client_id=data["client_id"],
            client_secret=data.get("client_secret"),
            redirect_uris=data.get("redirect_uris", [])
        )


class TokenManager:
    """Token 管理器"""
    
    def __init__(self):
        self._credentials: Optional[Credentials] = None
        self._credentials_path = settings.get_credentials_path()
        self._oauth_metadata: Optional[OAuthMetadata] = None
        self._client_registration: Optional[ClientRegistration] = None
        self._client_registration_path = self._credentials_path.parent / "client.json"
    
    def _log(self, message: str):
        """输出日志到 stderr（避免干扰 stdio 通信）"""
        import sys
        if settings.debug:
            print(f"[TokenManager] {message}", file=sys.stderr)
    
    # ==================== OAuth Metadata ====================
    
    async def get_oauth_metadata(self) -> Optional[OAuthMetadata]:
        """
        从 gateway 获取 OAuth 元数据
        
        通过 /.well-known/oauth-authorization-server 端点获取。
        """
        if self._oauth_metadata:
            return self._oauth_metadata
        
        # 从 gateway URL 构建 well-known URL
        gateway_base = settings.get_gateway_base_url()
        wellknown_url = f"{gateway_base}/.well-known/oauth-authorization-server"
        
        self._log(f"获取 OAuth 元数据: {wellknown_url}")
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(wellknown_url)
                
                if response.status_code == 200:
                    data = response.json()
                    self._oauth_metadata = OAuthMetadata.from_dict(data)
                    self._log(f"OAuth 元数据获取成功: issuer={self._oauth_metadata.issuer}")
                    self._log(f"  authorization_endpoint: {self._oauth_metadata.authorization_endpoint}")
                    self._log(f"  token_endpoint: {self._oauth_metadata.token_endpoint}")
                    self._log(f"  registration_endpoint: {self._oauth_metadata.registration_endpoint}")
                    return self._oauth_metadata
                else:
                    self._log(f"获取 OAuth 元数据失败: {response.status_code}")
                    return None
                    
        except Exception as e:
            self._log(f"获取 OAuth 元数据异常: {e}")
            return None
    
    # ==================== Dynamic Client Registration ====================
    
    def load_client_registration(self) -> Optional[ClientRegistration]:
        """从文件加载客户端注册信息"""
        if self._client_registration:
            return self._client_registration
        
        if not self._client_registration_path.exists():
            return None
        
        try:
            with open(self._client_registration_path, "r") as f:
                data = json.load(f)
            self._client_registration = ClientRegistration.from_dict(data)
            self._log(f"已加载客户端注册信息: client_id={self._client_registration.client_id}")
            return self._client_registration
        except Exception as e:
            self._log(f"加载客户端注册信息失败: {e}")
            return None
    
    def save_client_registration(self, registration: ClientRegistration):
        """保存客户端注册信息"""
        self._client_registration = registration
        
        self._client_registration_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self._client_registration_path, "w") as f:
            json.dump(registration.to_dict(), f, indent=2)
        
        self._log(f"已保存客户端注册信息: client_id={registration.client_id}")
    
    async def register_client(self, redirect_uri: str) -> Optional[ClientRegistration]:
        """
        动态注册 OAuth 客户端 (RFC 7591)
        
        Args:
            redirect_uri: 回调 URI
            
        Returns:
            注册成功的客户端信息
        """
        # 获取 OAuth 元数据
        metadata = await self.get_oauth_metadata()
        if not metadata or not metadata.registration_endpoint:
            self._log("无法获取注册端点")
            return None
        
        self._log(f"注册客户端: {metadata.registration_endpoint}")
        
        # RFC 7591 客户端注册请求
        registration_request = {
            "client_name": "Uno MCP Stdio",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",  # 公开客户端，使用 PKCE
            "application_type": "native"
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    metadata.registration_endpoint,
                    json=registration_request,
                    headers={"Content-Type": "application/json"}
                )
                
                if response.status_code in [200, 201]:
                    data = response.json()
                    registration = ClientRegistration(
                        client_id=data["client_id"],
                        client_secret=data.get("client_secret"),
                        redirect_uris=data.get("redirect_uris", [redirect_uri])
                    )
                    self.save_client_registration(registration)
                    self._log(f"客户端注册成功: client_id={registration.client_id}")
                    return registration
                else:
                    self._log(f"客户端注册失败: {response.status_code} {response.text}")
                    return None
                    
        except Exception as e:
            self._log(f"客户端注册异常: {e}")
            return None
    
    async def ensure_client_registered(self, redirect_uri: str) -> Optional[str]:
        """
        确保客户端已注册，返回 client_id
        
        如果已有注册信息，直接返回。
        否则进行动态注册。
        """
        # 先尝试加载已有的注册信息
        registration = self.load_client_registration()
        if registration:
            return registration.client_id
        
        # 进行动态注册
        registration = await self.register_client(redirect_uri)
        if registration:
            return registration.client_id
        
        # 注册失败，使用默认 client_id
        self._log("动态注册失败，使用默认 client_id")
        return settings.oauth_client_id
    
    # ==================== Credentials Management ====================
    
    def load_credentials(self) -> Optional[Credentials]:
        """从文件加载 credentials"""
        if self._credentials:
            return self._credentials
        
        if not self._credentials_path.exists():
            self._log(f"Credentials 文件不存在: {self._credentials_path}")
            return None
        
        try:
            with open(self._credentials_path, "r") as f:
                data = json.load(f)
            self._credentials = Credentials.from_dict(data)
            self._log(f"已加载 credentials，过期时间: {self._credentials.expires_at}")
            return self._credentials
        except Exception as e:
            self._log(f"加载 credentials 失败: {e}")
            return None
    
    def save_credentials(self, credentials: Credentials):
        """保存 credentials 到文件"""
        self._credentials = credentials
        
        # 确保目录存在
        self._credentials_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(self._credentials_path, "w") as f:
            json.dump(credentials.to_dict(), f, indent=2)
        
        self._log(f"已保存 credentials 到: {self._credentials_path}")
    
    def clear_credentials(self):
        """清除 credentials"""
        self._credentials = None
        if self._credentials_path.exists():
            self._credentials_path.unlink()
            self._log("已清除 credentials")
    
    async def get_valid_token(self) -> Optional[str]:
        """
        获取有效的 access_token
        
        如果 token 过期，尝试刷新。
        返回 None 表示需要重新认证。
        """
        credentials = self.load_credentials()
        
        if not credentials:
            return None
        
        # 检查是否过期
        if credentials.is_expired():
            self._log("Token 已过期，尝试刷新...")
            refreshed = await self.refresh_token(credentials.refresh_token)
            if refreshed:
                return refreshed.access_token
            else:
                self._log("刷新失败，需要重新认证")
                self.clear_credentials()
                return None
        
        return credentials.access_token
    
    async def refresh_token(self, refresh_token: str) -> Optional[Credentials]:
        """使用 refresh_token 刷新 access_token"""
        # 获取 OAuth 元数据
        metadata = await self.get_oauth_metadata()
        if not metadata:
            self._log("无法获取 OAuth 元数据")
            return None
        
        # 获取 client_id
        registration = self.load_client_registration()
        client_id = registration.client_id if registration else settings.oauth_client_id
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    metadata.token_endpoint,
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                        "client_id": client_id
                    },
                    headers={"Accept": "application/json"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    credentials = Credentials(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token", refresh_token),
                        expires_at=int(time.time()) + data.get("expires_in", 3600),
                        token_type=data.get("token_type", "Bearer")
                    )
                    self.save_credentials(credentials)
                    self._log("Token 刷新成功")
                    return credentials
                else:
                    self._log(f"Token 刷新失败: {response.status_code} {response.text}")
                    return None
                    
        except Exception as e:
            self._log(f"Token 刷新异常: {e}")
            return None
    
    async def exchange_code_for_token(
        self, 
        code: str, 
        code_verifier: str, 
        redirect_uri: str,
        client_id: str
    ) -> Optional[Credentials]:
        """用 authorization code 交换 token"""
        # 获取 OAuth 元数据
        metadata = await self.get_oauth_metadata()
        if not metadata:
            self._log("无法获取 OAuth 元数据")
            return None
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    metadata.token_endpoint,
                    data={
                        "grant_type": "authorization_code",
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "client_id": client_id,
                        "code_verifier": code_verifier
                    },
                    headers={"Accept": "application/json"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    credentials = Credentials(
                        access_token=data["access_token"],
                        refresh_token=data.get("refresh_token", ""),
                        expires_at=int(time.time()) + data.get("expires_in", 3600),
                        token_type=data.get("token_type", "Bearer")
                    )
                    self.save_credentials(credentials)
                    self._log("Token 交换成功")
                    return credentials
                else:
                    self._log(f"Token 交换失败: {response.status_code} {response.text}")
                    return None
                    
        except Exception as e:
            self._log(f"Token 交换异常: {e}")
            return None
    
    # ==================== PKCE & OAuth URL ====================
    
    @staticmethod
    def generate_pkce() -> tuple[str, str]:
        """
        生成 PKCE code_verifier 和 code_challenge
        
        Returns:
            (code_verifier, code_challenge)
        """
        # 生成 code_verifier (43-128 字符)
        code_verifier = secrets.token_urlsafe(64)[:128]
        
        # 生成 code_challenge (SHA256 + base64url)
        digest = hashlib.sha256(code_verifier.encode()).digest()
        code_challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
        
        return code_verifier, code_challenge
    
    @staticmethod
    def generate_state() -> str:
        """生成 OAuth state 参数"""
        return secrets.token_urlsafe(32)
    
    async def build_auth_url(
        self, 
        redirect_uri: str, 
        state: str, 
        code_challenge: str,
        client_id: str
    ) -> Optional[str]:
        """构建 OAuth 认证 URL"""
        from urllib.parse import urlencode
        
        # 获取 OAuth 元数据
        metadata = await self.get_oauth_metadata()
        if not metadata:
            self._log("无法获取 OAuth 元数据")
            return None
        
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "scope": "openid profile"
        }
        
        return f"{metadata.authorization_endpoint}?{urlencode(params)}"
    
    def open_auth_url(self, url: str) -> bool:
        """尝试在浏览器中打开认证 URL"""
        try:
            webbrowser.open(url)
            return True
        except Exception as e:
            self._log(f"无法打开浏览器: {e}")
            return False


# 全局实例
token_manager = TokenManager()
