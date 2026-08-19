"""高德天气业务：城市名 -> 行政区划码 -> 实时天气或天气预报。"""

from __future__ import annotations

from .errors import AmapError
from .geocode_service import GeoCodeService
from .models import WeatherDay, WeatherForecast, WeatherLive
from .rest_client import AmapRestClient


def _string_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


class AmapWeatherService:
    def __init__(self, client: AmapRestClient, geocode_service: GeoCodeService):
        self._client = client
        self._geocode_service = geocode_service

    def _adcode_for(self, city: str) -> str:
        point = self._geocode_service.geocode(city, city=city)
        if not point.adcode:
            raise AmapError(f"无法确定城市行政区划码：{city}")
        return point.adcode

    def live(self, city: str) -> WeatherLive:
        data = self._client.weather_live(city=self._adcode_for(city))
        lives = data.get("lives") or []
        if not lives or not isinstance(lives[0], dict):
            raise AmapError(f"未查询到实时天气：{city}")

        item = lives[0]
        weather = _string_or_none(item.get("weather"))
        temperature = _string_or_none(item.get("temperature"))
        if not weather or not temperature:
            raise AmapError("高德返回的实时天气数据不完整")

        return WeatherLive(
            city=_string_or_none(item.get("city")) or city,
            weather=weather,
            temperature=temperature,
            winddirection=_string_or_none(item.get("winddirection")),
            windpower=_string_or_none(item.get("windpower")),
            humidity=_string_or_none(item.get("humidity")),
            reporttime=_string_or_none(item.get("reporttime")),
        )

    def forecast(self, city: str) -> WeatherForecast:
        data = self._client.weather_forecast(city=self._adcode_for(city))
        forecasts = data.get("forecasts") or []
        if not forecasts or not isinstance(forecasts[0], dict):
            raise AmapError(f"未查询到天气预报：{city}")

        item = forecasts[0]
        days: list[WeatherDay] = []

        for cast in item.get("casts") or []:
            if not isinstance(cast, dict):
                continue
            date = _string_or_none(cast.get("date"))
            day_weather = _string_or_none(cast.get("dayweather"))
            night_weather = _string_or_none(cast.get("nightweather"))
            day_temp = _string_or_none(cast.get("daytemp"))
            night_temp = _string_or_none(cast.get("nighttemp"))

            if not all((date, day_weather, night_weather, day_temp, night_temp)):
                continue

            days.append(
                WeatherDay(
                    date=date,
                    day_weather=day_weather,
                    night_weather=night_weather,
                    day_temp=day_temp,
                    night_temp=night_temp,
                    day_wind=_string_or_none(cast.get("daywind")),
                    night_wind=_string_or_none(cast.get("nightwind")),
                    day_power=_string_or_none(cast.get("daypower")),
                    night_power=_string_or_none(cast.get("nightpower")),
                )
            )

        if not days:
            raise AmapError("高德返回的天气预报数据不完整")

        return WeatherForecast(
            city=_string_or_none(item.get("city")) or city,
            reporttime=_string_or_none(item.get("reporttime")),
            days=days,
        )