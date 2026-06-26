"""命令行表现层。

只负责：解析参数 → 装配 (config + transport + service) → 调用业务方法 → 打印。
不含任何业务/协议逻辑，因此换成 GUI 时这层整个替换即可，下面三层不动。

用法示例：
    python main.py ask "查询明天北京到上海的火车票"
    python main.py ask "查询明天北京到上海的机票" --stream
    python main.py me  "查一下我的行程有没有更新状态" --union-id xxxx
    python main.py trips --union-id xxxx
    python main.py subscribe "关注今天D7561次广州到深圳北的一等座" --union-id xxxx
    python main.py prompts get                      # 仅 mcp
    python main.py prompts set '[{"scenario":1,"prompt":"..."}]'   # 仅 mcp
全局参数：--transport openapi|mcp  --env test|prod  --model xxx  --no-data
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import Settings, build_transport
from .errors import TripNowError, UnsupportedFeatureError
from .models import ChatResponse
from .services import PersonalTravelService, PublicTravelService
from .transport import PromptsCapable


def _build_settings(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    if args.transport:
        settings.transport = args.transport
    if args.env:
        settings.env = args.env
    if args.model:
        settings.model = args.model
    if getattr(args, "union_id", None):
        settings.union_id = args.union_id
    return settings


def _print_response(resp: ChatResponse, show_data: bool) -> None:
    print(resp.content)
    if show_data and resp.model_data is not None:
        print("\n--- 结构化数据 (model_data) ---")
        print(json.dumps(resp.model_data, ensure_ascii=False, indent=2))


def _cmd_ask(args, settings, transport) -> None:
    service = PublicTravelService(transport, model=settings.model)
    if args.stream:
        if not transport.supports_stream:
            raise UnsupportedFeatureError(
                f"{settings.transport} 不支持流式，请去掉 --stream 或改用 openapi"
            )
        for chunk in service.ask_stream(args.query, include_data=not args.no_data):
            if chunk.delta:
                sys.stdout.write(chunk.delta)
                sys.stdout.flush()
        print()
    else:
        resp = service.ask(args.query, include_data=not args.no_data)
        _print_response(resp, show_data=not args.no_data)


def _personal_service(settings, transport) -> PersonalTravelService:
    if not settings.union_id:
        raise TripNowError("该命令需要 union_id，请用 --union-id 或设置 TRIPNOW_UNION_ID")
    return PersonalTravelService(transport, settings.union_id, model=settings.model)


def _cmd_me(args, settings, transport) -> None:
    resp = _personal_service(settings, transport).ask(
        args.query, include_data=not args.no_data
    )
    _print_response(resp, show_data=not args.no_data)


def _cmd_trips(args, settings, transport) -> None:
    resp = _personal_service(settings, transport).my_trips()
    _print_response(resp, show_data=not args.no_data)


def _cmd_subscribe(args, settings, transport) -> None:
    resp = _personal_service(settings, transport).subscribe(args.query)
    _print_response(resp, show_data=not args.no_data)


def _cmd_prompts(args, settings, transport) -> None:
    if not isinstance(transport, PromptsCapable):
        raise UnsupportedFeatureError("prompts 管理仅 mcp 传输支持，请加 --transport mcp")
    if args.action == "get":
        result = transport.get_prompts()
    else:
        result = transport.update_prompts(json.loads(args.prompts_json))
    print(json.dumps(result, ensure_ascii=False, indent=2))


_EPILOG = """\
命令一览：
  ask         公开信息查询（火车票/机票/余票/航班动态/车站大屏等，无需 union_id）
  me          个人信息提问（结合该用户票务/关注行程作答，需 union_id）
  trips       查询我的行程（me 的快捷封装）
  subscribe   订阅/关注车次或航班（需 union_id）
  prompts     管理 agent 意图 prompts（仅 mcp 传输支持）

示例：
  python main.py ask "查询明天北京到上海的火车票"
  python main.py ask "查询明天北京到上海的机票" --stream        # 流式，仅 openapi
  python main.py ask "CZ3427航班今天的预计到达时间" --no-data    # 只要自然语言
  python main.py me "查一下我的行程有没有更新状态" --union-id <id>
  python main.py trips --union-id <id>
  python main.py subscribe "关注今天D7561次广州到深圳北的一等座" --union-id <id>
  python main.py --transport mcp prompts get
  python main.py --transport mcp prompts set '[{"scenario":1,"prompt":"..."}]'

全局参数对所有子命令生效，须写在子命令【之前】：
  python main.py --transport mcp --env prod ask "..."

身份 union_id 的来源：OAuth 登录后的重定向 URL，可用 tripnow_client.extract_union_id 解析；
也可写进 .env 的 TRIPNOW_UNION_ID，命令行 --union-id 优先级更高。
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tripnow",
        description="TripNow Engine CLI：出行助手对话补全（OpenAPI / MCP 双传输，公开 / 个人两类信息）。",
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--transport", choices=["openapi", "mcp"], metavar="{openapi,mcp}",
        help="接入方式：openapi(REST,支持流式) | mcp(JSON-RPC,支持 prompts)。默认读 .env",
    )
    parser.add_argument(
        "--env", choices=["test", "prod"], metavar="{test,prod}",
        help="环境：test 走 /test 前缀，prod 走正式域名。默认读 .env",
    )
    parser.add_argument("--model", metavar="MODEL", help="模型名，默认 tripnow-travel-pro")
    parser.add_argument("--no-data", action="store_true", help="不返回结构化数据 model_data")

    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)

    p_ask = sub.add_parser(
        "ask", help="公开信息查询（无需 union_id）",
        description="公开出行信息查询，不绑定用户身份。引擎按自然语言自行选择工具。",
    )
    p_ask.add_argument("query", metavar="QUERY", help="自然语言提问，如 \"明天北京到上海的火车票\"")
    p_ask.add_argument("--stream", action="store_true", help="流式输出（仅 openapi，mcp 会报错）")
    p_ask.set_defaults(func=_cmd_ask)

    p_me = sub.add_parser(
        "me", help="个人信息提问（需 union_id）",
        description="携带 union_id 提问，引擎结合该用户的票务/关注行程作答。",
    )
    p_me.add_argument("query", metavar="QUERY", help="自然语言提问")
    p_me.add_argument("--union-id", dest="union_id", metavar="ID", help="用户身份，缺省读 TRIPNOW_UNION_ID")
    p_me.set_defaults(func=_cmd_me)

    p_trips = sub.add_parser(
        "trips", help="查询我的行程",
        description="me 命令的快捷封装，固定查询当前用户行程状态。",
    )
    p_trips.add_argument("--union-id", dest="union_id", metavar="ID", help="用户身份，缺省读 TRIPNOW_UNION_ID")
    p_trips.set_defaults(func=_cmd_trips)

    p_sub = sub.add_parser(
        "subscribe", help="订阅/关注车次或航班",
        description="为当前用户订阅/关注指定车次或航班（个人写操作）。",
    )
    p_sub.add_argument("query", metavar="QUERY", help='如 "关注今天D7561次广州到深圳北的一等座"')
    p_sub.add_argument("--union-id", dest="union_id", metavar="ID", help="用户身份，缺省读 TRIPNOW_UNION_ID")
    p_sub.set_defaults(func=_cmd_subscribe)

    p_prompts = sub.add_parser(
        "prompts", help="管理 agent prompts（仅 mcp）",
        description="读取/覆盖当前账户 channel 下的意图 prompts。需 --transport mcp。",
    )
    p_prompts.add_argument("action", choices=["get", "set"], help="get 读取；set 覆盖")
    p_prompts.add_argument("prompts_json", nargs="?", metavar="JSON", help="set 时传入 prompts JSON 数组")
    p_prompts.set_defaults(func=_cmd_prompts)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        settings = _build_settings(args)
        transport = build_transport(settings)
        try:
            args.func(args, settings, transport)
        finally:
            transport.close()
    except TripNowError as e:
        print(f"错误: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
