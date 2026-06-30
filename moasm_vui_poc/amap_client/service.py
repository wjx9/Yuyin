"""高德 业务层：自然语言地图查询（周边/路线/景点等）。

对上层只暴露一个接口 MapService.ask()，把"用哪个高德能力"封装在实现内部。
目前有两种后端实现，可经 config 切换（默认 rest）：
    - A2aMapService：调高德 ai_native 智能体（A2A/JSON-RPC），由云端 agent 自己
      做工具/场景路由（POI 检索、路径规划、天气……）。保留作对比。
    - RestMapService：直接调高德 Web 服务 REST API（见 rest_service.py），
      结构化、可控，是当前默认实现。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .client import AmapClient
from .models import MapResult, build_message


class MapService(ABC):
    """地图查询业务接口：自然语言进，MapResult 出。"""

    @abstractmethod
    def ask(self, query: str, *, location: str | None = None) -> MapResult:
        raise NotImplementedError


class A2aMapService(MapService):
    """旧实现：调高德 ai_native 智能体（A2A）。保留以便与 REST 实现对比。"""

    def __init__(self, client: AmapClient, default_location: str | None = None):
        self._client = client
        # agent 必须拿到 user_loc 才会检索；无显式位置时退回默认位置（见 config）。
        self._default_location = default_location

    def ask(self, query: str, *, location: str | None = None) -> MapResult:
        message = build_message(query, location=location or self._default_location)
        return self._client.send(message)
