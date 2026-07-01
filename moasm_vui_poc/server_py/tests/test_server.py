"""server 层单测：ChatService 核心 + schema 校验 + HTTP 适配器（假 dispatcher，不联网）。"""

from __future__ import annotations

import json
import threading
import urllib.request
import urllib.error

import pytest

from routing.handler import RouteContext, RouteResult
from server.auth import Credentials, CredentialProvider, MockCredentialProvider
from server.http_server import build_http_server
from server.schemas import BadRequest, ChatRequest, ChatResponse
from server.service import ChatService
from server.session import SessionStore


class FakeDispatcher:
    """记录每次 dispatch 收到的 query 与 context，回显固定结果。

    仿真 platform 过滤：music_control 是 PC-only，仅 pc 端可见（对应真 Dispatcher.intents_for）。
    """

    _PC_ONLY = {"music_control"}

    def __init__(self):
        self.calls = []
        self._all_intents = ["chitchat", "amap", "music_control"]

    def intents_for(self, platform="pc"):
        return [i for i in self._all_intents if not (i in self._PC_ONLY and platform == "mobile")]

    @property
    def intents(self):
        return self.intents_for("pc")

    def dispatch(self, query, context: RouteContext) -> RouteResult:
        self.calls.append({"query": query, "context": context})
        return RouteResult(text=f"回复:{query}", intent="chitchat")


def _service(dispatcher=None, credentials=None) -> ChatService:
    return ChatService(
        dispatcher=dispatcher or FakeDispatcher(),
        store=SessionStore(),
        credentials=credentials or MockCredentialProvider(tripnow_union_id="UNION-TEST"),
    )


# ---- schema ----


def test_request_requires_query_and_session():
    with pytest.raises(BadRequest):
        ChatRequest.from_dict({"session_id": "s1"})
    with pytest.raises(BadRequest):
        ChatRequest.from_dict({"query": "hi"})


def test_request_defaults_and_optional_fields():
    req = ChatRequest.from_dict({"query": " 附近咖啡 ", "session_id": "s1"})
    assert req.query == "附近咖啡" and req.session_id == "s1"
    assert req.user_id == "mock-user" and req.location is None and req.include_data is True


def test_response_to_dict():
    assert ChatResponse("hi", "chitchat", "s1").to_dict() == {
        "text": "hi",
        "intent": "chitchat",
        "session_id": "s1",
    }


# ---- ChatService ----


def test_service_injects_mock_credential_as_union_id():
    disp = FakeDispatcher()
    svc = _service(disp)
    svc.handle_chat(ChatRequest(query="我的行程", session_id="s1"))
    assert disp.calls[0]["context"].union_id == "UNION-TEST"


def test_service_passes_location():
    disp = FakeDispatcher()
    svc = _service(disp)
    svc.handle_chat(ChatRequest(query="附近", session_id="s1", location="116.0,39.0"))
    assert disp.calls[0]["context"].location == "116.0,39.0"


def test_service_isolates_history_per_session():
    disp = FakeDispatcher()
    svc = _service(disp)
    svc.handle_chat(ChatRequest(query="a", session_id="s1"))
    svc.handle_chat(ChatRequest(query="b", session_id="s1"))
    svc.handle_chat(ChatRequest(query="c", session_id="s2"))

    # s1 第二轮应能看到第一轮历史；s2 独立、无历史
    second_s1_ctx = disp.calls[1]["context"]
    first_s2_ctx = disp.calls[2]["context"]
    assert [t.query for t in second_s1_ctx.history] == ["a"]
    assert first_s2_ctx.history == []


def test_service_response_shape():
    svc = _service()
    resp = svc.handle_chat(ChatRequest(query="你好", session_id="s1"))
    assert resp.text == "回复:你好" and resp.intent == "chitchat" and resp.session_id == "s1"
    assert resp.data is None and "data" not in resp.to_dict()  # 无结构化 data 时不下发


def test_service_passes_through_dict_data():
    """音乐等产出可序列化 dict 的 handler：data 透传给客户端（含 orpheus 深链，step 3.1）。"""

    class MusicDisp(FakeDispatcher):
        def dispatch(self, query, context):
            self.calls.append({"query": query, "context": context})
            return RouteResult(
                text="正在播放：晴天", intent="music_play",
                data={"kind": "music", "deeplink": "orpheus://song/123"},
            )

    resp = _service(MusicDisp()).handle_chat(ChatRequest(query="放晴天", session_id="s1"))
    assert resp.data == {"kind": "music", "deeplink": "orpheus://song/123"}
    assert resp.to_dict()["data"]["deeplink"] == "orpheus://song/123"


def test_service_drops_non_dict_data():
    """富对象（NewsResult 等）非 dict：不下发，保持 phase-1 行为。"""

    class ObjDisp(FakeDispatcher):
        def dispatch(self, query, context):
            self.calls.append({"query": query, "context": context})
            return RouteResult(text="x", intent="news", data=object())

    resp = _service(ObjDisp()).handle_chat(ChatRequest(query="x", session_id="s1"))
    assert resp.data is None and "data" not in resp.to_dict()


def test_real_auth_provider_seam():
    """预留接口：自定义 CredentialProvider 即可替换 mock（将来接真鉴权）。"""

    class StubProvider(CredentialProvider):
        def resolve(self, user_id):
            return Credentials(tripnow_union_id=f"real-{user_id}", mocked=False)

    disp = FakeDispatcher()
    svc = ChatService(dispatcher=disp, store=SessionStore(), credentials=StubProvider())
    svc.handle_chat(ChatRequest(query="x", session_id="s1", user_id="u9"))
    assert disp.calls[0]["context"].union_id == "real-u9"


# ---- HTTP 适配器（真起一个本地 server） ----


@pytest.fixture
def http_server():
    svc = _service()
    httpd = build_http_server(svc, host="127.0.0.1", port=0)  # port=0 让系统选空闲端口
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def _post(base, path, payload, headers=None):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json", **(headers or {})}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read())


def test_http_health(http_server):
    with urllib.request.urlopen(http_server + "/health", timeout=5) as r:
        body = json.loads(r.read())
    # 不带 platform → 默认 pc → 全量能力，含 PC-only 的 music_control
    assert body["status"] == "ok" and "chitchat" in body["capabilities"]
    assert "music_control" in body["capabilities"]


def test_http_health_mobile_hides_pc_only(http_server):
    with urllib.request.urlopen(http_server + "/health?platform=mobile", timeout=5) as r:
        body = json.loads(r.read())
    # 移动端能力清单里不该出现 PC-only 的 music_control，其余能力照常
    assert "music_control" not in body["capabilities"]
    assert "chitchat" in body["capabilities"]


def test_http_health_bad_platform(http_server):
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(http_server + "/health?platform=watch", timeout=5)
    assert ei.value.code == 400


def test_http_chat_ok(http_server):
    status, body = _post(http_server, "/chat", {"query": "你好", "session_id": "s1"})
    assert status == 200 and body["text"] == "回复:你好" and body["intent"] == "chitchat"


def test_http_chat_platform_flows_into_context():
    disp = FakeDispatcher()
    svc = _service(dispatcher=disp)
    httpd = build_http_server(svc, host="127.0.0.1", port=0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        _post(base, "/chat", {"query": "hi", "session_id": "s1", "platform": "mobile"})
        assert disp.calls[-1]["context"].platform == "mobile"
        _post(base, "/chat", {"query": "hi", "session_id": "s2"})  # 不带 → 默认 pc
        assert disp.calls[-1]["context"].platform == "pc"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_http_chat_bad_platform(http_server):
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(http_server, "/chat", {"query": "hi", "session_id": "s1", "platform": "watch"})
    assert ei.value.code == 400


def test_http_chat_bad_request(http_server):
    with pytest.raises(urllib.error.HTTPError) as ei:
        _post(http_server, "/chat", {"session_id": "s1"})  # 缺 query
    assert ei.value.code == 400


def test_http_unknown_path(http_server):
    with pytest.raises(urllib.error.HTTPError) as ei:
        urllib.request.urlopen(http_server + "/nope", timeout=5)
    assert ei.value.code == 404


def test_http_auth_required():
    svc = _service()
    httpd = build_http_server(svc, host="127.0.0.1", port=0, auth_token="secret")
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    try:
        with pytest.raises(urllib.error.HTTPError) as ei:
            _post(base, "/chat", {"query": "hi", "session_id": "s1"})
        assert ei.value.code == 401
        status, body = _post(
            base, "/chat", {"query": "hi", "session_id": "s1"}, headers={"Authorization": "Bearer secret"}
        )
        assert status == 200
    finally:
        httpd.shutdown()
        httpd.server_close()
