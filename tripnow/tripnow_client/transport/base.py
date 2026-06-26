"""传输层抽象。

TripNowTransport ≈ Android 里的 Retrofit interface：业务层只依赖这个抽象，
具体走 REST(OpenApiClient) 还是 JSON-RPC(McpClient) 由工厂决定，可随时互换。

PromptsCapable 是 MCP 独有的能力（管理 agent prompts），用单独协议表达，
避免污染通用传输接口。业务层若需要可做 isinstance/能力探测。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterator, Protocol, runtime_checkable

from ..errors import UnsupportedFeatureError
from ..models import ChatChunk, ChatRequest, ChatResponse


class TripNowTransport(ABC):
    """所有接入方式的统一入口。"""

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """非流式对话调用。两种传输方式都必须实现。"""
        raise NotImplementedError

    def chat_stream(self, request: ChatRequest) -> Iterator[ChatChunk]:
        """流式对话调用。默认不支持，由支持的传输方式覆盖。"""
        raise UnsupportedFeatureError(
            f"{type(self).__name__} 不支持流式调用，请使用 chat()"
        )

    @property
    def supports_stream(self) -> bool:
        return False

    def close(self) -> None:
        """释放连接资源（如 requests.Session）。"""


@runtime_checkable
class PromptsCapable(Protocol):
    """MCP 独有：管理当前账户 channel 下的 agent prompts。"""

    def get_prompts(self) -> Any: ...

    def update_prompts(self, prompts: list[dict[str, Any]]) -> Any: ...
