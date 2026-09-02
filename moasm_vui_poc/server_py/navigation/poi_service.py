"""POI 搜索服务：封装现有 amap_client，提供 query_poi_list 接口。

对应技术设计文档中的端侧能力接口 query_poi_list(destination)。
优先使用关键字搜索（text），无结果时退回周边搜索（around）。
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from ..amap_client.errors import AmapError
    from ..amap_client.rest_client import AmapRestClient
except ImportError:
    # 独立运行时的兜底导入
    import sys
    import os
    _sys_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _sys_path not in sys.path:
        sys.path.insert(0, _sys_path)
    from amap_client.errors import AmapError
    from amap_client.rest_client import AmapRestClient

from .models import Poi

_log = logging.getLogger("navigation.poi_service")

_DEFAULT_CITY = "深圳"
_DEFAULT_LOCATION = "114.0579,22.5431"  # 深圳
_MAX_POIS = 10  # 最多返回的 POI 数量


class PoiSearchService:
    """POI 搜索服务。"""

    def __init__(
        self,
        client: AmapRestClient,
        *,
        default_city: str = _DEFAULT_CITY,
        default_location: str = _DEFAULT_LOCATION,
        max_pois: int = _MAX_POIS,
    ):
        self._client = client
        self._default_city = default_city
        self._default_location = default_location
        self._max_pois = max_pois

    @classmethod
    def from_key(cls, key: str, **kwargs: Any) -> "PoiSearchService":
        """从高德 Key 创建服务。"""
        return cls(AmapRestClient(key), **kwargs)

    def query_poi_list(self, destination: str, *, city: str | None = None) -> list[Poi]:
        """搜索目的地对应的 POI 列表。

        Args:
            destination: 目的地关键词（如"大新"、"深圳湾公园"）
            city: 限定城市，为空用默认城市

        Returns:
            POI 列表，为空表示没搜到
        """
        destination = destination.strip()
        if not destination:
            return []

        city = city or self._default_city

        # 1. 优先关键字搜索
        try:
            data = self._client.text(
                keywords=destination,
                city=city,
                offset=self._max_pois,
            )
            pois = self._parse_pois(data.get("pois") or [])
            if pois:
                _log.info("关键字搜索命中 %d 个 POI: %s", len(pois), destination)
                return pois
        except AmapError as e:
            _log.warning("关键字搜索失败: %s", e)

        # 2. 退回周边搜索（用默认坐标）
        try:
            data = self._client.around(
                location=self._default_location,
                keywords=destination,
                radius=50000,  # 50公里范围
                offset=self._max_pois,
            )
            pois = self._parse_pois(data.get("pois") or [])
            if pois:
                _log.info("周边搜索命中 %d 个 POI: %s", len(pois), destination)
                return pois
        except AmapError as e:
            _log.warning("周边搜索失败: %s", e)

        _log.info("未搜索到 POI: %s", destination)
        return []

    @staticmethod
    def _parse_pois(items: list[Any]) -> list[Poi]:
        """从高德 REST 返回的 pois[] 解析 Poi 列表。"""
        pois: list[Poi] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            name = it.get("name")
            if not name:
                continue
            biz = it.get("biz_ext")
            if not isinstance(biz, dict):
                biz = {}
            pois.append(Poi(
                name=name,
                address=it.get("address") or None,
                location=it.get("location") or None,
                distance_m=_as_int(it.get("distance")),
                rating=_as_float(biz.get("rating")),
                raw=it,
            ))
        return pois


def _as_int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _as_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
