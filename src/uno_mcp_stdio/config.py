"""
配置管理模块

通过环境变量配置 uno-mcp-stdio。
"""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Uno MCP Stdio 配置"""
    
    # 使用 pydantic v2 的配置方式
    model_config = SettingsConfigDict(
        env_prefix="UNO_",
        env_file=None,  # 不读取 .env 文件，避免与其他项目冲突
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # 忽略额外的环境变量
    )
    
    # Gateway 配置
    gateway_url: str = Field(
        default="https://uno.mcpmarket.cn/mcp",
        description="Uno Gateway MCP 端点地址"
    )
    
    # Default Readonly Token - 用于未认证时获取工具列表
    # 与 Gateway 端的 DEFAULT_READONLY_TOKEN 保持一致
    default_readonly_token: str = Field(
        default="uno-default-readonly-token-for-tools-list-only",
        description="默认只读 Token，用于获取工具列表"
    )
    
    # MCPMarket OAuth 配置
    mcpmarket_url: str = Field(
        default="https://mcpmarket.cn",
        description="MCPMarket 服务地址（OAuth 认证）"
    )
    
    # OAuth 客户端配置（公开客户端，用于 PKCE 流程）
    oauth_client_id: str = Field(
        default="uno-stdio",
        description="OAuth 客户端 ID"
    )
    
    # Token 存储配置
    credentials_path: str = Field(
        default="~/.uno-mcp/credentials.json",
        description="Token 存储文件路径"
    )
    
    # 调试模式
    debug: bool = Field(
        default=False,
        description="调试模式"
    )
    
    # 回调服务器配置
    callback_host: str = Field(
        default="127.0.0.1",
        description="OAuth 回调服务器地址"
    )
    callback_timeout: int = Field(
        default=300,
        description="等待 OAuth 回调超时时间（秒）"
    )
    
    def get_credentials_path(self) -> Path:
        """获取 credentials 文件的完整路径"""
        path = Path(self.credentials_path).expanduser()
        # 确保父目录存在
        path.parent.mkdir(parents=True, exist_ok=True)
        return path
    
    def get_gateway_base_url(self) -> str:
        """获取 gateway 基础 URL（去掉 /mcp 后缀）"""
        url = self.gateway_url
        if url.endswith("/mcp"):
            return url[:-4]
        return url


# 全局配置实例
settings = Settings()

