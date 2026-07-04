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
