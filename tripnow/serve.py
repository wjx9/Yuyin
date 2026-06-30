"""服务端启动入口（与 chat_app.py 平级，互不影响）。

    python serve.py                 # 监听 0.0.0.0:8000，局域网内手机可访问
    python serve.py --port 9000 --debug
    python serve.py --token <密钥>   # 开启 Bearer 鉴权（公网/阿里云建议开）

各能力 key 仍从 .env / 环境变量读取（缺哪个就不启用哪个），与 CLI 完全一致。
"""

from __future__ import annotations

import argparse
import logging
import os
import socket
import sys


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if getattr(sys, "frozen", False):
        bundled = os.path.join(getattr(sys, "_MEIPASS", ""), ".env")
        if os.path.isfile(bundled):
            load_dotenv(bundled, override=True)
        external = os.path.join(os.path.dirname(sys.executable), ".env")
        if os.path.isfile(external):
            load_dotenv(external, override=True)
    else:
        load_dotenv(override=True)


_load_env()

from routing import setup_logging
from server import ChatService
from server.http_server import build_http_server

_log = logging.getLogger("server")


def _lan_ip() -> str:
    """取本机在局域网的出口 IP（不真正发包，仅让内核选好网卡）。失败回退 127.0.0.1。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="serve",
        description="多能力分流助手 · 服务端（client-server 模式）",
    )
    parser.add_argument("--host", default="0.0.0.0", help="监听地址（默认 0.0.0.0，局域网可达）")
    parser.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    parser.add_argument("--token", help="Bearer 鉴权密钥；省略则读 env SERVER_AUTH_TOKEN，仍无则不鉴权")
    parser.add_argument("--debug", action="store_true", help="开启调试日志")
    args = parser.parse_args(argv)

    # 同时配置 routing 与 server 两个命名空间，让服务端日志（含 mock 鉴权提示）可见
    setup_logging("DEBUG" if args.debug else None, namespaces=("routing", "server"))

    token = args.token or os.getenv("SERVER_AUTH_TOKEN", "").strip() or None

    try:
        service = ChatService()
    except RuntimeError as e:
        print(f"启动失败：{e}", file=sys.stderr)
        return 1

    httpd = build_http_server(service, host=args.host, port=args.port, auth_token=token)

    lan = _lan_ip()
    print("多能力助手服务端已启动")
    print(f"  本机访问 : http://127.0.0.1:{args.port}")
    print(f"  局域网   : http://{lan}:{args.port}    （手机与本机同一 WiFi 时用这个）")
    print(f"  鉴权     : {'开启 (Bearer Token)' if token else '关闭（局域网试用）'}")
    print(f"  已启用能力: {', '.join(service.capabilities)}")
    print("  接口     : POST /chat   GET /health    （Ctrl+C 退出）")

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭…")
    finally:
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
