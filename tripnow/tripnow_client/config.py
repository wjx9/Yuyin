"""配置与传输工厂。

端点由 host + 环境前缀 + 路径拼成，新增环境/路径只改这里。
build_transport() 是唯一决定"走 OpenAPI 还是 MCP"的地方，业务层不感知。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import ConfigError
from .transport import McpClient, OpenApiClient, TripNowTransport

try:  # .env 可选加载，没装 python-dotenv 也能用环境变量
    from dotenv import load_dotenv

    # override=True：本地 .env 优先级高于系统环境变量（后者仅作兜底），
    # 避免系统里残留的旧 key 把 .env 里的新 key 盖住。
    load_dotenv(override=True)
except ImportError:
    pass

_HOST = "https://tripnowengine.133.cn"
_TEST_PREFIX = "/test"
_PATH_OPENAPI = "/tripnow/v1/chat/completions"
_PATH_MCP = "/tripnow/v1/mcp"


@dataclass
class Settings:
    api_key: str
    transport: str = "openapi"  # openapi | mcp
    env: str = "test"  # test | prod
    model: str = "tripnow-travel-pro"
    union_id: str | None = None

    @classmethod
    def from_env(cls) -> "Settings":
        api_key = os.getenv("TRIPNOW_API_KEY", "").strip()
        if not api_key:
            raise ConfigError("缺少 TRIPNOW_API_KEY，请在 .env 或环境变量中配置")
        return cls(
            api_key=api_key,
            transport=os.getenv("TRIPNOW_TRANSPORT", "openapi").strip().lower(),
            env=os.getenv("TRIPNOW_ENV", "test").strip().lower(),
            model=os.getenv("TRIPNOW_MODEL", "tripnow-travel-pro").strip(),
            union_id=(os.getenv("TRIPNOW_UNION_ID", "").strip() or None),
        )

    def _prefix(self) -> str:
        return _TEST_PREFIX if self.env == "test" else ""

    @property
    def openapi_url(self) -> str:
        return f"{_HOST}{self._prefix()}{_PATH_OPENAPI}"

    @property
    def mcp_url(self) -> str:
        return f"{_HOST}{self._prefix()}{_PATH_MCP}"


def build_transport(settings: Settings) -> TripNowTransport:
    """根据配置创建传输实现。这是接入方式可插拔的唯一开关。"""
    if settings.transport == "mcp":
        return McpClient(settings.mcp_url, settings.api_key)
    if settings.transport == "openapi":
        return OpenApiClient(settings.openapi_url, settings.api_key)
    raise ConfigError(f"未知 transport: {settings.transport}（仅支持 openapi/mcp）")
