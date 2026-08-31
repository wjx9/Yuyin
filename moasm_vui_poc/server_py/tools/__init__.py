"""统一工具调用层。

LangGraph 只依赖 ToolRuntime；底层 Handler、HTTP、MCP 和手机动作都可以通过适配器
接入，避免编排层感知具体 provider。
"""

from .models import ToolSpec, ToolResult
from .registry import ToolRegistry
from .runtime import ToolRuntime

__all__ = ["ToolSpec", "ToolResult", "ToolRegistry", "ToolRuntime"]
