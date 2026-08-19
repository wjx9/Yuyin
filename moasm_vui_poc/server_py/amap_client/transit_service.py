"""高德公交/地铁路线业务：地址/地名 -> 坐标和行政区划码 -> 换乘方案。"""

from __future__ import annotations

from typing import Any

from .errors import AmapError
from .geocode_service import GeoCodeService
from .models import TransitRoute
from .regeo_service import RegeoService
from .rest_client import AmapRestClient


def _string_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int_or_none(value: object) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _segment_summaries(segments: list[Any]) -> list[str]:
    summaries: list[str] = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        bus = segment.get("bus") if isinstance(segment.get("bus"), dict) else {}
        for line in bus.get("buslines") or []:
            if not isinstance(line, dict):
                continue
            name = _string_or_none(line.get("name"))
            departure = ((line.get("departure_stop") or {}).get("name"))
            arrival = ((line.get("arrival_stop") or {}).get("name"))
            if name:
                text = f"乘坐{name}"
                if departure and arrival:
                    text += f"（{departure}上车，{arrival}下车）"
                summaries.append(text)

        railway = segment.get("railway") if isinstance(segment.get("railway"), dict) else {}
        railway_name = _string_or_none(railway.get("name"))
        if railway_name:
            summaries.append(f"乘坐{railway_name}")
    return summaries


class TransitRouteService:
    def __init__(self, client: AmapRestClient, geocode_service: GeoCodeService, regeo_service: RegeoService | None = None):
        self._client = client
        self._geocode_service = geocode_service
        self._regeo_service = regeo_service

    def plan(
        self,
        origin: str,
        destination: str,
        *,
        origin_city: str = "",
        destination_city: str = "",
        origin_location: str | None = None,
    ) -> TransitRoute:
        if origin_location and self._regeo_service:
            origin_point = self._regeo_service.reverse_geocode(origin_location)
        else:
            origin_point = self._geocode_service.geocode(origin, city=origin_city)
        destination_point = self._geocode_service.geocode(destination, city=destination_city)
        if not origin_point.adcode or not destination_point.adcode:
            raise AmapError("公交路线缺少起点或终点的行政区划码")

        data = self._client.transit(
            origin=origin_point.location,
            destination=destination_point.location,
            city1=origin_point.adcode,
            city2=destination_point.adcode,
        )
        route = data.get("route") or {}
        transits = route.get("transits") or []
        if not transits or not isinstance(transits[0], dict):
            raise AmapError(f"未找到从“{origin}”到“{destination}”的公交路线")

        transit = transits[0]
        cost = transit.get("cost") if isinstance(transit.get("cost"), dict) else {}
        return TransitRoute(
            origin=origin_point,
            destination=destination_point,
            distance_m=_int_or_none(transit.get("distance")) or _int_or_none(cost.get("distance")),
            duration_s=_int_or_none(transit.get("duration")) or _int_or_none(cost.get("duration")),
            walking_distance_m=(
                _int_or_none(transit.get("walking_distance"))
                or _int_or_none(cost.get("walking_distance"))
            ),
            cost_yuan=_float_or_none(transit.get("cost")) or _float_or_none(cost.get("transit_fee")),
            transfers=_int_or_none(transit.get("transfers")),
            segments=_segment_summaries(transit.get("segments") or []),
        )
