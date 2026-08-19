"""高德实时天气 Handler。"""

from __future__ import annotations

import re

from amap_client.errors import AmapError
from amap_client.weather_service import AmapWeatherService

from ..handler import Handler, RouteContext, RouteResult, SlotSpec


_CITY_RE = re.compile(r"([\u4e00-\u9fff]{2,10}(?:市|区|县))")


def _city(query: str, context: RouteContext, default_city: str) -> str:
    city = context.slots.get("city")
    if isinstance(city, str) and city.strip():
        return city.strip()

    match = _CITY_RE.search(query)
    return match.group(1) if match else default_city


class AmapWeatherLiveHandler(Handler):
    intent = "amap_weather_live"
    description = (
        "查询某地当前或实时天气：现在天气、当前温度、湿度、风向风力、"
        "此刻是否下雨。例如“深圳现在天气怎么样”“宝安区气温多少”。"
        "用户询问明天、后天、周末或未来几天天气时，不要选择此技能。"
    )
    slots = (
        SlotSpec(
            "city",
            "string",
            "用户点名的城市、区或县，例如“深圳”“深圳宝安区”；未点名时不要填写",
        ),
    )

    def __init__(self, service: AmapWeatherService, default_city: str = "深圳"):
        self._service = service
        self._default_city = default_city

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        city = _city(query, context, self._default_city)

        try:
            weather = self._service.live(city)
        except AmapError as error:
            return RouteResult(
                text=f"实时天气查询失败：{error}",
                intent=self.intent,
            )

        details: list[str] = []
        if weather.humidity:
            details.append(f"湿度{weather.humidity}%")
        if weather.winddirection or weather.windpower:
            details.append(f"{weather.winddirection or ''}风{weather.windpower or ''}级")

        text = f"{weather.city}当前天气：{weather.weather}，{weather.temperature}°C"
        if details:
            text += "；" + "，".join(details)
        if weather.reporttime:
            text += f"。数据时间：{weather.reporttime}"

        return RouteResult(text=text, data=weather, intent=self.intent)