"""高德地理编码 Handler：把地址或地名转换成经纬度。"""

from __future__ import annotations

import re

from amap_client.errors import AmapError
from amap_client.geocode_service import GeoCodeService

from ..handler import Handler, RouteContext, RouteResult, SlotSpec


_SUFFIX_RE = re.compile(
    r"(?:的)?(?:经纬度|坐标|位置坐标|坐标是多少|在哪儿|在哪里)(?:是多少|是什么|啊|呀|呢|吗)?$"
)


def _fallback_address(query: str) -> str:
    """Gemini 分类失败、没有槽位时的简单兜底。"""
    text = query.strip()
    text = re.sub(r"^(?:帮我|请|麻烦|查一下|查查|查询|搜索|定位)", "", text)
    text = _SUFFIX_RE.sub("", text).strip()
    return text or query


class AmapGeocodeHandler(Handler):
    intent = "amap_geocode"
    description = (
        "把明确的地址、地名或地标转换成经纬度坐标，例如“深圳市南山区科技园坐标是多少”；"
        "不处理附近地点搜索、实时天气或路线规划"
    )
    slots = (
        SlotSpec(
            "address",
            "string",
            "要转换为经纬度的完整地址、地名或地标，例如“深圳市南山区科技园”",
        ),
        SlotSpec(
            "city",
            "string",
            "可选的城市名，用于消除同名地点歧义，例如“深圳”；无法判断时不要填",
        ),
    )

    def __init__(self, service: GeoCodeService):
        self._service = service

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        address = context.slots.get("address") or _fallback_address(query)
        city = context.slots.get("city") or ""

        try:
            point = self._service.geocode(address, city=city)
        except AmapError as e:
            return RouteResult(text=f"地址解析失败：{e}", intent=self.intent)

        text = f"{point.formatted_address}的坐标是：{point.location}"
        if point.adcode:
            text += f"；行政区划码：{point.adcode}"

        return RouteResult(text=text, data=point, intent=self.intent)