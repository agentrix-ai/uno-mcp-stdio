"""
Uno MCP Stdio - 入口文件

提供命令行入口，启动 stdio server。

用法:
    uvx uno-mcp-stdio          # 本地模式（默认）
    uvx uno-mcp-stdio --link   # 链接模式（用于 Manus 等远程服务器场景）
"""

import sys
import argparse
import asyncio

from .config import settings


def print_banner(link_mode: bool = False):
    """打印启动横幅（到 stderr，避免干扰 stdio）"""
    mode_str = "Link Mode (远程)" if link_mode else "Local Mode (本地)"
    banner = f"""
╔═══════════════════════════════════════════════════════════╗
║                    Uno MCP Stdio                          ║
║         Local proxy for Uno MCP Gateway                   ║
║                    [{mode_str}]                     
╚═══════════════════════════════════════════════════════════╝
"""
    print(banner, file=sys.stderr)
    print(f"  Gateway: {settings.gateway_url}", file=sys.stderr)
    print(f"  Credentials: {settings.get_credentials_path()}", file=sys.stderr)
    print(f"  Auth Mode: {'link' if link_mode else 'local'}", file=sys.stderr)
    print(f"  Debug: {settings.debug}", file=sys.stderr)
    print("", file=sys.stderr)


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="Uno MCP Stdio - Local proxy for Uno MCP Gateway",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
认证模式说明:
  本地模式 (默认):  会弹出浏览器完成认证，适用于本地运行
  链接模式 (--link): 返回认证链接，用户在其他设备完成认证后输入授权码
                    适用于 Manus 等远程服务器场景

示例配置 (Manus/Cherry Studio):
  {
    "mcpServers": {
      "uno": {
        "command": "uvx",
        "args": ["uno-mcp-stdio", "--link"]
      }
    }
  }
"""
    )
    
    parser.add_argument(
        "--link", "-l",
        action="store_true",
        help="启用链接模式（用于远程服务器，如 Manus）。认证时返回链接，用户手动完成后输入授权码"
    )
    
    parser.add_argument(
        "--debug", "-d",
        action="store_true",
        help="启用调试模式，输出详细日志"
    )
    
    return parser.parse_args()


def main():
    """主入口函数"""
    # 解析命令行参数
    args = parse_args()
    
    # 设置调试模式
    if args.debug:
        settings.debug = True
    
    # 设置认证模式
    link_mode = args.link
    if link_mode:
        settings.auth_mode = "link"
    
    # 打印横幅
    if settings.debug:
        print_banner(link_mode)
    
    # 导入并运行服务器（传入 link_mode）
    from .stdio_server import run_server
    
    try:
        asyncio.run(run_server(link_mode=link_mode))
    except KeyboardInterrupt:
        print("\n[UnoStdio] 收到中断信号，正在退出...", file=sys.stderr)
        sys.exit(0)
    except Exception as e:
        print(f"[UnoStdio] 错误: {e}", file=sys.stderr)
        if settings.debug:
            import traceback
            traceback.print_exc(file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

