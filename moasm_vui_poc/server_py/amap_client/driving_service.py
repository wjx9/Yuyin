"""高德驾车路线业务：地址/地名 -> 坐标 -> 驾车路线。"""

from __future__ import annotations

from typing import Any

from .errors import AmapError
from .geocode_service import GeoCodeService
from .models import DrivingRoute, RouteStep
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


class DrivingRouteService:
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
    ) -> DrivingRoute:
        if origin_location and self._regeo_service:
            origin_point = self._regeo_service.reverse_geocode(origin_location)
        else:
            origin_point = self._geocode_service.resolve_place(origin, city=origin_city)
        destination_point = self._geocode_service.resolve_place(
            destination,
            city=destination_city,
        )

        data = self._client.driving(
            origin=origin_point.location,
            destination=destination_point.location,
        )

        route = data.get("route") or {}
        paths = route.get("paths") or []
        if not paths or not isinstance(paths[0], dict):
            raise AmapError(f"未找到从“{origin}”到“{destination}”的驾车路线")

        path = paths[0]
                # V5 接口在 show_fields=cost,navi 时，路线成本字段位于 path["cost"]；
        # 兼容未指定 show_fields 时的旧式扁平字段。
        cost = path.get("cost")
        if not isinstance(cost, dict):
            cost = {}

        distance_m = _int_or_none(path.get("distance"))
        if distance_m is None:
            distance_m = _int_or_none(cost.get("distance"))

        duration_s = _int_or_none(path.get("duration"))
        if duration_s is None:
            duration_s = _int_or_none(cost.get("duration"))

        if distance_m is None or duration_s is None:
            raise AmapError("高德返回的驾车路线缺少距离或预计时间")

        steps: list[RouteStep] = []
        for item in path.get("steps") or []:
            if not isinstance(item, dict):
                continue

            instruction = _string_or_none(item.get("instruction"))
            if not instruction:
                continue

            steps.append(
                RouteStep(
                    instruction=instruction,
                    distance_m=_int_or_none(item.get("distance")),
                    road_name=_string_or_none(item.get("road_name")),
                )
            )

        return DrivingRoute(
            origin=origin_point,
            destination=destination_point,
            distance_m=distance_m,
            duration_s=duration_s,
            strategy=_string_or_none(path.get("strategy")),
                        tolls=(
                _float_or_none(path.get("tolls"))
                if _float_or_none(path.get("tolls")) is not None
                else _float_or_none(cost.get("tolls"))
            ),
            toll_distance_m=(
                _int_or_none(path.get("toll_distance"))
                if _int_or_none(path.get("toll_distance")) is not None
                else _int_or_none(cost.get("toll_distance"))
            ),
            steps=steps,
        )
