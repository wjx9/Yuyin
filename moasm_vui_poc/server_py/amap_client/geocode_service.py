"""高德地理编码业务：地址/地名 -> 经纬度和行政区划码。"""

from __future__ import annotations

from .errors import AmapError
from .models import GeoPoint
from .rest_client import AmapRestClient


def _string_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


class GeoCodeService:
    def __init__(self, client: AmapRestClient):
        self._client = client

    def geocode(self, address: str, *, city: str = "") -> GeoPoint:
        data = self._client.geocode(address=address, city=city)
        geocodes = data.get("geocodes") or []

        if not geocodes or not isinstance(geocodes[0], dict):
            raise AmapError(f"未找到地址：{address}")

        item = geocodes[0]
        location = _string_or_none(item.get("location"))
        if location is None:
            raise AmapError(f"地址没有可用坐标：{address}")

        return GeoPoint(
            formatted_address=_string_or_none(item.get("formatted_address")) or address,
            location=location,
            adcode=_string_or_none(item.get("adcode")),
            city=_string_or_none(item.get("city")),
        )