"""高德步行和骑行路线业务：地址/地名 -> 坐标 -> 路线。"""

from __future__ import annotations

from typing import Any, Callable

from .errors import AmapError
from .geocode_service import GeoCodeService
from .models import ActiveRoute, RouteStep
from .regeo_service import RegeoService
from .rest_client import AmapRestClient


def _string_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _int_or_none(value: object) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


class ActiveRouteService:
    """步行/骑行共享实现；mode 仅决定调用哪个 REST 方法。"""

    def __init__(
        self,
        client: AmapRestClient,
        geocode_service: GeoCodeService,
        regeo_service: RegeoService | None = None,
        *,
        mode: str,
    ):
        if mode not in ("walking", "bicycling"):
            raise ValueError(f"不支持的出行方式：{mode}")
        self._client = client
        self._geocode_service = geocode_service
        self._regeo_service = regeo_service
        self._mode = mode

    def plan(
        self,
        origin: str,
        destination: str,
        *,
        origin_city: str = "",
        destination_city: str = "",
        origin_location: str | None = None,
    ) -> ActiveRoute:
        if origin_location and self._regeo_service:
            origin_point = self._regeo_service.reverse_geocode(origin_location)
        else:
            origin_point = self._geocode_service.resolve_place(origin, city=origin_city)
        destination_point = self._geocode_service.resolve_place(destination, city=destination_city)

        request: Callable[..., dict[str, Any]] = getattr(self._client, self._mode)
        data = request(origin=origin_point.location, destination=destination_point.location)

        route = data.get("route") or {}
        paths = route.get("paths") or []
        if not paths or not isinstance(paths[0], dict):
            raise AmapError(f"未找到从“{origin}”到“{destination}”的路线")

        path = paths[0]
        cost = path.get("cost") if isinstance(path.get("cost"), dict) else {}
        distance_m = _int_or_none(path.get("distance"))
        duration_s = _int_or_none(path.get("duration"))
        if distance_m is None:
            distance_m = _int_or_none(cost.get("distance"))
        if duration_s is None:
            duration_s = _int_or_none(cost.get("duration"))
        if distance_m is None or duration_s is None:
            raise AmapError("高德返回的路线缺少距离或预计时间")

        steps: list[RouteStep] = []
        for item in path.get("steps") or []:
            if not isinstance(item, dict):
                continue
            instruction = _string_or_none(item.get("instruction"))
            if instruction:
                steps.append(
                    RouteStep(
                        instruction=instruction,
                        distance_m=_int_or_none(item.get("distance")),
                        road_name=_string_or_none(item.get("road_name")),
                    )
                )

        return ActiveRoute(
            origin=origin_point,
            destination=destination_point,
            distance_m=distance_m,
            duration_s=duration_s,
            steps=steps,
        )
