from __future__ import annotations

from routing.handler import RouteContext, RouteResult
from dataclasses import replace

from .registry import ToolRegistry


class ToolRuntime:
    """所有 Agent 工具调用的唯一入口。"""

    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    @classmethod
    def from_dispatcher(cls, dispatcher) -> "ToolRuntime":
        return cls(ToolRegistry.from_dispatcher(dispatcher))

    def specs(self, platform: str = "pc"):
        return self.registry.specs(platform)

    def names(self, platform: str = "pc") -> list[str]:
        return self.registry.names(platform)

    def invoke(
        self, *, tool_name: str, query: str, context: RouteContext, arguments: dict | None = None
    ) -> RouteResult:
        item = self.registry.get(tool_name)
        if item is None:
            return RouteResult(text=f"任务无法执行：系统未注册能力“{tool_name}”。", intent=tool_name, status="failed")
        spec, adapter = item
        if spec.platform not in ("both", context.platform):
            return RouteResult(text=f"任务无法执行：能力“{tool_name}”不支持当前设备。", intent=tool_name, status="blocked")
        # 适配旧 Dispatcher 时把工具名放入元数据；正常 Handler 不受影响。
        call_context = replace(
            context,
            metadata={**context.metadata, "tool_name": tool_name},
        )
        return adapter.invoke(query, call_context, arguments or {})
