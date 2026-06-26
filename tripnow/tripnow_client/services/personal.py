"""个人信息业务层：所有调用都带 union_id（OAuth 获取的用户标识）。

覆盖文档场景 2.8 订阅关注(增)、2.9 个人行程查询(查)。
与公开层唯一的结构差异：注入 union_id。这使得"公开/个人"成为同一传输之上
两个并列的业务类，互不影响。
"""

from __future__ import annotations

from typing import Iterable

from ..errors import ConfigError
from ..models import ChatRequest, ChatResponse, Message, build_messages
from ..transport import TripNowTransport


class PersonalTravelService:
    def __init__(
        self,
        transport: TripNowTransport,
        union_id: str,
        model: str = "tripnow-travel-pro",
    ):
        if not union_id:
            raise ConfigError("个人信息服务需要 union_id，请先完成 OAuth 获取")
        self._transport = transport
        self._union_id = union_id
        self._model = model

    def ask(
        self,
        query: str,
        *,
        include_data: bool = True,
        history: Iterable[Message] | None = None,
    ) -> ChatResponse:
        """携带 union_id 提问，模型会结合该用户的票务/关注行程作答。"""
        req = ChatRequest(
            messages=build_messages(query, history),
            model=self._model,
            include_data=include_data,
            union_id=self._union_id,
        )
        return self._transport.chat(req)

    # 以下是对文档既有个人场景的语义封装（薄封装，仅固定常用 query）

    def my_trips(self, query: str = "查一下我的行程有没有更新状态") -> ChatResponse:
        """查（Read）：个人行程查询。"""
        return self.ask(query, include_data=True)

    def subscribe(self, query: str) -> ChatResponse:
        """增（Create）：订阅/关注，如 "关注今天D7561次广州到深圳北的一等座"。"""
        return self.ask(query, include_data=True)
