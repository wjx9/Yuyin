"""Exa Search API 的领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def _string_or_none(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _highlights(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


@dataclass
class SearchItem:
    """一条联网搜索结果。"""

    title: str
    url: str
    published_date: str | None = None
    author: str | None = None
    highlights: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    """一次 Exa 搜索的完整结果。"""

    query: str
    items: list[SearchItem] = field(default_factory=list)
    request_id: str | None = None
    search_time_ms: float | None = None
    cost_usd: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(cls, query: str, data: dict[str, Any]) -> "SearchResult":
        items: list[SearchItem] = []

        for result in data.get("results") or []:
            if not isinstance(result, dict):
                continue

            title = _string_or_none(result.get("title"))
            url = _string_or_none(result.get("url"))
            if not title or not url:
                continue

            items.append(
                SearchItem(
                    title=title,
                    url=url,
                    published_date=_string_or_none(result.get("publishedDate")),
                    author=_string_or_none(result.get("author")),
                    highlights=_highlights(result.get("highlights")),
                )
            )

        cost = data.get("costDollars")
        if not isinstance(cost, dict):
            cost = {}

        search_time = data.get("searchTime")
        try:
            search_time_ms = float(search_time)
        except (TypeError, ValueError):
            search_time_ms = None

        total_cost = cost.get("total")
        try:
            cost_usd = float(total_cost)
        except (TypeError, ValueError):
            cost_usd = None

        return cls(
            query=query,
            items=items,
            request_id=_string_or_none(data.get("requestId")),
            search_time_ms=search_time_ms,
            cost_usd=cost_usd,
            raw=data,
        )