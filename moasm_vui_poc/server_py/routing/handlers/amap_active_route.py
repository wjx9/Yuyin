"""高德步行和骑行路线 Handler。"""

from __future__ import annotations

import re

from amap_client.active_route_service import ActiveRouteService
from amap_client.errors import AmapError

from ..handler import Handler, RouteContext, RouteResult, SlotSpec


_FROM_TO_RE = re.compile(
    r"(?:从)?(?P<origin>.+?)(?:步行|走路|骑行|骑车|骑自行车)?(?:到|去|前往)(?P<destination>.+)"
)
_TRAILING_RE = re.compile(r"(?:怎么走|怎么去|路线|路线规划|需要多久|要多久|多远|啊|呀|呢|吗)+$")
_HERE_WORDS = ("我这里", "这里", "当前位置", "我当前的位置")


def _fallback_places(query: str) -> tuple[str, str]:
    text = query.strip()
    text = re.sub(r"^(?:帮我|请|麻烦|查一下|查查|查询|规划一下)", "", text)
    text = _TRAILING_RE.sub("", text).strip()
    match = _FROM_TO_RE.search(text)
    if not match:
        return "", ""
    return (
        match.group("origin").strip(" ，,。"),
        match.group("destination").strip(" ，,。"),
    )


def _format_distance(distance_m: int) -> str:
    return f"{distance_m / 1000:.1f}公里" if distance_m >= 1000 else f"{distance_m}米"


def _format_duration(duration_s: int) -> str:
    minutes = max(1, round(duration_s / 60))
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}小时{minutes}分钟" if minutes else f"{hours}小时"
    return f"{minutes}分钟"


class _AmapActiveRouteHandler(Handler):
    mode_name = ""
    mode_words = ""

    slots = (
        SlotSpec("origin", "string", "出发地点，只填写地点名称；如果手机提供了当前位置且用户未说明起点，可以使用当前位置"),
        SlotSpec("destination", "string", "目的地，只填写地点名称；必填", required=True),
        SlotSpec("origin_city", "string", "出发地点所在城市；无法判断时不要填写"),
        SlotSpec("destination_city", "string", "目的地所在城市；无法判断时不要填写"),
    )

    def __init__(self, service: ActiveRouteService, default_location: str = ""):
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
                text=f"请告诉我{self.mode_name}的起点和终点，例如“从深圳宝安区{self.mode_words}到南山科技园”。",
                intent=self.intent,
            )

        try:
            kwargs = {"origin_city": origin_city, "destination_city": destination_city}
            if origin_location:
                kwargs["origin_location"] = origin_location
            route = self._service.plan(origin, destination, **kwargs)
        except AmapError as error:
            return RouteResult(
                text=f"{self.mode_name}路线查询失败：{error}",
                intent=self.intent,
                status="failed",
            )

        text = (
            f"从{route.origin.formatted_address}{self.mode_name}到{route.destination.formatted_address}，"
            f"约{_format_distance(route.distance_m)}，预计{_format_duration(route.duration_s)}。"
        )
        if route.steps:
            text += "\n关键路线："
            for index, step in enumerate(route.steps[:3], start=1):
                text += f"\n{index}. {step.instruction}"
        return RouteResult(text=text, data=route, intent=self.intent)


class AmapWalkingHandler(_AmapActiveRouteHandler):
    intent = "amap_walking"
    mode_name = "步行"
    mode_words = "步行"
    description = (
        "查询步行或走路路线规划：从一个地点步行到另一个地点的路线、距离和预计时间。"
        "例如“从深圳宝安区步行到南山科技园怎么走”。"
        "不处理驾车、骑行、公交、高铁、航班或火车路线。"
    )


class AmapBicyclingHandler(_AmapActiveRouteHandler):
    intent = "amap_bicycling"
    mode_name = "骑行"
    mode_words = "骑车"
    description = (
        "查询自行车、电动车或骑行路线规划：从一个地点骑车到另一个地点的路线、距离和预计时间。"
        "例如“从深圳宝安区骑车到南山科技园怎么走”。"
        "不处理驾车、步行、公交、高铁、航班或火车路线。"
    )
