"""客户端配置：服务端地址 / 鉴权 / 位置 / 会话标识。

优先级：显式传参 > 环境变量(.env) > 内置默认。与 server 侧各 key 一样从 .env 读，
缺省即用本机默认（127.0.0.1:8000），方便同机自测。
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass

try:  # .env 可选；没装 python-dotenv 也能用系统环境变量
    from dotenv import load_dotenv

    load_dotenv(override=True)
except ImportError:
    pass

# 默认深圳南山，供高德等基于位置的能力用（与 run_cases.py 一致）
_DEFAULT_LOCATION = "113.92,22.53"
_DEFAULT_SERVER = "http://127.0.0.1:8000"


@dataclass
class ClientConfig:
    server_url: str = _DEFAULT_SERVER
    auth_token: str | None = None  # 对应服务端 SERVER_AUTH_TOKEN；为空则不带鉴权头
    location: str | None = None  # "经度,纬度"
    user_id: str = "mock-user"  # 我方平台账号；服务端据此 mock 取三方凭证
    session_id: str = ""  # 客户端生成并固定，服务端据此隔离多轮历史
    timeout: float = 120.0  # 单轮可能数秒（服务端真发网络），给足超时

    def __post_init__(self) -> None:
        self.server_url = self.server_url.rstrip("/")
        if not self.session_id:
            self.session_id = uuid.uuid4().hex

    @classmethod
    def from_env(
        cls,
        *,
        server_url: str | None = None,
        auth_token: str | None = None,
        location: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> "ClientConfig":
        """显式传参缺省时回落到环境变量，再缺省回落到内置默认。"""
        return cls(
            server_url=server_url or os.getenv("SERVER_URL", "").strip() or _DEFAULT_SERVER,
            auth_token=(auth_token or os.getenv("SERVER_AUTH_TOKEN", "").strip() or None),
            location=(location or os.getenv("DEMO_LOCATION", "").strip() or _DEFAULT_LOCATION),
            user_id=(user_id or os.getenv("CLIENT_USER_ID", "").strip() or "mock-user"),
            session_id=(session_id or os.getenv("CLIENT_SESSION_ID", "").strip() or ""),
        )
