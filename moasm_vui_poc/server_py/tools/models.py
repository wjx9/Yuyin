from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from routing.handler import SlotSpec


@dataclass(frozen=True)
class ToolSpec:
    """统一工具声明；由 LangGraph 读取，不关心底层协议。"""

    name: str
    description: str
    slots: tuple[SlotSpec, ...] = ()
    keywords: tuple[str, ...] = ()
    transport: str = "handler"  # handler/http/mcp/local
    platform: str = "both"

    @property
    def id(self) -> str:
        """兼容现有 IntentSpec.id，便于渐进迁移 Planner。"""
        return self.name


@dataclass
class ToolResult:
    """统一工具结果；当前兼容旧 RouteResult 的字段。"""

    success: bool
    tool_name: str
    text: str
    data: Any | None = None
    source: str = ""
    error: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
