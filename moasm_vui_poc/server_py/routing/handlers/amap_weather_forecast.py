"""高德天气预报 Handler。"""

from __future__ import annotations

import re

from amap_client.errors import AmapError
from amap_client.weather_service import AmapWeatherService

from ..handler import Handler, RouteContext, RouteResult, SlotSpec


_CITY_RE = re.compile(r"([\u4e00-\u9fff]{2,10}(?:市|区|县))")
_DAYS_RE = re.compile(r"(?:未来|接下来|后)\s*(\d+)\s*天")


def _city(query: str, context: RouteContext, default_city: str) -> str:
    city = context.slots.get("city")
    if isinstance(city, str) and city.strip():
        return city.strip()

    match = _CITY_RE.search(query)
    return match.group(1) if match else default_city


def _skip_days(query: str) -> int:
    if "大后天" in query:
        return 3
    if "后天" in query:
        return 2
    if "明天" in query:
        return 1
    return 0


def _forecast_count(query: str) -> int:
    match = _DAYS_RE.search(query)
    if match:
        return min(max(int(match.group(1)), 1), 4)

    if _skip_days(query):
        return 1

    return 4


class AmapWeatherForecastHandler(Handler):
    intent = "amap_weather_forecast"
    description = (
        "查询某地未来天气预报：明天、后天、大后天、周末、下周或未来几天是否下雨、"
        "白天夜间天气和温度。例如“宝安区明天会下雨吗”“杭州未来三天天气”。"
        "用户只问当前、现在或实时天气时，不要选择此技能。"
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
            forecast = self._service.forecast(city)
        except AmapError as error:
            return RouteResult(
                text=f"天气预报查询失败：{error}",
                intent=self.intent,
                status="failed",
            )

        skip = _skip_days(query)
        # 具体日期未能解析时保留服务返回的完整窗口，避免把“周六”等口语时间
        # 错当作预报列表第一天；总结层可基于明确日期择要表达。
        selected = forecast.days[skip : skip + _forecast_count(query)]

        if not selected:
            return RouteResult(
                text=f"没有找到{city}对应日期的天气预报。",
                intent=self.intent,
                status="empty",
            )

        lines = [f"{forecast.city}天气预报："]
        for day in selected:
            lines.append(
                f"{day.date}：白天{day.day_weather} {day.day_temp}°C，"
                f"夜间{day.night_weather} {day.night_temp}°C"
            )

        if forecast.reporttime:
            lines.append(f"发布时间：{forecast.reporttime}")

        return RouteResult(
            text="\n".join(lines),
            data=forecast,
            intent=self.intent,
        )
