"""当前位置逆地理编码 Handler。"""

from __future__ import annotations

import re

from amap_client.errors import AmapError
from amap_client.regeo_service import RegeoService

from ..handler import Handler, RouteContext, RouteResult, SlotSpec


_COORDINATE_RE = re.compile(
    r"东经\s*([+-]?\d+(?:\.\d+)?)\s*度?[^0-9+-]+"
    r"北纬\s*([+-]?\d+(?:\.\d+)?)\s*度?"
)
_PAIR_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)\s*[,，]\s*([+-]?\d+(?:\.\d+)?)")


def _normalize_location(value: object) -> str | None:
    """把常见坐标写法统一为高德要求的‘经度,纬度’。"""
    if not isinstance(value, str):
        return None
    text = value.strip()
    match = _COORDINATE_RE.search(text)
    if match:
        return f"{match.group(1)},{match.group(2)}"
    match = _PAIR_RE.search(text)
    if match:
        longitude = float(match.group(1))
        latitude = float(match.group(2))
        # 高德要求经度/纬度必须是数值；不能把“查询当前位置”之类的
        # 自然语言误当成 location 传给逆地理编码接口。
        if -180 <= longitude <= 180 and -90 <= latitude <= 90:
            return f"{match.group(1)},{match.group(2)}"
    return None


class AmapRegeoHandler(Handler):
    intent = "amap_regeo"
    description = (
        "把经纬度坐标转换为具体地址，或查询用户当前所在位置；"
        "用户提供坐标时填写 location（格式为‘经度,纬度’），"
        "例如‘120.130396,30.259242’；未提供坐标时使用手机当前位置。"
    )
    slots = (
        SlotSpec(
            "location",
            "string",
            "要查询的经纬度，格式为‘经度,纬度’；如果用户用东经/北纬表达，转换为纯数字格式",
        ),
    )

    def __init__(self, service: RegeoService, default_location: str):
        self._service = service
        self._default_location = default_location

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        slot_location = _normalize_location(context.slots.get("location"))
        request_location = _normalize_location(context.location)
        default_location = _normalize_location(self._default_location)
        if slot_location:
            location, location_source = slot_location, "user_coordinate"
        elif request_location:
            location = request_location
            location_source = context.metadata.get("location_source", "unknown")
        else:
            location, location_source = default_location, "configured_location"
        import logging
        logging.getLogger("routing.handlers.amap_regeo").info(
            "当前位置输入：source=%s，location=%s", location_source, location
        )
        if not location:
            return RouteResult(
                text="我暂时没有获取到你的位置信息，请在手机上打开定位权限后再试。",
                intent=self.intent,
                status="failed",
                source="手机 GPS",
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
