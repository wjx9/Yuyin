"""P1 mock MCP server：一个可热插拔的第三方技能模拟。

用法（仓库根）：
    .venv\\Scripts\\python server_py\\mcp_skill\\mock_server.py
监听 http://127.0.0.1:9100/mcp（streamable-http 端点）。

P4.3 麦当劳式 MCP 接入（2026-08-28）：加 `--require-auth` 模式，模拟官方 MCP
「所有请求都要 `Authorization: Bearer <token>`（连 initialize 握手都要）」——
用自写 ASGI 中间件包住 streamable-http app，Token 不符一律 401。用于在本地
复现「probe 需带临时 Token / 用户需配 Token」的完整链路，无需真实麦当劳账号。

    .venv\\Scripts\\python server_py\\mcp_skill\\mock_server.py --require-auth [--token xxx]

mcp 版本：2.1.1。注意 FastMCP 在 2.x 已改名 MCPServer（见
https://py.sdk.modelcontextprotocol.io/v2/migration/）。
"""

import argparse
import json

from mcp.server.mcpserver import MCPServer, Context

mcp = MCPServer("weather-mock")

# P4.2 演示凭证（与商店 seed / 管理员上架的 byok 技能保持一致；真实场景换平台服务）
_MOCK_API_KEY = "mock-secret-key-123"
# P4.3 --require-auth 模式接受的全请求 Token（模拟麦当劳开放平台发的 MCP Token）
_MOCK_MCP_TOKEN = "mock-mcd-token-123"


class _BearerGate:
    """ASGI 中间件：所有请求必须带 `Authorization: Bearer <token>`，否则 401。

    模拟麦当劳式 MCP：连 initialize 握手都要鉴权。POC 用自写中间件——SDK 自带的
    RequireAuthMiddleware 是 OAuth 专用（要 TokenVerifier），不适合固定 Token 场景。
    """

    def __init__(self, app, expected: bytes):
        self.app = app
        self.expected = b"Bearer " + expected

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        auth = None
        for k, v in scope.get("headers") or []:
            if k.lower() == b"authorization":
                auth = v
                break
        if auth != self.expected:
            body = json.dumps(
                {"error": "invalid_token", "error_description": "缺少或无效的 MCP Token"}
            ).encode()
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"www-authenticate", b'Bearer error="invalid_token"'),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)


@mcp.tool()
def get_weather(city: str, days: int = 1) -> str:
    """查询指定城市未来几天的天气情况。

    Args:
        city: 城市名，如 深圳。
        days: 未来几天，默认 1。
    """
    return f"{city} 未来{days}天：多云转晴，27~32℃（mock 数据）"


@mcp.tool()
def get_region_forecast(city: str, ctx: Context) -> str:
    """查询指定区域的天气（需携带区域凭证，P4.3 动态凭证演示工具）。

    MCPServer 2.x 把 `Context` 注入工具：`ctx.headers` 读本次请求头——
    client 侧注入的 Authorization 头能在这里被验证到（完整方案 §7 注入链路闭环）。

    Args:
        city: 城市名，如 深圳。
    """
    headers = ctx.headers or {}
    auth = headers.get("authorization", "")
    if _MOCK_API_KEY not in auth:
        return "缺少凭证：请先在技能商店配置本技能的凭证（api_key）"
    return f"{city} 区域天气：晴，25~30℃（已鉴权，mock 数据）"


@mcp.tool()
def query_nearby_stores(address: str) -> str:
    """查询指定地址附近的麦当劳门店（P4.3 麦当劳式 MCP 演示工具）。

    模拟麦当劳 MCP 的读操作 query-nearby-stores。在 `--require-auth` 模式下
    整个服务（含本工具）都被 ASGI 网关要求 `Authorization: Bearer <token>`，
    客户端注入的凭证过网关后工具即可正常返回。

    Args:
        address: 地址，如 深圳南山。
    """
    return (
        f"{address} 附近的麦当劳门店（mock）：\n"
        "- 科技园店（深圳市南山区科苑路15号）距离 300m，营业中\n"
        "- 万象天地店（南山区深南大道9668号）距离 800m，营业中\n"
        "- 海岸城店（南山区文心五路33号）距离 1.2km，营业中"
    )


@mcp.tool()
def get_stock(symbol: str) -> str:
    """查询指定股票代码的最新行情（P2 seed 的第二个演示技能）。

    Args:
        symbol: 股票代码，如 600519。
    """
    return f"{symbol} 最新价 152.30，涨跌 +2.15%（mock 数据）"


@mcp.tool()
def translate_text(text: str, target_lang: str = "en") -> str:
    """把指定文本翻译成目标语言（管理员验收流：管理员自助 probe+发布 的演示技能）。

    Args:
        text: 待翻译的文本。
        target_lang: 目标语言代码，如 en/ja/zh，默认 en。
    """
    langs = {"en": "English", "ja": "Japanese", "zh": "Chinese"}
    name = langs.get(target_lang, target_lang)
    return f"「{text}」{name}翻译：mock 结果"


def _main() -> None:
    parser = argparse.ArgumentParser(description="mock MCP server（streamable-http :9100）")
    parser.add_argument(
        "--require-auth",
        action="store_true",
        help="模拟麦当劳式全请求鉴权：所有请求（含 initialize）都要 Authorization: Bearer <token>",
    )
    parser.add_argument(
        "--token",
        default=_MOCK_MCP_TOKEN,
        help=f"--require-auth 模式接受的 Token（默认 {_MOCK_MCP_TOKEN}）",
    )
    args = parser.parse_args()

    if not args.require_auth:
        mcp.run(
            transport="streamable-http",
            host="127.0.0.1",
            port=9100,
            streamable_http_path="/mcp",
        )
        return

    import uvicorn

    app = mcp.streamable_http_app(streamable_http_path="/mcp", host="127.0.0.1")
    gated = _BearerGate(app, expected=args.token.encode())
    uvicorn.run(gated, host="127.0.0.1", port=9100)


if __name__ == "__main__":
    _main()
