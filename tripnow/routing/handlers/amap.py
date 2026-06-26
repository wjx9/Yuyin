"""高德地图 Handler：周边/路线/景点等基于位置的查询。

REST 后端需要把自然语言拆成 关键词 + 地点，这一步靠 GeminiMapQueryParser 完成
（放在 routing 层，避免 amap_client 反向依赖 Gemini）。
"""

from __future__ import annotations

import json
import logging

from amap_client.errors import AmapError
from amap_client.models import MapQuery
from amap_client.parser import QueryParser
from amap_client.service import MapService

from ..gemini import GeminiClient, GeminiError
from ..handler import Handler, RouteContext, RouteResult

_log = logging.getLogger(__name__)


class AmapHandler(Handler):
    intent = "amap"
    description = "地图与位置服务：附近的店/景点/美食、路线导航、怎么走、周边查询"

    def __init__(self, service: MapService):
        self._service = service

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        try:
            result = self._service.ask(query, location=context.location)
        except AmapError as e:
            return RouteResult(text=f"地图查询失败：{e}", intent=self.intent)
        return RouteResult(text=result.text, data=result, intent=self.intent)


_PARSER_SYSTEM = """你是高德地图检索的查询解析器。把用户的自然语言诉求拆成 JSON，字段：
  keywords: 要检索的对象或品类，例如 "美食"、"川菜"、"咖啡"、"景点"、"加油站"。必须是简短的检索词，不要带地点、不要带"附近/推荐/top5"等修饰。
  near: 用户点名的地点或地标，例如 "深圳万科云城"、"北京西站"。如果用户只说"附近/我周边"没点名地点，置为空字符串。
  city: 能判断出的城市名，例如 "深圳"，判断不出置为空字符串。
只输出一个 JSON 对象，不要解释，不要代码块。"""


class GeminiMapQueryParser(QueryParser):
    """用 Gemini 把自然语言拆成 MapQuery。失败时退回整句当关键词。"""

    def __init__(self, gemini: GeminiClient):
        self._gemini = gemini

    def parse(self, query: str) -> MapQuery:
        try:
            raw = self._gemini.generate(query, system=_PARSER_SYSTEM, temperature=0.0)
        except GeminiError as e:
            _log.warning("高德查询解析失败，退回整句关键词: %s", e)
            return MapQuery(keywords=query)
        data = _loads_json(raw)
        if not isinstance(data, dict):
            return MapQuery(keywords=query)
        keywords = (data.get("keywords") or "").strip() or query
        near = (data.get("near") or "").strip() or None
        city = (data.get("city") or "").strip() or None
        _log.debug("高德查询解析: keywords=%r near=%r city=%r", keywords, near, city)
        return MapQuery(keywords=keywords, near=near, city=city)


def _loads_json(text: str):
    """容错解析：剥掉可能的 ```json 代码块，取第一个 {...}。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(t[start : end + 1])
    except ValueError:
        return None
