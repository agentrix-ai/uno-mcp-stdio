"""
Uno MCP Stdio - 入口文件

提供命令行入口，启动 stdio server。
"""

import sys
import asyncio

from .config import settings


def print_banner():
    """打印启动横幅（到 stderr，避免干扰 stdio）"""
    banner = """
╔═══════════════════════════════════════════════════════════╗
║                    Uno MCP Stdio                          ║
║         Local proxy for Uno MCP Gateway                   ║
╚═══════════════════════════════════════════════════════════╝
"""
    print(banner, file=sys.stderr)
    print(f"  Gateway: {settings.gateway_url}", file=sys.stderr)
    print(f"  Credentials: {settings.get_credentials_path()}", file=sys.stderr)
    print(f"  Debug: {settings.debug}", file=sys.stderr)
    print("", file=sys.stderr)


def main():
    """主入口函数"""
    # 打印横幅
    if settings.debug:
        print_banner()
    
    # 导入并运行服务器
    from .stdio_server import run_server
    
    try:
        asyncio.run(run_server())
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

