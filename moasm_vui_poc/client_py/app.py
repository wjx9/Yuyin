"""交互式 / 单轮 CLI —— 对标 chat_app.py，但把"本地 Dispatcher"换成"HTTP 远端"。

刻意复用 ui.TerminalPresenter（同一套聊天气泡），让 CS 版与单机版"看起来一样"。
差别只有两点，都是 CS 架构的必然：
  1. 多轮历史在服务端按 session_id 维护，客户端只固定带同一个 session_id；
  2. 路由调试日志在服务端打，客户端中间不再有"夹在输入输出之间的日志区"。

运行：
    python -m client_py                      # 交互模式（多轮）
    python -m client_py "深圳到北京怎么最舒服?"  # 单轮
    python -m client_py --server http://192.168.1.5:8000 --show-intent "附近咖啡"
"""

from __future__ import annotations

import argparse
import sys

# 允许 `python client_py/app.py` 直接跑（把工程根加入 sys.path），也支持 `python -m client_py`
if __package__ in (None, ""):
    import os

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from client_py.client import ServerClient, ServerError
    from client_py.config import ClientConfig
else:
    from .client import ServerClient, ServerError
    from .config import ClientConfig

# Windows 中文控制台对 emoji 等非 gbk 字符会崩；与 chat_app.py 同款保护
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

from ui import TerminalPresenter

_EPILOG = """\
示例：
  python -m client_py                                进入交互模式（多轮）
  python -m client_py "深圳到北京怎么最舒服?"           单轮，命中 tripnow_public
  python -m client_py --show-intent "附近咖啡"         打印命中意图
  python -m client_py --server http://192.168.1.5:8000  指向局域网内的 serve.py
  python -m client_py --token <密钥> "你好"            服务端开了 Bearer 鉴权时带上

服务端地址 / 鉴权 / 位置 也可写进 .env：
  SERVER_URL=http://192.168.1.5:8000
  SERVER_AUTH_TOKEN=<密钥>
  DEMO_LOCATION=113.92,22.53
"""


def _run_once(
    client: ServerClient,
    query: str,
    presenter: TerminalPresenter,
    show_intent: bool,
) -> None:
    presenter.show_input(query)
    try:
        reply = client.chat(query)
    except ServerError as e:
        presenter.show_output(f"[与服务端通信失败] {e}", intent=None)
        return
    presenter.show_output(reply.text, intent=reply.intent if show_intent else None)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="client_py",
        description="多能力分流对话（client-server 客户端）：把输入发给 serve.py，渲染其回复。",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("query", nargs="?", metavar="QUERY", help="单轮提问；省略则进入交互模式")
    parser.add_argument("--server", metavar="URL", help="服务端地址（默认 env SERVER_URL 或 http://127.0.0.1:8000）")
    parser.add_argument("--token", metavar="TOKEN", help="Bearer 鉴权密钥（默认 env SERVER_AUTH_TOKEN）")
    parser.add_argument("--location", metavar="经度,纬度", help='当前位置，如 "116.39,39.90"，供高德等用')
    parser.add_argument("--session", metavar="ID", help="固定会话 id（默认随机生成；多轮记忆按它隔离）")
    parser.add_argument("--show-intent", action="store_true", help="在回复前打印本轮命中的意图 id")
    parser.add_argument("--no-color", action="store_true", help="关闭彩色输出（仅保留框线）")
    parser.add_argument("--once", action="store_true", help="只回答一轮就退出（用于脚本/管道）")
    args = parser.parse_args(argv)

    config = ClientConfig.from_env(
        server_url=args.server,
        auth_token=args.token,
        location=args.location,
        session_id=args.session,
    )
    client = ServerClient(config)
    presenter = TerminalPresenter(color=False if args.no_color else None)

    # 启动即探活：顺带把服务端启用的能力打出来，等价于 chat_app 的 banner
    try:
        health = client.health()
    except ServerError as e:
        print(f"无法连接服务端 {config.server_url}：{e}", file=sys.stderr)
        print("请确认已在 PC 上运行 `python serve.py`，且手机/本机与它网络可达。", file=sys.stderr)
        return 1

    presenter.banner(health.capabilities)
    presenter.info(f"已连接服务端 {config.server_url}（会话 {config.session_id[:8]}…）")

    if args.once:
        if not args.query:
            print("--once 需要同时给出一句提问", file=sys.stderr)
            return 2
        _run_once(client, args.query, presenter, args.show_intent)
        return 0

    presenter.info("直接用自然语言提问即可，我会自动判断该用哪个能力。输入 exit / quit 退出。")

    if args.query:
        _run_once(client, args.query, presenter, args.show_intent)

    while True:
        try:
            query = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not query:
            continue
        if query.lower() in {"exit", "quit", "q"}:
            break
        _run_once(client, query, presenter, args.show_intent)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
