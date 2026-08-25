"""ChatService：服务端核心，框架无关。

复用现有 Dispatcher 与 LangGraph 编排入口，自身只多做三件事：
    1. 经 CredentialProvider 取该用户的三方凭证（当前 mock）；
    2. 按 session_id 取/建该会话的多轮历史，串行注入 RouteContext；
    3. 图执行完成后把这轮问答记进该会话历史。
不依赖任何 HTTP 框架——HTTP/WS 适配器只调用 handle_chat()，便于将来换框架/迁阿里云。
"""

from __future__ import annotations

import logging

from a2ui import build_a2ui

from routing import RouteContext
from orchestration import build_assistant_graph

from .auth import CredentialProvider, MockCredentialProvider
from .schemas import ChatRequest, ChatResponse
from .session import SessionStore

_log = logging.getLogger("server.service")


class ChatService:
    def __init__(
        self,
        dispatcher=None,
        composer=None,
        analyzer=None,
        decider=None,
        store: SessionStore | None = None,
        credentials: CredentialProvider | None = None,
    ):
        self._assistant = build_assistant_graph(
            dispatcher=dispatcher,
            composer=composer,
            analyzer=analyzer,
            decider=decider,
        )
        self._store = store or SessionStore()
        self._credentials = credentials or MockCredentialProvider()
        self._mock_notified: set[str] = set()  # 已打过 mock 鉴权提示的会话

    @property
    def capabilities(self) -> list[str]:
        return self.capabilities_for("pc")

    def capabilities_for(self, platform: str = "pc") -> list[str]:
        """指定端可用的能力清单（供 /health 按端过滤：移动端不含 PC-only 能力如 music_control）。"""
        return self._assistant.capabilities_for(platform)

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
            platform=req.platform,
            metadata={"location_source": req.location_source or "unknown"},
        )

        hist = self._store.get(req.session_id)
        with self._store.lock_for(req.session_id):
            context.history = hist.turns  # 本轮之前的历史
            result = self._assistant.run(req.query, context)
            hist.append(req.query, result.text)

        # 只下发可序列化的 dict 型 data（如音乐深链）；富对象（NewsResult 等）保持不下发。
        data = result.data if isinstance(result.data, dict) else None
        # A2UI 卡片只对富 UI 端（client_flutter，platform=mobile）生成；
        # 纯文本端（chat_app/client_py）不产不发，省流量也免得老客户端困惑。
        a2ui = (
            build_a2ui(result.intent, result.card_text)
            if req.platform == "mobile"
            else None
        )
        return ChatResponse(
            text=result.text, intent=result.intent, session_id=req.session_id, data=data, a2ui=a2ui
        )
