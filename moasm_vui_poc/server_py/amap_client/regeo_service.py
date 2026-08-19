"""高德逆地理编码业务：经纬度 -> 当前地址、城市和行政区划码。"""

from __future__ import annotations

from .errors import AmapError
from .models import GeoPoint
from .rest_client import AmapRestClient


def _string_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


class RegeoService:
    def __init__(self, client: AmapRestClient):
        self._client = client

    def reverse_geocode(self, location: str) -> GeoPoint:
        data = self._client.regeo(location=location)
        item = data.get("regeocode")
        if not isinstance(item, dict):
            raise AmapError("高德未返回当前位置地址")

        component = item.get("addressComponent")
        if not isinstance(component, dict):
            component = {}
        formatted_address = _string_or_none(item.get("formatted_address"))
        if not formatted_address:
            raise AmapError("高德未返回当前位置的格式化地址")

        city = _string_or_none(component.get("city"))
        if not city:
            city = _string_or_none(component.get("province"))

        return GeoPoint(
            formatted_address=formatted_address,
            location=location,
            adcode=_string_or_none(component.get("adcode")),
            city=city,
        )
