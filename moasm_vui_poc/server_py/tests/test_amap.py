"""高德 A2A provider 单测：请求构造 + 多种返回结构提取（假 session）。"""

from __future__ import annotations

import json

import pytest

from amap_client.client import AmapClient
from amap_client.errors import AmapError
from amap_client.models import build_message, parse_inner_json
from amap_client.rest_client import AmapRestClient
from amap_client.rest_service import RestMapService
from amap_client.service import A2aMapService


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload):
        self._payload = payload
        self.last_post = None

    def post(self, url, json=None, headers=None, timeout=None):
        self.last_post = {"url": url, "json": json, "headers": headers}
        return FakeResponse(self._payload)


def _result_message(text):
    return {"result": {"role": "agent", "parts": [{"type": "text", "text": text}]}}


def test_send_sets_key_header_and_jsonrpc_method():
    session = FakeSession(_result_message("附近有3家咖啡店"))
    client = AmapClient(key="AMAPKEY", session=session)
    client.send(build_message("附近咖啡", location="116.0,39.0"))

    body = session.last_post["json"]
    assert body["jsonrpc"] == "2.0"
    assert body["method"] == "message/send"
    assert session.last_post["headers"]["key"] == "AMAPKEY"
    # part.text 是 JSON 串（高德会再 JSON 解析它）：query 放诉求、location 进 user_loc
    inner = json.loads(body["params"]["message"]["parts"][0]["text"])
    assert inner["query"] == "附近咖啡"
    assert inner["user_loc"] == "116.0,39.0"
    assert "history" in inner and "device_id" in inner  # agent 需要的完整入参
    # Message/Part 必须带 kind 判别字段
    assert body["params"]["message"]["kind"] == "message"
    assert body["params"]["message"]["parts"][0]["kind"] == "text"


def test_send_hits_mcp_amap_host():
    session = FakeSession(_result_message("ok"))
    AmapClient(key="K", session=session).send(build_message("x"))
    assert session.last_post["url"] == "https://mcp.amap.com/a2a/agent/ai_native"


def test_extract_structured_pois():
    # 真正的榜单埋在 container 的 contentInfos 里，需挖出 POI 并渲染进文本
    payload = {"result": {"artifacts": [
        {"parts": [{"kind": "data", "data": {"type": "markdown", "displayText": "为您推荐川菜榜，"}}]},
        {"parts": [{"kind": "data", "data": {"type": "container", "data": {"data": {"contentInfos": [
            {"content": {"paragraphList": [{"paragraphInfoList": [
                {"pointInfo": {"name": "马旺子川小馆", "poi": {
                    "evaluation": {"rating": 4.7, "ratingDesc": "超棒"},
                    "distance": {"directDistance": 6163},
                    "address": "南山区科苑南路", "openTime": "11:30-20:30"}},
                 "attributes": {"recommendReason": [{"text": "毛血旺又麻又辣"}]}},
            ]}]}}
        ]}}}}]},
    ]}}
    session = FakeSession(payload)
    result = AmapClient(key="K", session=session).send(build_message("x"))
    assert len(result.pois) == 1
    poi = result.pois[0]
    assert poi.name == "马旺子川小馆" and poi.rating == 4.7 and poi.distance_m == 6163
    # 渲染文本里既有开场白，也有店名/评分/距离/地址/推荐语
    assert "为您推荐川菜榜" in result.text
    assert "马旺子川小馆" in result.text and "评分4.7" in result.text and "6.2km" in result.text
    assert "毛血旺又麻又辣" in result.text


def test_extract_concats_markdown_artifacts():
    # 非流式下回答被拆成多个 artifact：tips/正文markdown片段/source，需按序拼接正文
    payload = {"result": {"artifacts": [
        {"parts": [{"kind": "data", "data": {"type": "tips", "text": ""}}]},
        {"parts": [{"kind": "data", "data": {"type": "markdown", "displayText": "为您推荐川菜，"}}]},
        {"parts": [{"kind": "data", "data": {"type": "markdown", "displayText": "每家都是排队王者！"}}]},
        {"parts": [{"kind": "data", "data": {"type": "source", "text": ""}}]},
    ]}}
    session = FakeSession(payload)
    result = AmapClient(key="K", session=session).send(build_message("x"))
    assert result.text == "为您推荐川菜，每家都是排队王者！"


def test_extract_from_direct_message():
    session = FakeSession(_result_message("结果文本"))
    result = A2aMapService(AmapClient(key="K", session=session)).ask("附近")
    assert result.text == "结果文本"


def test_extract_from_task_status_message():
    payload = {"result": {"status": {"message": {"parts": [{"text": "任务内文本"}]}}}}
    session = FakeSession(payload)
    result = AmapClient(key="K", session=session).send(build_message("x"))
    assert result.text == "任务内文本"


def test_extract_from_artifacts():
    payload = {"result": {"artifacts": [{"parts": [{"text": "产物文本"}]}]}}
    session = FakeSession(payload)
    result = AmapClient(key="K", session=session).send(build_message("x"))
    assert result.text == "产物文本"


def test_error_response_raises():
    session = FakeSession({"error": {"code": -32000, "message": "bad"}})
    with pytest.raises(AmapError):
        AmapClient(key="K", session=session).send(build_message("x"))


def test_parse_inner_json():
    assert parse_inner_json('[{"a":1}]') == [{"a": 1}]
    assert parse_inner_json("普通文本") is None
    assert parse_inner_json("") is None


# ---- 高德 Web 服务 REST 后端 ----


class FakeGetSession:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self._status_code = status_code
        self.last_get = None

    def get(self, url, params=None, timeout=None):
        self.last_get = {"url": url, "params": params}
        return FakeResponse(self._payload, status_code=self._status_code)


def _rest_ok(pois):
    return {"status": "1", "info": "OK", "count": str(len(pois)), "pois": pois}


def test_rest_around_sends_key_location_and_extensions():
    session = FakeGetSession(_rest_ok([]))
    client = AmapRestClient(key="AMAPKEY", session=session)
    client.around(location="116.0,39.0", keywords="川菜")

    assert session.last_get["url"] == "https://restapi.amap.com/v3/place/around"
    params = session.last_get["params"]
    assert params["key"] == "AMAPKEY"
    assert params["location"] == "116.0,39.0"
    assert params["keywords"] == "川菜"
    assert params["extensions"] == "all"


def test_rest_drops_empty_params():
    session = FakeGetSession(_rest_ok([]))
    AmapRestClient(key="K", session=session).around(location="1,2", keywords="")
    # keywords 为空应被丢弃，不发给高德
    assert "keywords" not in session.last_get["params"]


def test_rest_status_zero_raises():
    session = FakeGetSession({"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"})
    with pytest.raises(AmapError):
        AmapRestClient(key="K", session=session).around(location="1,2", keywords="x")


def test_rest_network_error_does_not_expose_key():
    import requests

    class FailingSession:
        def get(self, url, params=None, timeout=None):
            raise requests.ConnectionError(
                "HTTPSConnectionPool(host='restapi.amap.com'): "
                "https://restapi.amap.com/v3/geocode/geo?key=SECRET_KEY"
            )

    with pytest.raises(AmapError) as error:
        AmapRestClient(key="SECRET_KEY", session=FailingSession()).geocode(address="深圳")

    assert "SECRET_KEY" not in str(error.value)
    assert "检查网络" in str(error.value)


def test_rest_service_uses_around_when_location_given():
    pois = [
        {
            "name": "马旺子川小馆",
            "address": "南山区科苑南路",
            "distance": "6163",
            "biz_ext": {"rating": "4.7", "open_time": "11:30-20:30"},
        }
    ]
    session = FakeGetSession(_rest_ok(pois))
    service = RestMapService(AmapRestClient(key="K", session=session), default_location="1,2")
    result = service.ask("川菜", location="116.0,39.0")

    assert session.last_get["url"].endswith("/place/around")
    assert session.last_get["params"]["location"] == "116.0,39.0"
    assert len(result.pois) == 1
    poi = result.pois[0]
    assert poi.name == "马旺子川小馆" and poi.rating == 4.7 and poi.distance_m == 6163
    assert "马旺子川小馆" in result.text and "评分4.7" in result.text and "6.2km" in result.text


def test_rest_service_falls_back_to_text_without_location():
    session = FakeGetSession(_rest_ok([]))
    service = RestMapService(AmapRestClient(key="K", session=session), default_location=None)
    service.ask("故宫")
    assert session.last_get["url"].endswith("/place/text")


def test_rest_handles_empty_biz_ext_list():
    # 高德在无评分数据时把 biz_ext 返回成 [] 而非 {}，不能崩
    pois = [{"name": "无名小店", "address": [], "distance": "100", "biz_ext": []}]
    session = FakeGetSession(_rest_ok(pois))
    service = RestMapService(AmapRestClient(key="K", session=session), default_location="1,2")
    result = service.ask("x")
    assert len(result.pois) == 1
    poi = result.pois[0]
    assert poi.name == "无名小店" and poi.rating is None and poi.address is None


# ---- REST + 查询解析（关键词 + 指定地点定位） ----


class MultiGetSession:
    """按 url 路径返回不同 payload；记录每次 get 的 params，支持多次调用。"""

    def __init__(self, by_path):
        self._by_path = by_path  # {"text": payload, "around": payload}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        path = url.rsplit("/", 1)[-1]
        self.calls.append({"path": path, "params": params})
        return FakeResponse(self._by_path[path])


class StubParser:
    def __init__(self, map_query):
        self._mq = map_query

    def parse(self, query):
        return self._mq


def test_rest_resolves_named_place_then_around():
    from amap_client.models import MapQuery

    session = MultiGetSession({
        "text": _rest_ok([{"name": "万科云城", "location": "113.95,22.58"}]),
        "around": _rest_ok([{"name": "云城川菜馆", "distance": "120", "biz_ext": {"rating": "4.5"}}]),
    })
    service = RestMapService(
        AmapRestClient(key="K", session=session),
        default_location="1,2",
        parser=StubParser(MapQuery(keywords="美食", near="深圳万科云城", city="深圳")),
    )
    result = service.ask("深圳万科云城附近好吃的推荐")

    # 先用 text 把地标定位成坐标，再用该坐标做 around
    assert session.calls[0]["path"] == "text"
    assert session.calls[0]["params"]["keywords"] == "深圳万科云城"
    assert session.calls[1]["path"] == "around"
    assert session.calls[1]["params"]["location"] == "113.95,22.58"
    assert session.calls[1]["params"]["keywords"] == "美食"
    assert any(p.name == "云城川菜馆" for p in result.pois)


def test_rest_named_place_unresolved_falls_back_to_default():
    from amap_client.models import MapQuery

    session = MultiGetSession({
        "text": _rest_ok([]),  # 地标没定位到
        "around": _rest_ok([{"name": "店", "distance": "10"}]),
    })
    service = RestMapService(
        AmapRestClient(key="K", session=session),
        default_location="113.93,22.57",
        parser=StubParser(MapQuery(keywords="美食", near="不存在的地标")),
    )
    service.ask("不存在的地标附近吃的")
    # 定位失败仍退回默认坐标做 around，而不是 0 结果
    assert session.calls[1]["path"] == "around"
    assert session.calls[1]["params"]["location"] == "113.93,22.57"


def test_rest_prefers_preparsed_over_parser():
    from amap_client.models import MapQuery

    session = MultiGetSession({"text": _rest_ok([{"name": "店", "location": "1,2"}])})
    service = RestMapService(
        AmapRestClient(key="K", session=session),
        parser=StubParser(MapQuery(keywords="parser不该被用到")),
    )
    service.ask("来点咖啡", preparsed=MapQuery(keywords="咖啡", city="深圳"))
    assert session.calls[0]["params"]["keywords"] == "咖啡"
    assert session.calls[0]["params"]["city"] == "深圳"


def test_amap_handler_passes_classifier_slots_as_preparsed():
    # 主路径：意图分类顺带抽出的槽位经 context.slots 直通 service，零额外 LLM 调用
    from routing.handler import RouteContext
    from routing.handlers.amap import AmapHandler

    class SpyService:
        def __init__(self):
            self.preparsed = "not-called"

        def ask(self, query, *, location=None, preparsed=None):
            self.preparsed = preparsed
            from amap_client.models import MapResult
            return MapResult(text="ok")

    svc = SpyService()
    ctx = RouteContext(slots={"keywords": "美食", "near": "深圳万科云城", "city": "深圳"})
    AmapHandler(svc).handle("深圳万科云城附近好吃的推荐", ctx)
    assert svc.preparsed.keywords == "美食"
    assert svc.preparsed.near == "深圳万科云城"
    assert svc.preparsed.city == "深圳"


def test_amap_handler_without_slots_lets_service_parse():
    from routing.handler import RouteContext
    from routing.handlers.amap import AmapHandler

    class SpyService:
        def __init__(self):
            self.preparsed = "not-called"

        def ask(self, query, *, location=None, preparsed=None):
            self.preparsed = preparsed
            from amap_client.models import MapResult
            return MapResult(text="ok")

    svc = SpyService()
    AmapHandler(svc).handle("附近的咖啡", RouteContext())  # 槽位为空（如关键词兜底分类）
    assert svc.preparsed is None  # 交回 service 内部 parser（降级路径）


def test_gemini_map_query_parser_extracts_fields():
    from routing.gemini import GeminiAnswer
    from routing.handlers.amap import GeminiMapQueryParser

    class FakeGemini:
        def generate(self, prompt, *, system=None, temperature=0.0, history=None):
            return '```json\n{"keywords": "美食", "near": "深圳万科云城", "city": "深圳"}\n```'

    mq = GeminiMapQueryParser(FakeGemini()).parse("深圳万科云城附近好吃的推荐")
    assert mq.keywords == "美食" and mq.near == "深圳万科云城" and mq.city == "深圳"


def test_gemini_map_query_parser_falls_back_on_bad_json():
    from routing.handlers.amap import GeminiMapQueryParser

    class FakeGemini:
        def generate(self, prompt, *, system=None, temperature=0.0, history=None):
            return "我无法解析"

    mq = GeminiMapQueryParser(FakeGemini()).parse("附近的咖啡")
    assert mq.keywords == "附近的咖啡" and mq.near is None
def test_geocode_sends_address_city_and_key():
    from amap_client.geocode_service import GeoCodeService
    from amap_client.rest_client import AmapRestClient

    session = FakeGetSession(
        {
            "status": "1",
            "info": "OK",
            "count": "1",
            "geocodes": [
                {
                    "formatted_address": "广东省深圳市南山区科技园",
                    "location": "113.946,22.540",
                    "adcode": "440305",
                    "city": "深圳市",
                }
            ],
        }
    )

    point = GeoCodeService(AmapRestClient(key="K", session=session)).geocode(
        "深圳市南山区科技园",
        city="深圳",
    )

    assert session.last_get["url"] == "https://restapi.amap.com/v3/geocode/geo"
    assert session.last_get["params"]["key"] == "K"
    assert session.last_get["params"]["address"] == "深圳市南山区科技园"
    assert session.last_get["params"]["city"] == "深圳"
    assert point.location == "113.946,22.540"
    assert point.adcode == "440305"


def test_geocode_raises_when_no_result():
    from amap_client.geocode_service import GeoCodeService
    from amap_client.rest_client import AmapRestClient

    session = FakeGetSession(
        {"status": "1", "info": "OK", "count": "0", "geocodes": []}
    )

    with pytest.raises(AmapError, match="未找到地址"):
        GeoCodeService(AmapRestClient(key="K", session=session)).geocode("不存在的地址")


def test_resolve_place_prefers_city_matched_poi():
    from amap_client.geocode_service import GeoCodeService
    from amap_client.rest_client import AmapRestClient

    session = MultiGetSession({
        "text": _rest_ok([
            {
                "name": "推车卤鹅",
                "location": "116.639465,23.658366",
                "adcode": "445102",
                "cityname": "潮州市",
            },
            {
                "name": "TCL国际E城",
                "location": "113.951000,22.573000",
                "adcode": "440305",
                "cityname": "深圳市",
            },
        ]),
    })

    point = GeoCodeService(AmapRestClient(key="K", session=session)).resolve_place(
        "TCL国际E城", city="深圳"
    )

    assert point.formatted_address == "TCL国际E城"
    assert point.location == "113.951000,22.573000"
    assert point.adcode == "440305"
    assert session.calls == [
        {
            "path": "text",
            "params": {
                "keywords": "TCL国际E城",
                "city": "深圳",
                "offset": 5,
                "page": 1,
                "extensions": "all",
                "key": "K",
            },
        }
    ]


def test_resolve_place_falls_back_to_geocode_when_poi_has_no_match():
    from amap_client.geocode_service import GeoCodeService
    from amap_client.rest_client import AmapRestClient

    session = MultiGetSession({
        "text": _rest_ok([]),
        "geo": _geocode_ok("440305"),
    })

    point = GeoCodeService(AmapRestClient(key="K", session=session)).resolve_place(
        "深圳市南山区科技园", city="深圳"
    )

    assert point.location == "114.057868,22.543099"
    assert [call["path"] for call in session.calls] == ["text", "geo"]


def test_resolve_place_rejects_wrong_city_poi():
    from amap_client.geocode_service import GeoCodeService
    from amap_client.rest_client import AmapRestClient

    session = MultiGetSession({
        "text": _rest_ok([
            {
                "name": "推车卤鹅",
                "location": "116.639465,23.658366",
                "adcode": "445102",
                "cityname": "潮州市",
            }
        ]),
        "geo": {"status": "0", "info": "ENGINE_RESPONSE_DATA_ERROR", "infocode": "30001"},
    })

    with pytest.raises(AmapError, match="未能定位地点"):
        GeoCodeService(AmapRestClient(key="K", session=session)).resolve_place(
            "TCL国际E城", city="深圳"
        )
    assert [call["path"] for call in session.calls] == ["text", "geo"]


def _geocode_ok(adcode="440300"):
    return {
        "status": "1",
        "info": "OK",
        "count": "1",
        "geocodes": [{
            "formatted_address": "广东省深圳市",
            "location": "114.057868,22.543099",
            "adcode": adcode,
        }],
    }


def test_weather_live_resolves_city_then_requests_amap_weather():
    from amap_client.geocode_service import GeoCodeService
    from amap_client.rest_client import AmapRestClient
    from amap_client.weather_service import AmapWeatherService

    session = MultiGetSession({
        "geo": _geocode_ok(),
        "weatherInfo": {
            "status": "1",
            "info": "OK",
            "lives": [{
                "city": "深圳市",
                "weather": "晴",
                "temperature": "30",
                "winddirection": "东",
                "windpower": "3",
                "humidity": "70",
                "reporttime": "2026-08-19 12:00:00",
            }],
        },
    })

    client = AmapRestClient(key="K", session=session)
    result = AmapWeatherService(client, GeoCodeService(client)).live("深圳")

    assert session.calls[0]["path"] == "geo"
    assert session.calls[0]["params"]["address"] == "深圳"
    assert session.calls[1]["path"] == "weatherInfo"
    assert session.calls[1]["params"]["city"] == "440300"
    assert session.calls[1]["params"]["extensions"] == "base"
    assert result.city == "深圳市"
    assert result.weather == "晴"
    assert result.temperature == "30"


def test_weather_forecast_uses_all_extension():
    from amap_client.geocode_service import GeoCodeService
    from amap_client.rest_client import AmapRestClient
    from amap_client.weather_service import AmapWeatherService

    session = MultiGetSession({
        "geo": _geocode_ok(),
        "weatherInfo": {
            "status": "1",
            "info": "OK",
            "forecasts": [{
                "city": "深圳市",
                "reporttime": "2026-08-19 12:00:00",
                "casts": [{
                    "date": "2026-08-19",
                    "dayweather": "晴",
                    "nightweather": "多云",
                    "daytemp": "32",
                    "nighttemp": "27",
                    "daywind": "东",
                    "nightwind": "东南",
                    "daypower": "3",
                    "nightpower": "2",
                }],
            }],
        },
    })

    client = AmapRestClient(key="K", session=session)
    result = AmapWeatherService(client, GeoCodeService(client)).forecast("深圳")

    assert session.calls[1]["params"]["extensions"] == "all"
    assert len(result.days) == 1
    assert result.days[0].day_weather == "晴"
    assert result.days[0].night_temp == "27"


def test_amap_weather_live_handler_uses_live_service():
    from amap_client.models import WeatherLive
    from routing.handler import RouteContext
    from routing.handlers.amap_weather_live import AmapWeatherLiveHandler

    class FakeWeatherService:
        def live(self, city):
            assert city == "深圳"
            return WeatherLive(
                city="深圳市",
                weather="晴",
                temperature="30",
                humidity="70",
            )

    result = AmapWeatherLiveHandler(FakeWeatherService()).handle(
        "深圳现在天气怎么样",
        RouteContext(slots={"city": "深圳"}),
    )

    assert result.intent == "amap_weather_live"
    assert "深圳市当前天气：晴，30°C" in result.text
    assert "湿度70%" in result.text


def test_amap_weather_forecast_handler_selects_tomorrow():
    from amap_client.models import WeatherDay, WeatherForecast
    from routing.handler import RouteContext
    from routing.handlers.amap_weather_forecast import AmapWeatherForecastHandler

    class FakeWeatherService:
        def forecast(self, city):
            assert city == "深圳"
            return WeatherForecast(
                city="深圳市",
                days=[
                    WeatherDay("2026-08-19", "晴", "晴", "32", "27"),
                    WeatherDay("2026-08-20", "多云", "阵雨", "31", "26"),
                ],
            )

    result = AmapWeatherForecastHandler(FakeWeatherService()).handle(
        "深圳明天会下雨吗",
        RouteContext(slots={"city": "深圳"}),
    )

    assert result.intent == "amap_weather_forecast"
    assert "2026-08-20" in result.text
    assert "阵雨" in result.text
    assert "2026-08-19" not in result.text


def test_amap_weather_forecast_handler_keeps_the_available_window_for_unparsed_time():
    from amap_client.models import WeatherDay, WeatherForecast
    from routing.handler import RouteContext
    from routing.handlers.amap_weather_forecast import AmapWeatherForecastHandler

    class FakeWeatherService:
        def forecast(self, city):
            return WeatherForecast(
                city=city,
                days=[
                    WeatherDay("2026-08-21", "晴", "晴", "32", "27"),
                    WeatherDay("2026-08-22", "多云", "阵雨", "31", "26"),
                ],
            )

    result = AmapWeatherForecastHandler(FakeWeatherService()).handle(
        "深圳周六天气", RouteContext(slots={"city": "深圳", "days": 1})
    )

    assert "2026-08-21" in result.text
    assert "2026-08-22" in result.text

def test_driving_route_resolves_two_addresses_then_plans_route():
    from amap_client.driving_service import DrivingRouteService
    from amap_client.geocode_service import GeoCodeService
    from amap_client.rest_client import AmapRestClient

    session = MultiGetSession({
        "text": _rest_ok([{
            "name": "测试地点",
            "location": "113.946040,22.544610",
            "adcode": "440306",
            "cityname": "深圳市",
        }]),
        "geo": {
            "status": "1",
            "info": "OK",
            "count": "1",
            "geocodes": [{
                "formatted_address": "测试地点",
                "location": "113.946040,22.544610",
                "adcode": "440306",
            }],
        },
        "driving": {
            "status": "1",
            "info": "OK",
            "route": {
               "paths": [{
                    "strategy": "速度优先",
                    "cost": {
                        "distance": "12500",
                        "duration": "1800",
                        "tolls": "0",
                        "toll_distance": "0",
                    },
                    "steps": [{
                        "instruction": "沿创业路向东行驶",
                        "distance": "500",
                        "road_name": "创业路",
                    }],
                }],
            },
        },
    })

    client = AmapRestClient(key="K", session=session)
    service = DrivingRouteService(client, GeoCodeService(client))

    result = service.plan(
        "深圳宝安区",
        "深圳南山区科技园",
        origin_city="深圳",
        destination_city="深圳",
    )

    assert session.calls[0]["path"] == "text"
    assert session.calls[0]["params"]["keywords"] == "深圳宝安区"

    assert session.calls[1]["path"] == "text"
    assert session.calls[1]["params"]["keywords"] == "深圳南山区科技园"

    assert session.calls[2]["path"] == "driving"
    assert session.calls[2]["params"]["origin"] == "113.946040,22.544610"
    assert session.calls[2]["params"]["destination"] == "113.946040,22.544610"
    assert session.calls[2]["params"]["strategy"] == 0
    assert session.calls[2]["params"]["show_fields"] == "cost,navi"

    assert result.distance_m == 12500
    assert result.duration_s == 1800
    assert result.steps[0].instruction == "沿创业路向东行驶"
def test_amap_driving_handler_passes_slots_to_service():
    from amap_client.models import DrivingRoute, GeoPoint
    from routing.handler import RouteContext
    from routing.handlers.amap_driving import AmapDrivingHandler

    class SpyDrivingService:
        def __init__(self):
            self.args = None

        def plan(self, origin, destination, *, origin_city="", destination_city=""):
            self.args = (origin, destination, origin_city, destination_city)
            return DrivingRoute(
                origin=GeoPoint("广东省深圳市宝安区", "113.88,22.55"),
                destination=GeoPoint("广东省深圳市南山区科技园", "113.94,22.54"),
                distance_m=12500,
                duration_s=1800,
            )

    service = SpyDrivingService()
    result = AmapDrivingHandler(service).handle(
        "从深圳宝安区开车到南山科技园要多久",
        RouteContext(
            slots={
                "origin": "深圳宝安区",
                "destination": "南山科技园",
                "origin_city": "深圳",
                "destination_city": "深圳",
            }
        ),
    )

    assert service.args == ("深圳宝安区", "南山科技园", "深圳", "深圳")
    assert result.intent == "amap_driving"
    assert "约12.5公里" in result.text
    assert "预计30分钟" in result.text


def test_amap_driving_handler_asks_for_missing_places():
    from routing.handler import RouteContext
    from routing.handlers.amap_driving import AmapDrivingHandler

    class NeverCalledService:
        def plan(self, *args, **kwargs):
            raise AssertionError("缺少起终点时不应调用路线服务")

    result = AmapDrivingHandler(NeverCalledService()).handle(
        "帮我规划驾车路线",
        RouteContext(),
    )

    assert result.intent == "amap_driving"
    assert "起点和终点" in result.text


def test_amap_driving_handler_uses_mobile_location_when_origin_is_omitted():
    from amap_client.models import DrivingRoute, GeoPoint
    from routing.handler import RouteContext
    from routing.handlers.amap_driving import AmapDrivingHandler

    class SpyDrivingService:
        def __init__(self):
            self.args = None

        def plan(self, origin, destination, **kwargs):
            self.args = (origin, destination, kwargs)
            return DrivingRoute(
                origin=GeoPoint("当前位置", "113.9,22.5"),
                destination=GeoPoint("南山科技园", "113.95,22.6"),
                distance_m=1000,
                duration_s=300,
            )

    service = SpyDrivingService()
    result = AmapDrivingHandler(service).handle(
        "去哪怎么走",
        RouteContext(
            platform="mobile",
            location="113.9,22.5",
            slots={"destination": "南山科技园"},
        ),
    )

    assert result.status == "success"
    assert service.args[0] == "我这里"
    assert service.args[2]["origin_location"] == "113.9,22.5"


def test_active_route_service_uses_selected_rest_method():
    from amap_client.active_route_service import ActiveRouteService
    from amap_client.geocode_service import GeoCodeService
    from amap_client.rest_client import AmapRestClient

    session = MultiGetSession({
        "text": _rest_ok([{
            "name": "测试地点",
            "location": "114.057868,22.543099",
            "adcode": "440300",
            "cityname": "深圳市",
        }]),
        "walking": {
            "status": "1",
            "info": "OK",
            "route": {"paths": [{
                "cost": {"distance": "600", "duration": "480"},
                "steps": [{"instruction": "沿科技南路向东步行", "distance": "600"}],
            }]},
        },
    })
    client = AmapRestClient(key="K", session=session)
    route = ActiveRouteService(client, GeoCodeService(client), mode="walking").plan("A", "B")

    assert session.calls[2]["path"] == "walking"
    assert session.calls[2]["params"]["show_fields"] == "cost,navi"
    assert route.distance_m == 600 and route.duration_s == 480
    assert route.steps[0].instruction == "沿科技南路向东步行"


def test_transit_route_service_uses_adcodes_and_extracts_bus_line():
    from amap_client.geocode_service import GeoCodeService
    from amap_client.rest_client import AmapRestClient
    from amap_client.transit_service import TransitRouteService

    session = MultiGetSession({
        "text": _rest_ok([{
            "name": "测试地点",
            "location": "114.057868,22.543099",
            "adcode": "440300",
            "cityname": "深圳市",
        }]),
        "geo": _geocode_ok("440300"),
        "integrated": {
            "status": "1",
            "info": "OK",
            "route": {"transits": [{
                "cost": {"distance": "12000", "duration": "2400", "transit_fee": "3"},
                "transfers": "1",
                "walking_distance": "700",
                "segments": [{"bus": {"buslines": [{
                    "name": "地铁1号线",
                    "departure_stop": {"name": "宝安中心"},
                    "arrival_stop": {"name": "世界之窗"},
                }]}}],
            }]},
        },
    })
    client = AmapRestClient(key="K", session=session)
    route = TransitRouteService(client, GeoCodeService(client)).plan("A", "B")

    assert session.calls[2]["path"] == "integrated"
    assert session.calls[2]["params"]["city1"] == "440300"
    assert session.calls[2]["params"]["city2"] == "440300"
    assert route.duration_s == 2400
    assert route.cost_yuan == 3.0
    assert "地铁1号线" in route.segments[0]


def test_walking_and_bicycling_handlers_use_their_own_intents():
    from amap_client.models import ActiveRoute, GeoPoint
    from routing.handler import RouteContext
    from routing.handlers.amap_active_route import AmapBicyclingHandler, AmapWalkingHandler

    class FakeActiveService:
        def plan(self, origin, destination, **kwargs):
            return ActiveRoute(
                origin=GeoPoint(origin, "1,2"),
                destination=GeoPoint(destination, "3,4"),
                distance_m=800,
                duration_s=600,
            )

    context = RouteContext(slots={"origin": "A", "destination": "B"})
    walking = AmapWalkingHandler(FakeActiveService()).handle("从A步行到B", context)
    bicycling = AmapBicyclingHandler(FakeActiveService()).handle("从A骑车到B", context)

    assert walking.intent == "amap_walking" and "步行" in walking.text
    assert bicycling.intent == "amap_bicycling" and "骑行" in bicycling.text


def test_amap_transit_handler_renders_transit_summary():
    from amap_client.models import GeoPoint, TransitRoute
    from routing.handler import RouteContext
    from routing.handlers.amap_transit import AmapTransitHandler

    class FakeTransitService:
        def plan(self, origin, destination, **kwargs):
            return TransitRoute(
                origin=GeoPoint(origin, "1,2"),
                destination=GeoPoint(destination, "3,4"),
                distance_m=12000,
                duration_s=2400,
                walking_distance_m=700,
                cost_yuan=3,
                transfers=1,
                segments=["乘坐地铁1号线（宝安中心上车，世界之窗下车）"],
            )

    result = AmapTransitHandler(FakeTransitService()).handle(
        "从A坐地铁到B",
        RouteContext(slots={"origin": "A", "destination": "B"}),
    )

    assert result.intent == "amap_transit"
    assert "预计40分钟" in result.text
    assert "换乘1次" in result.text
    assert "地铁1号线" in result.text


def test_amap_transit_handler_marks_provider_error_as_failed():
    from amap_client.errors import AmapError
    from routing.handler import RouteContext
    from routing.handlers.amap_transit import AmapTransitHandler

    class FailingTransitService:
        def plan(self, origin, destination, **kwargs):
            raise AmapError("未能定位地点：起点")

    result = AmapTransitHandler(FailingTransitService()).handle(
        "从A坐地铁到B", RouteContext(slots={"origin": "A", "destination": "B"})
    )

    assert result.status == "failed"
    assert "公交路线查询失败" in result.text


def test_regeo_service_turns_location_into_address_and_adcode():
    from amap_client.regeo_service import RegeoService
    from amap_client.rest_client import AmapRestClient

    session = MultiGetSession({
        "regeo": {
            "status": "1",
            "info": "OK",
            "regeocode": {
                "formatted_address": "广东省深圳市南山区科技园",
                "addressComponent": {"city": "深圳市", "adcode": "440305"},
            },
        },
    })

    point = RegeoService(AmapRestClient(key="K", session=session)).reverse_geocode("113.946,22.545")

    assert session.calls[0]["path"] == "regeo"
    assert session.calls[0]["params"]["location"] == "113.946,22.545"
    assert point.formatted_address == "广东省深圳市南山区科技园"
    assert point.adcode == "440305"


def test_driving_route_uses_gps_origin_when_supplied():
    from amap_client.driving_service import DrivingRouteService
    from amap_client.geocode_service import GeoCodeService
    from amap_client.regeo_service import RegeoService
    from amap_client.rest_client import AmapRestClient

    session = MultiGetSession({
        "regeo": {
            "status": "1", "info": "OK",
            "regeocode": {"formatted_address": "当前位置", "addressComponent": {"adcode": "440305"}},
        },
        "text": _rest_ok([{
            "name": "目的地",
            "location": "113.946040,22.544610",
            "adcode": "440305",
            "cityname": "深圳市",
        }]),
        "driving": {
            "status": "1", "info": "OK",
            "route": {"paths": [{"cost": {"distance": "1000", "duration": "300"}}]},
        },
    })
    client = AmapRestClient(key="K", session=session)
    service = DrivingRouteService(client, GeoCodeService(client), RegeoService(client))

    route = service.plan("我这里", "目的地", origin_location="113.946,22.545")

    assert session.calls[0]["path"] == "regeo"
    assert session.calls[1]["path"] == "text"
    assert session.calls[2]["params"]["origin"] == "113.946,22.545"
    assert route.origin.formatted_address == "当前位置"
