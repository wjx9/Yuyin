"""高德地图 Handler：周边/路线/景点等基于位置的查询。

REST 后端需要把自然语言拆成 关键词 + 地点。主路径：这三个槽位由 AmapHandler.slots
声明，意图分类的 function calling **一次**顺带抽出（零额外 LLM 调用），经
MapService.ask(preparsed=...) 直通 REST 实现。降级路径（分类走了关键词兜底、槽位
为空）：仍由注入的 GeminiMapQueryParser 单独解析，其提示词从同一份 SlotSpec 生成，
两条路径的抽取语义天然一致。解析器放 routing 层，amap_client 不反向依赖 Gemini。
"""

from __future__ import annotations

import logging

from amap_client.errors import AmapError
from amap_client.models import MapQuery
from amap_client.parser import QueryParser
from amap_client.service import MapService

from ..gemini import GeminiClient, GeminiError, loads_json_loose
from ..handler import Handler, RouteContext, RouteResult, SlotSpec

_log = logging.getLogger(__name__)

# 槽位既是分类器的 function 参数 schema，也是降级解析器的字段说明（单一事实源）。
_SLOTS = (
    SlotSpec(
        "keywords", "string",
        "要检索的对象或品类，如'美食'、'川菜'、'咖啡'、'景点'、'加油站'；"
        "必须是简短检索词，不要带地点、不要带'附近/推荐/top5'等修饰",
    ),
    SlotSpec(
        "near", "string",
        "用户点名的地点或地标，如'深圳万科云城'、'北京西站'；"
        "只说'附近/我周边'没点名地点就不要填",
    ),
    SlotSpec("city", "string", "能判断出的城市名，如'深圳'；判断不出就不要填"),
)


def _map_query_from_slots(slots: dict, query: str) -> MapQuery:
    return MapQuery(
        keywords=slots.get("keywords") or query,
        near=slots.get("near"),
        city=slots.get("city"),
    )


class AmapHandler(Handler):
    intent = "amap"
    description = "地图地点搜索：附近的店、景点、美食、咖啡、商场、加油站等 POI 周边查询；不处理天气、地址转坐标或路线规划"
    slots = _SLOTS

    def __init__(self, service: MapService):
        self._service = service

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        # 分类器抽到了 keywords 才算有效槽位；否则 preparsed=None，交回 service
        # 内部的 parser（REST 后端为 GeminiMapQueryParser，见模块 docstring）。
        preparsed = _map_query_from_slots(context.slots, query) if context.slots.get("keywords") else None
        try:
            result = self._service.ask(query, location=context.location, preparsed=preparsed)
        except AmapError as e:
            return RouteResult(text=f"地图查询失败：{e}", intent=self.intent)
        return RouteResult(text=result.text, data=result, intent=self.intent)


_PARSER_SYSTEM = (
    "你是高德地图检索的查询解析器。把用户的自然语言诉求拆成 JSON，字段：\n"
    + "\n".join(f"  {s.name}: {s.description}。填不出的字段置为空字符串。" for s in _SLOTS)
    + "\n只输出一个 JSON 对象，不要解释，不要代码块。"
)


class GeminiMapQueryParser(QueryParser):
    """用 Gemini 把自然语言拆成 MapQuery（降级路径用）。失败时退回整句当关键词。"""

    def __init__(self, gemini: GeminiClient):
        self._gemini = gemini

    def parse(self, query: str) -> MapQuery:
        try:
            raw = self._gemini.generate(query, system=_PARSER_SYSTEM, temperature=0.0)
        except GeminiError as e:
            _log.warning("高德查询解析失败，退回整句关键词: %s", e)
            return MapQuery(keywords=query)
        data = loads_json_loose(raw)
        if not isinstance(data, dict):
            return MapQuery(keywords=query)
        keywords = (data.get("keywords") or "").strip() or query
        near = (data.get("near") or "").strip() or None
        city = (data.get("city") or "").strip() or None
        _log.debug("高德查询解析: keywords=%r near=%r city=%r", keywords, near, city)
        return MapQuery(keywords=keywords, near=near, city=city)
