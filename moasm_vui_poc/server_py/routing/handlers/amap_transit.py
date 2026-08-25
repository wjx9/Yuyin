"""高德公交和地铁路线 Handler。"""

from __future__ import annotations

import re

from amap_client.errors import AmapError
from amap_client.transit_service import TransitRouteService

from ..handler import Handler, RouteContext, RouteResult, SlotSpec


_FROM_TO_RE = re.compile(r"(?:从)?(?P<origin>.+?)(?:坐公交|坐地铁|乘公交|乘地铁)?(?:到|去|前往)(?P<destination>.+)")
_TRAILING_RE = re.compile(r"(?:怎么走|怎么去|路线|路线规划|需要多久|要多久|啊|呀|呢|吗)+$")
_HERE_WORDS = ("我这里", "这里", "当前位置", "我当前的位置")


def _fallback_places(query: str) -> tuple[str, str]:
    text = _TRAILING_RE.sub("", query.strip()).strip()
    match = _FROM_TO_RE.search(text)
    if not match:
        return "", ""
    return (
        match.group("origin").strip(" ，,。"),
        match.group("destination").strip(" ，,。"),
    )


def _format_duration(duration_s: int | None) -> str | None:
    if duration_s is None:
        return None
    minutes = max(1, round(duration_s / 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours}小时{minutes}分钟" if hours and minutes else f"{hours}小时" if hours else f"{minutes}分钟"


class AmapTransitHandler(Handler):
    intent = "amap_transit"
    description = (
        "查询公交、地铁或公共交通换乘路线：从一个地点到另一个地点乘坐公交或地铁的方案、"
        "预计时间和换乘信息。例如“从深圳宝安区坐地铁到南山科技园怎么走”。"
        "不处理驾车、步行、骑行、高铁、航班或火车路线。"
    )
    slots = (
        SlotSpec("origin", "string", "公交/地铁出发地点；如果手机提供了当前位置且用户未说明起点，可以使用当前位置"),
        SlotSpec("destination", "string", "公交/地铁目的地，只填写地点名称；必填", required=True),
        SlotSpec("origin_city", "string", "出发地点所在城市；无法判断时不要填写"),
        SlotSpec("destination_city", "string", "目的地所在城市；无法判断时不要填写"),
    )

    def __init__(self, service: TransitRouteService, default_location: str = ""):
        self._service = service
        self._default_location = default_location

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        fallback_origin, fallback_destination = _fallback_places(query)
        origin = context.slots.get("origin") or fallback_origin
        destination = context.slots.get("destination") or fallback_destination
        origin_city = context.slots.get("origin_city") or ""
        destination_city = context.slots.get("destination_city") or ""
        origin_location = context.location or self._default_location
        if not origin and origin_location:
            origin = "我这里"
        if origin not in _HERE_WORDS:
            origin_location = None
        if not origin or not destination:
            return RouteResult(
                text="请告诉我公交或地铁的起点和终点，例如“从深圳宝安区坐地铁到南山科技园”。",
                intent=self.intent,
            )

        try:
            kwargs = {"origin_city": origin_city, "destination_city": destination_city}
            if origin_location:
                kwargs["origin_location"] = origin_location
            route = self._service.plan(origin, destination, **kwargs)
        except AmapError as error:
            return RouteResult(
                text=f"公交路线查询失败：{error}",
                intent=self.intent,
                status="failed",
            )

        details: list[str] = []
        duration = _format_duration(route.duration_s)
        if duration:
            details.append(f"预计{duration}")
        if route.transfers is not None:
            details.append(f"换乘{route.transfers}次")
        if route.walking_distance_m is not None:
            details.append(f"步行约{route.walking_distance_m}米")
        if route.cost_yuan is not None:
            details.append(f"票价约{route.cost_yuan:g}元")

        text = f"从{route.origin.formatted_address}前往{route.destination.formatted_address}的公交方案"
        if details:
            text += "：" + "，".join(details) + "。"
        if route.segments:
            text += "\n关键换乘："
            for index, segment in enumerate(route.segments[:3], start=1):
                text += f"\n{index}. {segment}"
        return RouteResult(text=text, data=route, intent=self.intent)
