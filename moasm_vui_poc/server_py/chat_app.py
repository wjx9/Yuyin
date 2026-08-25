"""总流程 demo：闲聊 / TripNow（公开+个人）/ 快递100 / 高德 统一分流。

运行：
    # 先在 .env 或环境变量里配置好各能力的 key（缺哪个就自动不启用哪个能力）
    #   GEMINI_API_KEY   —— 必需（意图分类 + 闲聊兜底）
    #   TRIPNOW_API_KEY  —— 启用出行能力；个人能力还需 --union-id
    #   KUAIDI100_KEY / KUAIDI100_CUSTOMER —— 启用快递查询
    #   AMAP_KEY         —— 启用高德地图
    python chat_app.py                      # 进入交互式对话
    python chat_app.py "深圳北到广州的高铁"   # 单轮
    python chat_app.py --show-intent "附近的咖啡"

整条链路：
    用户输入 → LangGraph execute（Dispatcher 分类并执行 Handler）
            → LangGraph compose（Gemini 将工具结果整理为自然语言）→ 最终回复
"""

from __future__ import annotations

import argparse
import os
import sys

# 本文件在 server_py/ 下：运行时脚本目录(server_py)自动入 sys.path，故 import routing 等可用；
# 但共享模块 ui_py 在项目根，需把根目录也加入 sys.path 才能 import ui_py。
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Windows 中文控制台默认 gbk 编码，遇到 emoji 等非 gbk 字符（如天气结果里的 ⛅）会
# 直接抛 UnicodeEncodeError 崩溃。保留控制台原编码（中文照常显示），仅把无法编码的
# 字符替换为占位符，避免崩溃。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass


def _load_env() -> None:
    """加载 .env（override=True：后加载者覆盖先加载者 / 系统环境变量）。

    打包成 exe 时，加载顺序（后者覆盖前者）：
      1) 打进包内的 .env（_MEIPASS/.env）—— 同事零配置即可用的内置默认；
      2) exe 同级目录的 .env（若存在）—— 同事可放一份覆盖内置值，无需重新打包。
    源码运行时沿用 dotenv 默认行为（从 cwd 向上找）。
    """
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
            load_dotenv(external, override=True)  # 外部覆盖内置
    else:
        load_dotenv(override=True)


_load_env()

from routing import RouteContext, SessionHistory, setup_logging
from orchestration import build_assistant_graph
from ui_py import Presenter, TerminalPresenter

_EPILOG = """\
示例：
  python chat_app.py                                进入交互模式（多轮）
  python chat_app.py "深圳北到广州的高铁"              单轮，命中 tripnow_public
  python chat_app.py --show-intent "附近的咖啡"      打印命中意图（amap）
  python chat_app.py "查下 SF1234567890 到哪了"      命中 express_tracking
  python chat_app.py --union-id <id> "我的行程"      命中 tripnow_personal（需身份）
  python chat_app.py --debug "今天天气"              开启路由调试日志

能力开关（.env 缺哪个 key 就不启用对应能力）：
  GEMINI_API_KEY                       意图分类 + 闲聊兜底（必需）
  TRIPNOW_API_KEY                      出行能力（个人能力还需 --union-id）
  KUAIDI100_KEY / KUAIDI100_CUSTOMER   快递查询
  AMAP_KEY                             高德地图

调试日志开关（二选一，--debug 优先级最高）：
  .env: ROUTING_LOG_LEVEL=DEBUG        持久开启，打印分类细节/命中技能/耗时
  CLI : --debug                        本次运行临时开启

链路：输入 → LangGraph execute（Dispatcher 分类并调用对应 Handler）
      → LangGraph compose（Gemini 整理工具结果）→ 最终回复
"""


def _run_once(
    assistant,
    query: str,
    context: RouteContext,
    show_intent: bool,
    history: SessionHistory,
    presenter: Presenter,
) -> None:
    presenter.show_input(query)  # 先画输入框，dispatch 期间的日志随后落在中间
    context.history = history.turns  # 本轮之前的历史
    result = assistant.run(query, context)
    presenter.show_output(result.text, intent=result.intent if show_intent else None)
    history.append(query, result.text)
    history.save()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="chat_app",
        description="多能力分流对话 demo：闲聊 / TripNow（公开+个人）/ 快递100 / 高德 统一路由。",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "query",
        nargs="?",
        metavar="QUERY",
        help="单轮提问内容；省略则进入交互模式（多轮，输入 exit 退出）",
    )
    parser.add_argument(
        "--union-id",
        metavar="ID",
        help="TripNow 个人身份（OAuth 获取的 union_id），用于查我的行程/订单等个人能力",
    )
    parser.add_argument(
        "--location",
        metavar="经度,纬度",
        help='当前位置坐标，如 "116.39,39.90"，供高德等基于位置的能力使用',
    )
    parser.add_argument("--show-intent", action="store_true", help="在回复前打印本轮命中的意图 id")
    parser.add_argument("--no-data", action="store_true", help="不请求结构化数据（仅要自然语言回复）")
    parser.add_argument(
        "--persist-memory",
        action="store_true",
        help="将最近 30 轮会话持久化到 ~/.tripnow/history.json；默认只记住本次启动期间的对话",
    )
    parser.add_argument(
        "--reset-memory",
        action="store_true",
        help="清空已保存的会话历史（需同时指定 --persist-memory）",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="开启路由调试日志（等价于临时 ROUTING_LOG_LEVEL=DEBUG）",
    )
    parser.add_argument("--no-color", action="store_true", help="关闭彩色输出（仅保留框线）")
    parser.add_argument(
        "--once",
        action="store_true",
        help="只回答一轮就退出（用于脚本/管道）；默认进入连续对话循环",
    )
    args = parser.parse_args(argv)
    if args.reset_memory and not args.persist_memory:
        parser.error("--reset-memory 需同时指定 --persist-memory")

    presenter = TerminalPresenter(color=False if args.no_color else None)
    setup_logging(
        "DEBUG" if args.debug else None,
        formatter=presenter.log_formatter(),
        namespaces=("routing", "orchestration"),
    )

    try:
        assistant = build_assistant_graph()
    except RuntimeError as e:
        print(f"启动失败：{e}", file=sys.stderr)
        return 1

    context = RouteContext(
        union_id=args.union_id,
        location=args.location,
        include_data=not args.no_data,
    )

    history = SessionHistory() if args.persist_memory else SessionHistory(path=None)
    if args.reset_memory:
        history.clear()
    history.load()

    presenter.banner(assistant.capabilities)

    # --once：脚本/管道场景，只回答一轮（需带初始 query）
    if args.once:
        if not args.query:
            print("--once 需要同时给出一句提问", file=sys.stderr)
            return 2
        _run_once(assistant, args.query, context, args.show_intent, history, presenter)
        return 0

    presenter.intro(assistant.specs)

    # 命令行带了 query 就作为第一轮，随后照常进入连续对话循环（与 exe 行为一致）
    if args.query:
        _run_once(assistant, args.query, context, args.show_intent, history, presenter)

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
        _run_once(assistant, query, context, args.show_intent, history, presenter)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
