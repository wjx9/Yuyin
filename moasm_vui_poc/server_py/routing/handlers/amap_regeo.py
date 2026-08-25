"""当前位置逆地理编码 Handler。"""

from __future__ import annotations

from amap_client.errors import AmapError
from amap_client.regeo_service import RegeoService

from ..handler import Handler, RouteContext, RouteResult


class AmapRegeoHandler(Handler):
    intent = "amap_regeo"
    description = "查询用户当前所在位置或当前位置地址，例如“我现在在哪”“这里是什么地方”。"

    def __init__(self, service: RegeoService, default_location: str):
        self._service = service
        self._default_location = default_location

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        location = context.location or self._default_location
        location_source = context.metadata.get("location_source", "unknown")
        import logging
        logging.getLogger("routing.handlers.amap_regeo").info(
            "当前位置输入：source=%s，location=%s", location_source, location
        )
        try:
            point = self._service.reverse_geocode(location)
        except AmapError as error:
            return RouteResult(text=f"当前位置查询失败：{error}", intent=self.intent)

        text = f"你当前的位置是：{point.formatted_address}"
        if point.adcode:
            text += f"；行政区划码：{point.adcode}"
        return RouteResult(
            text=text,
            data=point,
            intent=self.intent,
            source="高德 Web 服务 API",
            method=f"{location_source} 坐标 -> 高德逆地理编码",
        )
