"""高德配置：从环境变量读取 AMAP_KEY 及后端选择 AMAP_BACKEND。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .client import AmapClient
from .errors import AmapError
from .parser import QueryParser
from .rest_client import AmapRestClient
from .rest_service import RestMapService
from .service import A2aMapService, MapService

# ai_native agent 必须拿到 user_loc 才会真正检索（空值会回固定兜底「网络波动」）。
# 真实端有 GPS 时由 context.location 覆盖；demo/CLI 无 GPS，用此默认值兜底。
_DEFAULT_LOC = "113.93,22.57"  # 深圳南山一带

# 默认走 REST（结构化、可控）；设 AMAP_BACKEND=a2a 可切回旧的智能体实现做对比。
_DEFAULT_BACKEND = "rest"
_VALID_BACKENDS = ("rest", "a2a")


@dataclass
class AmapSettings:
    key: str
    default_location: str = _DEFAULT_LOC
    backend: str = _DEFAULT_BACKEND  # "rest"(默认) | "a2a"(旧实现，保留对比)

    @classmethod
    def from_env(cls) -> "AmapSettings":
        key = os.getenv("AMAP_KEY", "").strip()
        if not key:
            raise AmapError("缺少 AMAP_KEY 环境变量")
        backend = (os.getenv("AMAP_BACKEND", "").strip().lower() or _DEFAULT_BACKEND)
        if backend not in _VALID_BACKENDS:
            raise AmapError(f"AMAP_BACKEND 非法: {backend!r}（可选 {_VALID_BACKENDS}）")
        return cls(
            key=key,
            default_location=(os.getenv("AMAP_DEFAULT_LOC", "").strip() or _DEFAULT_LOC),
            backend=backend,
        )


def build_service(settings: AmapSettings, parser: QueryParser | None = None) -> MapService:
    """parser 仅对 REST 后端生效（把自然语言拆成关键词+地点）；a2a 后端忽略它。"""
    if settings.backend == "a2a":
        return A2aMapService(AmapClient(settings.key), default_location=settings.default_location)
    return RestMapService(
        AmapRestClient(settings.key),
        default_location=settings.default_location,
        parser=parser,
    )
