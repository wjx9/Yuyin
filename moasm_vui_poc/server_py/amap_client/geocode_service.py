"""高德地点解析：地址地理编码，以及路线规划使用的 POI 定位。"""

from __future__ import annotations

from .errors import AmapError
from .models import GeoPoint
from .rest_client import AmapRestClient


def _string_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _normalize_name(value: str) -> str:
    """用于比较地点/城市名称；不改变实际发送给高德的原始名称。"""
    return "".join(value.lower().split()).removesuffix("市")


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

    def resolve_place(self, place: str, *, city: str = "") -> GeoPoint:
        """为路线规划解析地点名。

        园区、学校、商场等通常是 POI 名，而不是完整门牌地址。先走带城市约束的
        POI 文本搜索，避免地理编码的模糊匹配把路线起终点定位到错误城市；POI
        无可靠结果时，仍保留地理编码对完整地址的支持。
        """
        point = self._find_poi(place, city=city)
        if point is not None:
            return point
        try:
            return self.geocode(place, city=city)
        except AmapError as error:
            raise AmapError(f"未能定位地点：{place}") from error

    def _find_poi(self, keywords: str, *, city: str) -> GeoPoint | None:
        try:
            data = self._client.text(keywords=keywords, city=city, offset=5)
        except AmapError:
            # POI 搜索是路线解析的优先路径；接口暂时不可用时再尝试地理编码。
            return None

        target_city = _normalize_name(city) if city else ""
        candidates: list[GeoPoint] = []
        for item in data.get("pois") or []:
            if not isinstance(item, dict):
                continue
            location = _string_or_none(item.get("location"))
            name = _string_or_none(item.get("name"))
            if not location or not name:
                continue

            poi_city = _string_or_none(item.get("cityname")) or _string_or_none(item.get("city"))
            # 用户明确给出城市时，不能接受没有城市信息或城市不一致的候选项。
            if target_city and (not poi_city or _normalize_name(poi_city) != target_city):
                continue
            candidates.append(
                GeoPoint(
                    formatted_address=name,
                    location=location,
                    adcode=_string_or_none(item.get("adcode")),
                    city=poi_city,
                )
            )

        if not candidates:
            return None
        target_name = _normalize_name(keywords)
        return next(
            (point for point in candidates if _normalize_name(point.formatted_address) == target_name),
            candidates[0],
        )
