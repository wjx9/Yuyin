"""管理员工具发现（豆包「连接器」式）：填 MCP server 地址 → list_tools 发现可用工具。

POC 只支持 HTTP/SSE 远程 MCP（用户已拍板）；transport 校验在 main.py 入口做。

mcp 版本：2.1.1。注意 2.x API：`streamable_http_client` / `ClientSession`；
`ClientSession.list_tools()` 返回 `ListToolsResult.tools`，其中 Tool 是 pydantic 模型，
`.name/.description/.input_schema`（input_schema 为 plain dict）。

P4.3 麦当劳式 MCP 接入（2026-08-28）：很多官方 MCP（如麦当劳 https://mcp.mcd.cn）
**所有请求都要 `Authorization: Bearer <token>`，包括 initialize 握手**，且 403 返回
非标准 JSON、地址填错会连到 HTML 管理网页。所以 probe 拆两步：
  ① 预检：裸 HTTP 发一个 initialize 握手，拿真实 HTTP 状态码/Content-Type，
     把「鉴权失败 / 填了网页 / 404 / 405 / 限流」映射成面向管理员的中文提示；
  ② 正式：带 probe_headers 的完整 MCP 会话（initialize + list_tools）。
probe 的临时 Token 只在这一次请求里用，不入库、不进 manifest。
"""

from __future__ import annotations

import asyncio
import logging

_log = logging.getLogger("skill_store.probe")


class ProbeError(RuntimeError):
    """probe 失败（连接、超时、协议不满足），消息面向管理员。"""


# 麦当劳等官方 MCP 的握手请求体（probe 预检用，只取 HTTP 状态码，不解析响应体）。
_HANDSHAKE_BODY = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",  # 麦当劳支持 2025-06-18 及之前
        "capabilities": {},
        "clientInfo": {"name": "skill-store-probe", "version": "1.0"},
    },
}


async def _preflight(url: str, headers: dict[str, str] | None, timeout: float) -> None:
    """预检：裸 HTTP 握手，把常见失败（鉴权/HTML 页/404/405/429/超时）映射成中文提示。

    2xx 即通过（不解析 body——streamable-http 的响应可能是 SSE 流）。
    例外：2xx 但 Content-Type 是 text/html → 基本是填了管理网页。
    """
    from mcp.shared._httpx_utils import create_mcp_http_client

    async with create_mcp_http_client(headers=headers) as client:
        try:
            resp = await asyncio.wait_for(
                client.post(
                    url,
                    json=_HANDSHAKE_BODY,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                ),
                timeout=timeout,
            )
        except TimeoutError:
            raise ProbeError(f"连接 {url} 超时（>{timeout}s），请确认 MCP server 可达") from None
        except Exception as e:
            raise ProbeError(
                f"连接 {url} 失败：{type(e).__name__}（请确认地址可达且支持 streamable-http）"
            ) from e
    st = resp.status_code
    ct = resp.headers.get("content-type", "")
    if st in (200, 202):
        if "text/html" in ct:
            raise ProbeError(
                f"该地址返回的是网页（HTTP {st}，{ct}），不是 MCP 服务——"
                "可能是管理网页，请填真正的 MCP endpoint（如 https://mcp.mcd.cn）"
            )
        return
    if st in (401, 403):
        raise ProbeError(
            f"鉴权失败（HTTP {st}）：临时 Token 缺失或无效。"
            "麦当劳类 MCP 需先到其开放平台控制台激活获取 Token，再粘贴到「临时 Token」"
        )
    if st == 404:
        raise ProbeError(f"地址不存在（HTTP 404）：{url}")
    if st == 405:
        raise ProbeError(f"该地址不是 MCP endpoint（HTTP 405）：不接受 MCP 握手请求")
    if st == 429:
        raise ProbeError("请求过频（HTTP 429 限流），请稍后再试")
    raise ProbeError(f"连接 {url} 失败：HTTP {st}（content-type: {ct or '无'}）")


def _describe_error(url: str, exc: BaseException, timeout: float) -> str:
    """把 MCP 会话阶段的异常转成面向管理员的提示。

    优先用叶子异常里的 MCPError（.code/.message）；ExceptionGroup 递归展开；
    最终兜底给类型名 + 摘要。
    """
    leaves: list[BaseException] = []

    def _walk(e: BaseException) -> None:
        if isinstance(e, BaseExceptionGroup):
            for sub in e.exceptions:
                _walk(sub)
        else:
            leaves.append(e)

    _walk(exc)
    for leaf in leaves:
        code = getattr(leaf, "code", None)
        msg = getattr(leaf, "message", None)
        if code is not None and msg:
            return f"连接 {url} 握手失败：{msg}（MCP code {code}）"
    first = leaves[0] if leaves else exc
    detail = str(first) or type(first).__name__
    return f"连接 {url} 失败：{type(exc).__name__}：{detail[:120]}"


def list_tools(url: str, timeout: float = 30.0, headers: dict[str, str] | None = None) -> list[dict]:
    """一次性连接 MCP server，list_tools 发现工具。

    headers：probe 用的临时请求头（如 {"Authorization": "Bearer <临时Token>"}），
    仅本次发现用；为空则按无鉴权处理。超时默认 30s——实测真实麦当劳 MCP 的
    list_tools（30 个工具枚举）要 ~18s，10s 会误杀；无鉴权 mock 则毫秒级返回。

    返回 [{"name", "description", "input_schema"}]（input_schema 是 JSON Schema dict）；
    任何失败抛 ProbeError。用 asyncio.run + wait_for：独立事件循环、防挂死。
    """
    async def _run() -> list[dict]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        # 有请求头才用自定义 client（MCP 默认超时 30s/300s 不变）；无则走默认，零行为差异。
        http_client = create_mcp_http_client(headers=headers) if headers else None
        kwargs = {"http_client": http_client} if http_client is not None else {}
        try:
            async with streamable_http_client(url, **kwargs) as (r, w, *_):
                async with ClientSession(r, w) as session:
                    await session.initialize()
                    res = await session.list_tools()
                    return [
                        {
                            "name": t.name,
                            "description": (t.description or ""),
                            "input_schema": dict(t.input_schema or {}),
                        }
                        for t in res.tools
                    ]
        finally:
            if http_client is not None:
                await http_client.aclose()  # 自定义 client 由我们托管（streamable_http.py:677）

    try:
        # ① 预检：拿真实 HTTP 状态码，把鉴权/网页/404/限流转成中文提示
        asyncio.run(_preflight(url, headers, timeout))
        # ② 正式 MCP 会话
        return asyncio.run(asyncio.wait_for(_run(), timeout=timeout))
    except ProbeError:
        raise
    except TimeoutError:
        raise ProbeError(f"连接 {url} 超时（>{timeout}s），请确认 MCP server 可达") from None
    except Exception as e:
        raise ProbeError(_describe_error(url, e, timeout)) from e
