"""Exa Search API 的单元测试，不访问真实网络。"""

from __future__ import annotations

import json

import pytest

from exa_client.client import ExaClient
from exa_client.errors import ExaError
from exa_client.service import ExaSearchService
from exa_client.models import SearchItem, SearchResult
from routing.handler import RouteContext
from routing.handlers.exa_search import ExaSearchHandler


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, payload: object, status_code: int = 200):
        self._payload = payload
        self._status_code = status_code
        self.last_post = None

    def post(self, url, json=None, headers=None, timeout=None):
        self.last_post = {
            "url": url,
            "json": json,
            "headers": headers,
            "timeout": timeout,
        }
        return FakeResponse(self._payload, self._status_code)


def _success_response():
    return {
        "requestId": "req-123",
        "searchTime": 293.6,
        "costDollars": {"total": 0.007},
        "results": [
            {
                "title": "OpenAI News",
                "url": "https://example.com/openai-news",
                "publishedDate": "2026-08-20T10:00:00.000Z",
                "author": "Alice",
                "highlights": ["第一段重点内容", "第二段重点内容"],
            }
        ],
    }


def test_exa_search_sends_bearer_auth_and_expected_payload():
    session = FakeSession(_success_response())
    client = ExaClient("EXA_TEST_KEY", session=session)

    client.search("latest AI news", num_results=3, search_type="instant")

    assert session.last_post["url"] == "https://api.exa.ai/search"
    assert session.last_post["headers"]["Authorization"] == "Bearer EXA_TEST_KEY"
    assert session.last_post["headers"]["Content-Type"] == "application/json"
    assert session.last_post["json"] == {
        "query": "latest AI news",
        "type": "instant",
        "numResults": 3,
        "contents": {"highlights": True},
    }


def test_exa_service_parses_search_result():
    session = FakeSession(_success_response())
    service = ExaSearchService(ExaClient("K", session=session))

    result = service.search("latest AI news")

    assert result.request_id == "req-123"
    assert result.search_time_ms == 293.6
    assert result.cost_usd == 0.007
    assert len(result.items) == 1

    item = result.items[0]
    assert item.title == "OpenAI News"
    assert item.url == "https://example.com/openai-news"
    assert item.author == "Alice"
    assert item.highlights == ["第一段重点内容", "第二段重点内容"]


def test_exa_error_response_raises_exa_error():
    session = FakeSession(
        {"error": "Rate limit exceeded"},
        status_code=429,
    )

    with pytest.raises(ExaError, match="429"):
        ExaClient("K", session=session).search("latest AI news")


def test_exa_rejects_invalid_local_arguments():
    client = ExaClient("K", session=FakeSession(_success_response()))

    with pytest.raises(ExaError, match="不能为空"):
        client.search(" ")

    with pytest.raises(ExaError, match="1 到 10"):
        client.search("test", num_results=0)

    with pytest.raises(ExaError, match="不支持"):
        client.search("test", search_type="unknown")


class FakeExaSearchService:
    def __init__(self, result: SearchResult | None = None, error: ExaError | None = None):
        self.result = result or SearchResult(query="test")
        self.error = error
        self.calls = []

    def search(self, query: str, *, num_results: int = 5) -> SearchResult:
        self.calls.append((query, num_results))
        if self.error:
            raise self.error
        return self.result


def _handler_result() -> SearchResult:
    return SearchResult(
        query="OpenAI 最新发布",
        items=[
            SearchItem(
                title="OpenAI News",
                url="https://example.com/openai-news",
                published_date="2026-08-20",
                highlights=["这是第一条搜索结果的重点摘要。"],
            ),
            SearchItem(
                title="OpenAI Research",
                url="https://example.com/openai-research",
                highlights=["这是第二条搜索结果的重点摘要。"],
            ),
        ],
    )


def test_exa_search_handler_uses_slots_and_renders_sources():
    service = FakeExaSearchService(_handler_result())
    handler = ExaSearchHandler(service)

    result = handler.handle(
        "联网搜索 OpenAI 最近发布了什么，来2条",
        RouteContext(slots={"query": "OpenAI 最新发布", "limit": 2}),
    )

    assert service.calls == [("OpenAI 最新发布", 2)]
    assert result.intent == "exa_search"
    assert "OpenAI News" in result.text
    assert "https://example.com/openai-news" in result.text
    assert "第一条搜索结果" in result.text


def test_exa_search_handler_clamps_limit_to_ten():
    service = FakeExaSearchService(_handler_result())
    handler = ExaSearchHandler(service)

    handler.handle(
        "联网搜索 OpenAI，来50条",
        RouteContext(slots={"query": "OpenAI", "limit": 50}),
    )

    assert service.calls == [("OpenAI", 10)]


def test_exa_search_handler_uses_original_query_when_slot_missing():
    service = FakeExaSearchService(_handler_result())
    handler = ExaSearchHandler(service)

    handler.handle("联网搜索 量子计算研究", RouteContext())

    assert service.calls == [("量子计算研究", 5)]


def test_exa_search_handler_returns_empty_message():
    service = FakeExaSearchService(SearchResult(query="不存在的内容"))
    handler = ExaSearchHandler(service)

    result = handler.handle(
        "联网搜索不存在的内容",
        RouteContext(slots={"query": "不存在的内容"}),
    )

    assert "没有找到" in result.text


def test_exa_search_handler_returns_friendly_error():
    service = FakeExaSearchService(error=ExaError("Rate limit exceeded"))
    handler = ExaSearchHandler(service)

    result = handler.handle(
        "联网搜索 OpenAI",
        RouteContext(slots={"query": "OpenAI"}),
    )

    assert "联网搜索失败" in result.text