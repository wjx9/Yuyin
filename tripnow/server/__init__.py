"""client-server 运行模式（在不改动现有 demo 的前提下，给 Dispatcher 套一层服务端）。

分层：
    schemas    —— 请求/响应数据契约（与传输无关）
    auth       —— 三方个人数据访问凭证的获取（当前 mock，预留接真鉴权的接口）
    session    —— 多会话历史隔离
    service    —— ChatService：框架无关的核心，复用 routing.build_dispatcher()
    http_server—— 标准库 HTTP 适配器（将来迁阿里云可替换为 FastAPI 等，core 不动）
"""

from .auth import CredentialProvider, Credentials, MockCredentialProvider
from .schemas import ChatRequest, ChatResponse
from .service import ChatService
from .session import SessionStore

__all__ = [
    "ChatRequest",
    "ChatResponse",
    "ChatService",
    "SessionStore",
    "Credentials",
    "CredentialProvider",
    "MockCredentialProvider",
]
