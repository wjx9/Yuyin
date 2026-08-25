"""Exa 联网网页搜索 Handler。"""

from __future__ import annotations

import re

from exa_client.errors import ExaError
from exa_client.service import ExaSearchService

from ..handler import Handler, RouteContext, RouteResult, SlotSpec

_DEFAULT_RESULTS = 5
_MAX_RESULTS = 10
_SNIPPET_LIMIT = 240

_COUNT_RE = re.compile(
    r"(?:top|前|来|要)\s*(\d+)\s*(?:条|个|则|篇)?|(\d+)\s*(?:条|个|则|篇)",
    re.IGNORECASE,
)

_REQUEST_PREFIX_RE = re.compile(
    r"^(?:(?:请|麻烦|能否|可以)\s*)?"
    r"(?:(?:帮我|给我|我想|我要)\s*)?"
    r"(?:联网搜索|网上搜索|全网搜索|搜索网页|搜索|搜一下|搜搜|搜下|"
    r"查一下|查查|查询|查下)\s*"
)


def _limit_from_context(context: RouteContext, query: str) -> int:
    """优先使用 Gemini 提取的 limit；没有时再从原句中识别“前 3 条”等表达。"""
    value = context.slots.get("limit")
    if isinstance(value, int) and not isinstance(value, bool):
        return max(1, min(value, _MAX_RESULTS))

    match = _COUNT_RE.search(query)
    if match:
        value = int(match.group(1) or match.group(2))
        return max(1, min(value, _MAX_RESULTS))

    return _DEFAULT_RESULTS


def _fallback_query(query: str) -> str:
    """Gemini 没有填 query 槽位时，从原句去掉少量请求话术。"""
    text = _COUNT_RE.sub("", query).strip()
    text = _REQUEST_PREFIX_RE.sub("", text).strip()

    if text.startswith("关于"):
        text = text.removeprefix("关于").strip()

    return text or query.strip()


def _snippet(highlights: list[str]) -> str | None:
    if not highlights:
        return None

    text = re.sub(r"\s+", " ", highlights[0]).replace("...", "").strip()
    if len(text) > _SNIPPET_LIMIT:
        return text[:_SNIPPET_LIMIT].rstrip() + "..."
    return text or None


class ExaSearchHandler(Handler):
    intent = "exa_search"
    description = (
        "联网查询跨网站公开网页、官方发布、技术文档、研究资料或指定主体的最新公开信息，"
        "例如“联网搜索 OpenAI 最近发布了什么”“查一下具身智能的研究资料”；"
        "不处理全国热点或某地区新闻报道（走腾讯新闻），不处理天气、地图地点、路线规划。"
    )
    slots = (
        SlotSpec(
            "query",
            "string",
            "要交给网页搜索引擎的核心检索词，例如“OpenAI 最近发布”或“具身智能研究资料”；"
            "不要带“帮我查”“联网搜索”“来3条”等请求话术。",
        ),
        SlotSpec(
            "limit",
            "integer",
            "用户要求返回的结果数，例如“前3条”填 3；范围 1 到 10；用户未提及则不要填。",
        ),
    )

    def __init__(self, service: ExaSearchService):
        self._service = service

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        search_query = context.slots.get("query") or _fallback_query(query)
        limit = _limit_from_context(context, query)

        try:
            result = self._service.search(search_query, num_results=limit)
        except ExaError as error:
            return RouteResult(
                text=f"联网搜索失败：{error}",
                intent=self.intent,
            )

        if not result.items:
            return RouteResult(
                text=f"没有找到与“{search_query}”相关的公开网页结果。",
                data=result,
                intent=self.intent,
            )

        lines = [f"【Exa 联网搜索：「{result.query}」】"]
        for index, item in enumerate(result.items, start=1):
            lines.append(f"{index}. {item.title}")

            if item.published_date:
                lines.append(f"   发布时间：{item.published_date}")

            summary = _snippet(item.highlights)
            if summary:
                lines.append(f"   摘要：{summary}")

            lines.append(f"   来源：{item.url}")

        return RouteResult(
            text="\n".join(lines),
            data=result,
            intent=self.intent,
        )