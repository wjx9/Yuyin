"""高德驾车路线 Handler。"""

from __future__ import annotations

import re

from amap_client.driving_service import DrivingRouteService
from amap_client.errors import AmapError

from ..handler import Handler, RouteContext, RouteResult, SlotSpec


_FROM_TO_RE = re.compile(
    r"(?:从)?(?P<origin>.+?)(?:开车|驾车|自驾)?(?:到|去|前往)(?P<destination>.+)"
)
_TRAILING_RE = re.compile(
    r"(?:怎么走|怎么去|路线|路线规划|驾车路线|开车路线|需要多久|要多久|多远|啊|呀|呢|吗)+$"
)
_HERE_WORDS = ("我这里", "这里", "当前位置", "我当前的位置")


def _fallback_places(query: str) -> tuple[str, str]:
    """Gemini 没有槽位时，尝试解析“从 A 开车到 B”或“A 到 B 怎么走”。"""
    text = query.strip()
    text = re.sub(r"^(?:帮我|请|麻烦|查一下|查查|查询|规划一下)", "", text)
    text = _TRAILING_RE.sub("", text).strip()

    match = _FROM_TO_RE.search(text)
    if not match:
        return "", ""

    origin = match.group("origin").strip(" ，,。")
    destination = match.group("destination").strip(" ，,。")
    return origin, destination


def _format_distance(distance_m: int) -> str:
    return f"{distance_m / 1000:.1f}公里" if distance_m >= 1000 else f"{distance_m}米"


def _format_duration(duration_s: int) -> str:
    minutes = max(1, round(duration_s / 60))
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}小时{minutes}分钟" if minutes else f"{hours}小时"
    return f"{minutes}分钟"


class AmapDrivingHandler(Handler):
    intent = "amap_driving"
    description = (
        "查询驾车、自驾或开车路线规划：从一个地点开车到另一个地点的路线、距离和预计时间。"
        "例如“从深圳宝安区开车到南山科技园要多久”“杭州到上海自驾怎么走”。"
        "不处理步行、骑行、公交、高铁、航班或火车路线。"
    )
    slots = (
        SlotSpec(
            "origin",
            "string",
            "驾车出发地点，只填写地点名称，例如“深圳宝安区”“杭州西湖”；必填",
        ),
        SlotSpec(
            "destination",
            "string",
            "驾车目的地，只填写地点名称，例如“深圳南山科技园”“上海虹桥站”；必填",
        ),
        SlotSpec(
            "origin_city",
            "string",
            "出发地点所在城市，用于消除同名地点歧义；无法判断时不要填写",
        ),
        SlotSpec(
            "destination_city",
            "string",
            "目的地所在城市，用于消除同名地点歧义；无法判断时不要填写",
        ),
    )

    def __init__(self, service: DrivingRouteService, default_location: str = ""):
        self._service = service
        self._default_location = default_location

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        fallback_origin, fallback_destination = _fallback_places(query)

        origin = context.slots.get("origin") or fallback_origin
        destination = context.slots.get("destination") or fallback_destination
        origin_city = context.slots.get("origin_city") or ""
        destination_city = context.slots.get("destination_city") or ""

        origin_location = (context.location or self._default_location) if origin in _HERE_WORDS else None
        if not origin or not destination:
            return RouteResult(
                text="请告诉我驾车的起点和终点，例如“从深圳宝安区开车到南山科技园”。",
                intent=self.intent,
            )

        try:
            kwargs = {"origin_city": origin_city, "destination_city": destination_city}
            if origin_location:
                kwargs["origin_location"] = origin_location
            route = self._service.plan(origin, destination, **kwargs)
        except AmapError as error:
            return RouteResult(
                text=f"驾车路线查询失败：{error}",
                intent=self.intent,
            )

        text = (
            f"从{route.origin.formatted_address}驾车到{route.destination.formatted_address}，"
            f"约{_format_distance(route.distance_m)}，"
            f"预计{_format_duration(route.duration_s)}。"
        )

        if route.tolls is not None and route.tolls > 0:
            text += f" 预计过路费{route.tolls:g}元。"

        if route.steps:
            text += "\n关键路线："
            for index, step in enumerate(route.steps[:3], start=1):
                text += f"\n{index}. {step.instruction}"

        return RouteResult(text=text, data=route, intent=self.intent)
