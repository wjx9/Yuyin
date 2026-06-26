"""OpenAPI 传输：SSE 流式解析、HTTP 错误映射（用假 session 隔离网络）。"""

import json

import pytest

from tripnow_client.errors import AuthError, TransportError
from tripnow_client.models import ChatRequest, Message
from tripnow_client.transport.openapi import OpenApiClient


class FakeResponse:
    def __init__(self, *, status=200, json_body=None, lines=None, text=""):
        self.status_code = status
        self.ok = 200 <= status < 300
        self._json = json_body
        self._lines = lines or []
        self.text = text

    def json(self):
        return self._json

    def iter_lines(self, decode_unicode=True):
        return iter(self._lines)


class FakeSession:
    def __init__(self, response):
        self._response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self._response

    def close(self):
        pass


def _chunk(content, finish=None):
    return "data: " + json.dumps(
        {"choices": [{"delta": {"content": content}, "finish_reason": finish}]}
    )


def test_stream_parses_sse_lines():
    session = FakeSession(
        FakeResponse(lines=[_chunk("高铁"), "", _chunk("G10"), "data: [DONE]"])
    )
    client = OpenApiClient("http://x", "sk-test", session=session)

    chunks = list(
        client.chat_stream(ChatRequest(messages=[Message("user", "q")]))
    )

    assert "".join(c.delta for c in chunks) == "高铁G10"
    # 流式调用应把 stream 置 true
    assert session.calls[0][1]["json"]["stream"] is True


def test_chat_parses_json_body():
    body = {"id": "1", "choices": [{"message": {"content": "ok"}}]}
    client = OpenApiClient(
        "http://x", "sk-test", session=FakeSession(FakeResponse(json_body=body))
    )
    resp = client.chat(ChatRequest(messages=[Message("user", "q")]))
    assert resp.content == "ok"


def test_auth_error_on_401():
    client = OpenApiClient(
        "http://x", "sk-bad", session=FakeSession(FakeResponse(status=401))
    )
    with pytest.raises(AuthError):
        client.chat(ChatRequest(messages=[Message("user", "q")]))


def test_transport_error_on_500():
    client = OpenApiClient(
        "http://x", "sk-test", session=FakeSession(FakeResponse(status=500, text="boom"))
    )
    with pytest.raises(TransportError):
        client.chat(ChatRequest(messages=[Message("user", "q")]))
