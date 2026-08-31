"""MCPHandler：把 MCP 技能包装成现有 Handler（见 最终技术路线.md §2.3）。

分类器零改动：MCPHandler 只需 spec() 正确，意图分流就自动认识这个新技能。
失败收敛：任何异常都变成干净的 RouteResult(status="failed")，不抛给 LangGraph。
"""

from __future__ import annotations

import logging

from routing.handler import Handler, RouteContext, RouteResult, IntentSpec

from .manifest import to_slot_specs
from .client import McpToolClient, McpSkillError

_log = logging.getLogger("mcp_skill.handler")


class MCPHandler(Handler):
    def __init__(self, manifest, client: McpToolClient):
        self.intent = manifest.intent
        self.description = manifest.description
        self.slots = to_slot_specs(manifest.tools)
        self.pc_only = manifest.pc_only
        self._m, self._c = manifest, client

    def spec(self) -> IntentSpec:
        return IntentSpec(self.intent, self.description, self.slots, tuple(self._m.keywords))

    def _first_string_slot(self) -> str | None:
        return next((s.name for s in self.slots if s.type == "string"), None)

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        # 槽位缺失兜底：整句 query 喂 manifest 声明的 query_slot（缺省=首个 string 槽）。
        # 不盲传 {"query": ...}——严格 JSON Schema 的 server 会拒绝未声明参数。
        args = dict(context.slots)
        if not args:
            target = self._m.query_slot or self._first_string_slot()
            if not target:
                return RouteResult(
                    text=f"{self._m.name} 需要更具体的参数（如城市名）",
                    intent=self.intent,
                    status="failed",
                )
            args = {target: query}
        try:
            try:
                result = self._c.call_tool(
                    self._m.entry_tool,
                    args,
                    timeout=30,
                    context=context,
                    query=query,
                )
            except TypeError as e:
                # 兼容旧的/测试用 MCP client（只接受 name, arguments, timeout）。
                # 真实远程客户端已支持统一上下文参数；仅对“未知关键字”回退。
                if "unexpected keyword argument" not in str(e):
                    raise
                result = self._c.call_tool(self._m.entry_tool, args, timeout=30)
            # local transport 可以直接返回 RouteResult，从而保留结构化 data；
            # 远程 MCP 仍返回字符串，按原有逻辑处理。
            if isinstance(result, RouteResult):
                result.intent = self.intent
                result.method = result.method or "mcp"
                result.source = result.source or self._m.name
                return result
            text = result
            return RouteResult(text=text, intent=self.intent, method="mcp", source=self._m.name)
        except McpSkillError as e:  # P4.2：缺凭证给"去配置"指引，其余仍是干净失败
            msg = str(e)
            if "缺少必填凭证" in msg:
                return RouteResult(
                    text=f"需要先配置「{self._m.name}」的凭证：{msg.removeprefix('缺少必填凭证：')}",
                    intent=self.intent,
                    status="failed",
                )
            _log.warning("MCP 技能 %s 调用失败: %s", self._m.name, msg)
            return RouteResult(
                text=f"{self._m.name} 暂不可用：{msg}",
                intent=self.intent,
                status="failed",
            )
        except Exception as e:  # 收敛成干净结果，别抛给 LangGraph
            _log.warning("MCP 技能 %s 调用失败: %r", self._m.name, e)
            return RouteResult(
                text=f"{self._m.name} 暂不可用：{type(e).__name__}",
                intent=self.intent,
                status="failed",
            )
