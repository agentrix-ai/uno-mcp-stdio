"""
OAuth 回调服务器

临时 HTTP 服务器，用于接收 OAuth 认证回调。
"""

import asyncio
import socket
from typing import Optional, Callable, Awaitable
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading

from ..config import settings


class CallbackHandler(BaseHTTPRequestHandler):
    """OAuth 回调请求处理器"""
    
    # 类变量，用于存储回调数据
    callback_data: Optional[dict] = None
    expected_state: Optional[str] = None
    callback_received: threading.Event = threading.Event()
    
    def log_message(self, format, *args):
        """禁用默认的日志输出（避免干扰 stdio）"""
        if settings.debug:
            import sys
            print(f"[CallbackServer] {format % args}", file=sys.stderr)
    
    def do_GET(self):
        """处理 GET 请求"""
        parsed = urlparse(self.path)
        
        if parsed.path == "/callback":
            self._handle_callback(parsed)
        elif parsed.path == "/health":
            self._send_response(200, "OK")
        else:
            self._send_response(404, "Not Found")
    
    def _handle_callback(self, parsed):
        """处理 OAuth 回调"""
        params = parse_qs(parsed.query)
        
        # 获取参数
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]
        error_description = params.get("error_description", ["Unknown error"])[0]
        
        # 检查错误
        if error:
            CallbackHandler.callback_data = {
                "success": False,
                "error": error,
                "error_description": error_description
            }
            self._send_html_response(400, self._error_page(error, error_description))
            CallbackHandler.callback_received.set()
            return
        
        # 验证 state
        if state != CallbackHandler.expected_state:
            CallbackHandler.callback_data = {
                "success": False,
                "error": "state_mismatch",
                "error_description": "State parameter does not match"
            }
            self._send_html_response(400, self._error_page("state_mismatch", "安全验证失败，请重试"))
            CallbackHandler.callback_received.set()
            return
        
        # 成功
        if code:
            CallbackHandler.callback_data = {
                "success": True,
                "code": code,
                "state": state
            }
            self._send_html_response(200, self._success_page())
            CallbackHandler.callback_received.set()
        else:
            CallbackHandler.callback_data = {
                "success": False,
                "error": "no_code",
                "error_description": "No authorization code received"
            }
            self._send_html_response(400, self._error_page("no_code", "未收到授权码"))
            CallbackHandler.callback_received.set()
    
    def _send_response(self, status: int, message: str):
        """发送纯文本响应"""
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(message.encode("utf-8"))
    
    def _send_html_response(self, status: int, html: str):
        """发送 HTML 响应"""
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))
    
    def _success_page(self) -> str:
        """成功页面 HTML"""
        return """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>认证成功 - Uno MCP</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .card {
            background: white;
            padding: 40px 60px;
            border-radius: 16px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            text-align: center;
        }
        .icon {
            font-size: 64px;
            margin-bottom: 20px;
        }
        h1 {
            color: #333;
            margin: 0 0 10px 0;
        }
        p {
            color: #666;
            margin: 0;
        }
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">✅</div>
        <h1>认证成功！</h1>
        <p>您可以关闭此页面，返回终端继续使用。</p>
    </div>
</body>
</html>
"""
    
    def _error_page(self, error: str, description: str) -> str:
        """错误页面 HTML"""
        return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>认证失败 - Uno MCP</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        }}
        .card {{
            background: white;
            padding: 40px 60px;
            border-radius: 16px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            text-align: center;
        }}
        .icon {{
            font-size: 64px;
            margin-bottom: 20px;
        }}
        h1 {{
            color: #333;
            margin: 0 0 10px 0;
        }}
        p {{
            color: #666;
            margin: 0;
        }}
        .error-code {{
            color: #999;
            font-size: 12px;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="card">
        <div class="icon">❌</div>
        <h1>认证失败</h1>
        <p>{description}</p>
        <p class="error-code">错误代码: {error}</p>
    </div>
</body>
</html>
"""


class CallbackServer:
    """OAuth 回调服务器管理器"""
    
    def __init__(self):
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None
        self._port: Optional[int] = None
    
    def _log(self, message: str):
        """输出日志到 stderr"""
        import sys
        if settings.debug:
            print(f"[CallbackServer] {message}", file=sys.stderr)
    
    def _find_free_port(self) -> int:
        """动态分配一个可用端口"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((settings.callback_host, 0))
            s.listen(1)
            port = s.getsockname()[1]
        return port
    
    def start(self, expected_state: str) -> int:
        """
        启动回调服务器
        
        Args:
            expected_state: 期望的 OAuth state 参数
            
        Returns:
            服务器监听的端口
        """
        # 重置状态
        CallbackHandler.callback_data = None
        CallbackHandler.expected_state = expected_state
        CallbackHandler.callback_received.clear()
        
        # 分配端口
        self._port = self._find_free_port()
        
        # 创建服务器
        self._server = HTTPServer(
            (settings.callback_host, self._port),
            CallbackHandler
        )
        
        # 在后台线程运行
        self._thread = threading.Thread(target=self._run_server, daemon=True)
        self._thread.start()
        
        self._log(f"回调服务器已启动: http://{settings.callback_host}:{self._port}")
        return self._port
    
    def _run_server(self):
        """运行服务器"""
        if self._server:
            self._server.serve_forever()
    
    def wait_for_callback(self, timeout: Optional[int] = None) -> Optional[dict]:
        """
        等待回调
        
        Args:
            timeout: 超时时间（秒），None 表示使用配置的默认值
            
        Returns:
            回调数据，超时返回 None
        """
        timeout = timeout or settings.callback_timeout
        
        self._log(f"等待回调，超时时间: {timeout}s")
        
        if CallbackHandler.callback_received.wait(timeout=timeout):
            return CallbackHandler.callback_data
        else:
            self._log("等待回调超时")
            return None
    
    def stop(self):
        """停止回调服务器"""
        if self._server:
            self._server.shutdown()
            self._server = None
            self._log("回调服务器已停止")
        
        if self._thread:
            self._thread.join(timeout=1)
            self._thread = None
    
    def get_redirect_uri(self) -> str:
        """获取回调 URI"""
        if not self._port:
            raise RuntimeError("Server not started")
        return f"http://{settings.callback_host}:{self._port}/callback"
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

