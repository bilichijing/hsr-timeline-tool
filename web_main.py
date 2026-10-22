"""Web 前端入口。

运行：

    python web_main.py                 # http://127.0.0.1:8765
    python web_main.py --port 9000
    python web_main.py --open          # 启动后自动打开浏览器
    python web_main.py --host 0.0.0.0  # 局域网可访问（注意本机无鉴权）

桌面端仍为 `python ui_main.py`，两者可同时运行（互不干扰）。
"""

from __future__ import annotations

import argparse
import sys
import threading
import webbrowser


def main() -> int:
    parser = argparse.ArgumentParser(description="星穹铁道排轴工具 · Web 前端")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8765, help="端口（默认 8765）")
    parser.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = parser.parse_args()

    url = f"http://{args.host}:{args.port}/"
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    from src.web.server import serve

    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
