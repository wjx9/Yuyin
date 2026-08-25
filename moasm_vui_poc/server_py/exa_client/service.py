"""Exa 搜索业务层：调用 HTTP Client 并解析为领域模型。"""

from __future__ import annotations

from .client import ExaClient
from .models import SearchResult


class ExaSearchService:
    def __init__(self, client: ExaClient):
        self._client = client

    def search(
        self,
        query: str,
        *,
        num_results: int = 5,
        search_type: str = "instant",
    ) -> SearchResult:
        data = self._client.search(
            query,
            num_results=num_results,
            search_type=search_type,
        )
        return SearchResult.from_response(query, data)