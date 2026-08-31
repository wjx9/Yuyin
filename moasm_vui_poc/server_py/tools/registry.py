from __future__ import annotations

from .adapters import HandlerAdapter, HttpAdapter, LocalAdapter, McpAdapter
from routing.handler import RouteResult
from .models import ToolSpec


class ToolRegistry:
    """统一工具目录：规格和实现成对注册。"""

    def __init__(self):
        self._items: dict[str, tuple[ToolSpec, object]] = {}

    def register(self, spec: ToolSpec, adapter: object) -> None:
        self._items[spec.name] = (spec, adapter)

    @classmethod
    def from_dispatcher(cls, dispatcher) -> "ToolRegistry":
        registry = cls()
        # 兼容测试桩/旧 Dispatcher：没有 Handler 暴露时，将整个 execute() 当成适配器。
        raw_specs = getattr(dispatcher, "specs", None)
        if raw_specs is None or not hasattr(dispatcher, "handler_for"):
            class _LegacyAdapter:
                def invoke(self, query, context, slots):
                    return dispatcher.execute(
                        intent=context.metadata.get("tool_name", "chitchat"),
                        query=query, context=context, slots=slots,
                    )
            for spec in dispatcher.visible_specs("pc"):
                platform = "pc" if spec.id not in dispatcher.intents_for("mobile") else "both"
                registry.register(ToolSpec(spec.id, spec.description, spec.slots, spec.keywords, platform=platform), _LegacyAdapter())
            return registry
        for spec in raw_specs:
            handler = dispatcher.handler_for(spec.id)
            if handler is None:
                continue
            # 保留旧 Handler 的执行实现，只在边界统一；MCP/本地/HTTP 的具体实现
            # 仍然由各自 Handler 内部完成，迁移期间不会改变行为。
            adapter_cls = HandlerAdapter
            if handler.__class__.__name__ == "MCPHandler":
                adapter_cls = McpAdapter
            elif handler.intent in {"calendar_create", "alarm_create", "timer_create", "reminder_create"}:
                adapter_cls = LocalAdapter
            elif handler.intent.startswith("amap") or handler.intent == "exa_search":
                adapter_cls = HttpAdapter
            registry.register(
                ToolSpec(
                    spec.id,
                    spec.description,
                    spec.slots,
                    spec.keywords,
                    transport=("mcp" if adapter_cls is McpAdapter else
                               "local" if adapter_cls is LocalAdapter else
                               "http" if adapter_cls is HttpAdapter else "handler"),
                    platform=("pc" if handler.pc_only else "both"),
                ),
                adapter_cls(handler),
            )
        return registry

    def get(self, name: str):
        return self._items.get(name)

    def specs(self, platform: str = "pc") -> list[ToolSpec]:
        result = []
        for spec, _adapter in self._items.values():
            if spec.platform != "both" and spec.platform != platform:
                continue
            result.append(spec)
        return result

    def names(self, platform: str = "pc") -> list[str]:
        return [s.name for s in self.specs(platform)]
