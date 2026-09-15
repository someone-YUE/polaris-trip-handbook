"""一键打开旅行攻略问卷页（仅标准库）。

用法：python scripts/open-questionnaire.py [端口]   （默认 8642）

做三件事：
1. 在项目根起一个只绑定 127.0.0.1 的静态服务；
2. 自动用系统默认浏览器打开问卷页；
3. 前台常驻（Ctrl+C 停止）。

问卷填完点「生成开工提示词」→ 复制提示词发回 Agent 即可。
若端口被占用，自动顺延试下一个（最多 10 个）。
"""
from __future__ import annotations

import http.server
import socket
import socketserver
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
Q_PATH = "/assets/intake-questionnaire/index.html"
PAGE = ROOT / "assets" / "intake-questionnaire" / "index.html"


def _port_in_use(port: int) -> bool:
    """在 Windows 上 allow_reuse_address 会让重复绑定"成功"但不收请求，
    所以不能靠 bind 成败判断端口是否空闲，必须先主动连一下。"""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _pick_port(start: int) -> tuple[socketserver.TCPServer, int]:
    """从 start 起找一个真正空闲的端口，返回 (server, port)。"""
    last_err: Exception | None = None
    for port in range(start, start + 10):
        if _port_in_use(port):
            continue
        try:
            srv = socketserver.TCPServer(("127.0.0.1", port), _make_handler())
            return srv, port
        except OSError as exc:  # 端口被占用
            last_err = exc
            continue
    raise SystemExit(f"端口 {start}~{start + 9} 都不可用：{last_err}")


def _make_handler():
    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(ROOT), **kwargs)

        def log_message(self, fmt, *args):
            sys.stdout.write("  [serve] %s - %s\n" % (self.address_string(), fmt % args))

    return Handler


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass

    if not PAGE.exists():
        raise SystemExit(f"找不到问卷页：{PAGE}\n（请确认脚本位于 <项目根>/scripts/ 下）")

    if argv and argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return 0
    try:
        base_port = int(argv[0]) if argv else 8642
    except ValueError:
        raise SystemExit(f"端口必须是数字，收到：{argv[0]}\n用法：python scripts/open-questionnaire.py [端口]")

    socketserver.TCPServer.allow_reuse_address = True
    httpd, port = _pick_port(base_port)
    url = f"http://127.0.0.1:{port}{Q_PATH}"

    print("=" * 56)
    print("  旅行攻略问卷已就绪")
    print("=" * 56)
    print(f"  问卷页：{url}")
    print("  填完点「生成开工提示词」→ 复制 → 发回 Agent 即可")
    print("  停止服务：Ctrl+C")
    print("=" * 56)

    threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    with httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
