"""ChatService：服务端核心，框架无关。

复用现有 routing.build_dispatcher()（同一个"大脑"），自身只多做三件事：
    1. 经 CredentialProvider 取该用户的三方凭证（当前 mock）；
    2. 按 session_id 取/建该会话的多轮历史，串行注入 RouteContext；
    3. dispatch 后把这轮问答记进该会话历史。
不依赖任何 HTTP 框架——HTTP/WS 适配器只调用 handle_chat()，便于将来换框架/迁阿里云。
"""

from __future__ import annotations

import logging

from routing import RouteContext, build_dispatcher

from .auth import CredentialProvider, MockCredentialProvider
from .schemas import ChatRequest, ChatResponse
from .session import SessionStore

_log = logging.getLogger("server.service")


class ChatService:
    def __init__(
        self,
        dispatcher=None,
        store: SessionStore | None = None,
        credentials: CredentialProvider | None = None,
    ):
        self._dispatcher = dispatcher or build_dispatcher()
        self._store = store or SessionStore()
        self._credentials = credentials or MockCredentialProvider()
        self._mock_notified: set[str] = set()  # 已打过 mock 鉴权提示的会话

    @property
    def capabilities(self) -> list[str]:
        return self._dispatcher.intents

    def handle_chat(self, req: ChatRequest) -> ChatResponse:
        creds = self._credentials.resolve(req.user_id)
        if creds.mocked and req.session_id not in self._mock_notified:
            self._mock_notified.add(req.session_id)
            _log.info(
                "[我们mock了鉴权过程, 假装拿到了key] user=%s session=%s", req.user_id, req.session_id
            )

        context = RouteContext(
            union_id=creds.tripnow_union_id,
            location=req.location,
            include_data=req.include_data,
        )

        hist = self._store.get(req.session_id)
        with self._store.lock_for(req.session_id):
            context.history = hist.turns  # 本轮之前的历史
            result = self._dispatcher.dispatch(req.query, context)
            hist.append(req.query, result.text)

        return ChatResponse(text=result.text, intent=result.intent, session_id=req.session_id)
