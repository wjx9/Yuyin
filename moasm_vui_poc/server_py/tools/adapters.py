from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from routing.handler import Handler, RouteContext, RouteResult


class ToolAdapter(Protocol):
    def invoke(self, query: str, context: RouteContext, slots: dict) -> RouteResult: ...


class HandlerAdapter:
    """兼容适配器：把现有 Handler 统一成 ToolRuntime 可调用的对象。"""

    def __init__(self, handler: Handler):
        self.handler = handler

    def invoke(self, query: str, context: RouteContext, slots: dict) -> RouteResult:
        return self.handler.handle(query, replace(context, slots=dict(slots)))


class HttpAdapter(HandlerAdapter):
    """HTTP API 的统一标记适配器；实际 HTTP 细节仍由现有 provider service 负责。"""


class McpAdapter(HandlerAdapter):
    """MCP 的统一标记适配器；连接复用和凭证注入由 MCPHandler/McpToolClient 负责。"""


class LocalAdapter(HandlerAdapter):
    """手机/本机动作适配器（如日历、闹钟、音乐）。"""
