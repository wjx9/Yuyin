"""高德 Web 服务 REST 客户端（restapi.amap.com）。

与 A2A 智能体面（client.py）完全独立：这里直接调结构化的 REST 接口，
返回标准 JSON，自己解析，不依赖云端 agent 的黑盒编排。

当前覆盖 POI 检索两种形态（够用即可，按需再加路径规划/地理编码等）：
    - around：周边搜索（带经纬度）  /v3/place/around
    - text  ：关键字搜索（带城市）  /v3/place/text
鉴权沿用同一把 AMAP_KEY（作为 query 参数 key 传入）。
extensions=all 才会返回评分/营业时间等 biz_ext 富字段。
"""

from __future__ import annotations

from typing import Any

import requests

from .errors import AmapError

_HOST = "https://restapi.amap.com"
_BASE = f"{_HOST}/v3/place"
_TIMEOUT = (10, 30)


class AmapRestClient:
    def __init__(self, key: str, session: requests.Session | None = None):
        self._key = key
        self._session = session or requests.Session()

    def around(
        self,
        *,
        location: str,
        keywords: str = "",
        types: str = "",
        radius: int = 3000,
        sortrule: str = "weight",
        offset: int = 10,
        page: int = 1,
    ) -> dict[str, Any]:
        """周边搜索：location="经度,纬度"。keywords/types 至少给一个才有意义。"""
        return self._get(
            "around",
            {
                "location": location,
                "keywords": keywords,
                "types": types,
                "radius": radius,
                "sortrule": sortrule,
                "offset": offset,
                "page": page,
            },
        )

    def text(
        self,
        *,
        keywords: str,
        city: str = "",
        types: str = "",
        offset: int = 10,
        page: int = 1,
    ) -> dict[str, Any]:
        """关键字搜索：无位置时使用。"""
        return self._get(
            "text",
            {
                "keywords": keywords,
                "city": city,
                "types": types,
                "offset": offset,
                "page": page,
            },
        )

    def geocode(self, *, address: str, city: str = "") -> dict[str, Any]:
        """地理编码：地址/地名 -> 经纬度。"""
        return self._request(
            f"{_HOST}/v3/geocode/geo",
            {
                "address": address,
                "city": city,
            },
        )

    def weather_live(self, *, city: str) -> dict[str, Any]:
        """实时天气。city 必须是行政区划码，例如深圳为 440300。"""
        return self._request(
            f"{_HOST}/v3/weather/weatherInfo",
            {
                "city": city,
                "extensions": "base",
            },
        )

    def weather_forecast(self, *, city: str) -> dict[str, Any]:
        """天气预报。city 必须是行政区划码，例如深圳为 440300。"""
        return self._request(
            f"{_HOST}/v3/weather/weatherInfo",
            {
                "city": city,
                "extensions": "all",
            },
        )
    def driving(
        self,
        *,
        origin: str,
        destination: str,
        strategy: int = 0,
    ) -> dict[str, Any]:
        """驾车路线规划。origin/destination 格式均为“经度,纬度”。"""
        return self._request(
            f"{_HOST}/v5/direction/driving",
            {
                "origin": origin,
                "destination": destination,
                "strategy": strategy,
                "show_fields": "cost,navi",
            },
        )

    def regeo(self, *, location: str) -> dict[str, Any]:
        """逆地理编码：经纬度 -> 地址和行政区划码。"""
        return self._request(
            f"{_HOST}/v3/geocode/regeo",
            {"location": location, "extensions": "base"},
        )

    def walking(self, *, origin: str, destination: str) -> dict[str, Any]:
        """步行路线规划。origin/destination 格式均为“经度,纬度”。"""
        return self._request(
            f"{_HOST}/v5/direction/walking",
            {
                "origin": origin,
                "destination": destination,
                "show_fields": "cost,navi",
            },
        )

    def bicycling(self, *, origin: str, destination: str) -> dict[str, Any]:
        """骑行路线规划。origin/destination 格式均为“经度,纬度”。"""
        return self._request(
            f"{_HOST}/v5/direction/bicycling",
            {
                "origin": origin,
                "destination": destination,
                "show_fields": "cost,navi",
            },
        )

    def transit(
        self,
        *,
        origin: str,
        destination: str,
        city1: str,
        city2: str,
    ) -> dict[str, Any]:
        """公交/地铁路线规划。city1/city2 为起终点行政区划码。"""
        return self._request(
            f"{_HOST}/v5/direction/transit/integrated",
            {
                "origin": origin,
                "destination": destination,
                "city1": city1,
                "city2": city2,
                "show_fields": "cost,navi",
            },
        )

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        params = {**params, "extensions": "all"}
        return self._request(f"{_BASE}/{path}", params)

    def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        query = {k: v for k, v in params.items() if v not in ("", None)}
        query["key"] = self._key

        try:
            resp = self._session.get(url, params=query, timeout=_TIMEOUT)
        except requests.RequestException as e:
            raise AmapError(f"高德 REST 请求失败: {e}") from e

        if not resp.ok:
            raise AmapError(f"高德 REST 返回 {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        if str(data.get("status")) != "1":
            raise AmapError(
                f"高德 REST 错误: {data.get('info')} ({data.get('infocode')})"
            )
        return data
