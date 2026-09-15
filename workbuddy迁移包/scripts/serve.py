"""trip-handbook-maker 本地预览服务器（仅标准库）。

用法：python scripts/serve.py [端口]   （默认 8642，只绑定 127.0.0.1）
在工作区根目录起 http.server，浏览器打开 http://127.0.0.1:8642/trips/<slug>/handbook.html 预览。
Ctrl+C 退出；不做任何写操作、不提供上传。
"""
from __future__ import annotations

import http.server
import socketserver
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    port = int(argv[0]) if argv else 8642

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def log_message(self, fmt, *args):  # 精简控制台输出
            sys.stdout.write("  [serve] %s - %s\n" % (self.address_string(), fmt % args))

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("127.0.0.1", port), Handler) as httpd:
        print(f"预览服务已启动：http://127.0.0.1:{port}/trips/  （Ctrl+C 停止）")
        print("提示：打开 http://127.0.0.1:%d/trips/sy-yj-cc-demo/handbook.html 查看演示" % port)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
