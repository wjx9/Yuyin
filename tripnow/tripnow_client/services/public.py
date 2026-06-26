"""公开信息业务层：不依赖用户身份，不带 union_id。纯查询（读）。

覆盖文档场景 2.1~2.7：火车票/余票/抢票分析/车站大屏/机票/列车动态/航班动态。
这些场景的差异只在自然语言 query，模型自行选择工具，因此对外只需 ask()。
"""

from __future__ import annotations

from typing import Iterable, Iterator

from ..models import ChatChunk, ChatRequest, ChatResponse, Message, build_messages
from ..transport import TripNowTransport


class PublicTravelService:
    def __init__(self, transport: TripNowTransport, model: str = "tripnow-travel-pro"):
        self._transport = transport
        self._model = model

    def ask(
        self,
        query: str,
        *,
        include_data: bool = True,
        history: Iterable[Message] | None = None,
    ) -> ChatResponse:
        """提问公开信息。include_data=True 时返回结构化数据(response.model_data)。"""
        req = ChatRequest(
            messages=build_messages(query, history),
            model=self._model,
            include_data=include_data,
            union_id=None,
        )
        return self._transport.chat(req)

    def ask_stream(
        self,
        query: str,
        *,
        include_data: bool = True,
        history: Iterable[Message] | None = None,
    ) -> Iterator[ChatChunk]:
        """流式提问（仅 OpenAPI 支持，MCP 会抛 UnsupportedFeatureError）。"""
        req = ChatRequest(
            messages=build_messages(query, history),
            model=self._model,
            include_data=include_data,
            union_id=None,
        )
        return self._transport.chat_stream(req)
