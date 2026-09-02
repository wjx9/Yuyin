"""server 层单测：ChatService 核心 + schema 校验 + HTTP 适配器（假 dispatcher，不联网）。"""

from __future__ import annotations

import json
import threading
import urllib.request
import urllib.error

import pytest

from orchestration.task_models import AgentAction, AgentDecision, RequestAnalysis
from routing.handler import IntentSpec, RouteContext, RouteResult
from server.auth import Credentials, CredentialProvider, MockCredentialProvider
from server.http_server import build_http_server
from server.schemas import BadRequest, ChatRequest, ChatResponse
from server.service import ChatService
from server.session import SessionStore

from mcp_skill.client import McpToolClient, McpSkillError
from mcp_skill.handler import MCPHandler
from mcp_skill.manifest import SkillManifest
from mcp_skill.provider import SkillCredentialProvider
from store_client import StoreUnavailable


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

    def visible_specs(self, platform="pc"):
        return [IntentSpec(intent, intent) for intent in self.intents_for(platform)]

    @property
    def intents(self):
        return self.intents_for("pc")

    def dispatch(self, query, context: RouteContext) -> RouteResult:
        self.calls.append({"query": query, "context": context})
        return RouteResult(text=f"回复:{query}", intent="chitchat")

    def execute(self, *, intent, query, context, slots=None):
        # 旧测试桩的具体结果都定义在 dispatch() 覆写中，复用它以保持测试关注点不变。
        return self.dispatch(query, context)


class FakeComposer:
    """隔离 Graph 的总结节点，避免 server 单测访问真实 Gemini。"""

    def compose(self, *, query, intent, tool_text, history):
        return tool_text


class FakeAnalyzer:
    """每轮只回显原始问题，隔离服务端测试的分析模型依赖。"""

    def analyze(self, *, query, history):
        return RequestAnalysis(goal=query)


class FakeDecider:
    """每轮调用一次 chitchat，下一轮结束，隔离决策模型依赖。"""

    def decide(
        self, *, query, analysis, observations, specs, history, remaining_steps, executed_actions
    ):
        if not observations:
            return AgentDecision(actions=[AgentAction("chitchat", query)])
        return AgentDecision(finished=True)


def _service(dispatcher=None, credentials=None) -> ChatService:
    return ChatService(
        dispatcher=dispatcher or FakeDispatcher(),
        composer=FakeComposer(),
        analyzer=FakeAnalyzer(),
        decider=FakeDecider(),
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


class _NewsDisp(FakeDispatcher):
    """命中新闻意图的桩：a2ui 生成层按 intent+text 工作，无需真 CLI。"""

    def dispatch(self, query, context):
        self.calls.append({"query": query, "context": context})
        return RouteResult(text="1. 标题：某新闻\n   来源: 某报", intent="tencent_news_search")


def test_service_builds_a2ui_for_mobile():
    resp = _service(_NewsDisp()).handle_chat(
        ChatRequest(query="美国新闻", session_id="s1", platform="mobile")
    )
    assert resp.a2ui is not None
    assert "createSurface" in resp.a2ui[0]
    assert resp.to_dict()["a2ui"] == resp.a2ui


def test_service_skips_a2ui_for_pc():
    """纯文本端（pc）不产 a2ui：契约不变，也不浪费流量。"""
    resp = _service(_NewsDisp()).handle_chat(
        ChatRequest(query="美国新闻", session_id="s1", platform="pc")
    )
    assert resp.a2ui is None and "a2ui" not in resp.to_dict()


def test_real_auth_provider_seam():
    """预留接口：自定义 CredentialProvider 即可替换 mock（将来接真鉴权）。"""

    class StubProvider(CredentialProvider):
        def resolve(self, user_id):
            return Credentials(tripnow_union_id=f"real-{user_id}", mocked=False)

    disp = FakeDispatcher()
    svc = ChatService(
        dispatcher=disp,
        composer=FakeComposer(),
        analyzer=FakeAnalyzer(),
        decider=FakeDecider(),
        store=SessionStore(),
        credentials=StubProvider(),
    )
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


# ---- P4.2 动态凭证：连接参数构建 + 提供器 + handler 文案 ----


def _byok_manifest() -> SkillManifest:
    return SkillManifest(
        skill_id="region-mcp",
        name="区域天气",
        description="区域天气查询",
        intent="region_forecast",
        entry_tool="get_region_forecast",
        mcp_server={"transport": "http", "url": "http://127.0.0.1:9100/mcp"},
        tools=[
            {
                "name": "get_region_forecast",
                "input_schema": {
                    "type": "object",
                    "properties": {"city": {"type": "string"}},
                },
            }
        ],
        credentials={
            "type": "byok",
            "schema": [
                {
                    "key": "api_key",
                    "label": "API Key",
                    "type": "secret",
                    "required": True,
                    "help": "区域服务密钥",
                    "inject": {"where": "header", "name": "X-API-Key", "prefix": "Bearer "},
                },
                {
                    "key": "region",
                    "label": "区域",
                    "type": "select",
                    "required": True,
                    "options": ["cn", "us"],
                    "inject": {"where": "query", "name": "region"},
                },
                {
                    "key": "endpoint",
                    "label": "自定义端点",
                    "type": "string",
                    "required": False,
                    "inject": {"where": "header", "name": "X-Endpoint"},
                },
            ],
        },
    )


class _FakeCredProvider:
    """只回显预置 values 的凭证提供器（隔离 store_client）。"""

    def __init__(self, values: dict | None = None):
        self._values = values or {}

    def get(self, user_id, skill_id):
        return self._values


def _bare_client(manifest, provider, user_id="u1") -> McpToolClient:
    """绕开 __init__ 起线程，只测 _build_connection_params 纯逻辑。"""
    c = McpToolClient.__new__(McpToolClient)
    c._m = manifest
    c._cred_provider = provider
    c._user_id = user_id
    return c


def test_build_connection_params_type_none():
    m = _byok_manifest()
    m.credentials = {"type": "none"}
    c = _bare_client(m, _FakeCredProvider())
    url, headers = c._build_connection_params()
    assert url == "http://127.0.0.1:9100/mcp" and headers == {}


def test_build_connection_params_rejects_web_or_invalid_url():
    m = _byok_manifest()
    m.mcp_server = {"transport": "http", "url": "handler://flutter/index.html"}
    c = _bare_client(m, _FakeCredProvider())
    with pytest.raises(McpSkillError, match="MCP 地址无效"):
        c._build_connection_params()


def test_mcp_client_connection_is_lazy():
    """装配用户技能时不应立即启动后台网络连接。"""
    client = McpToolClient(_byok_manifest(), credential_provider=_FakeCredProvider())
    try:
        assert client._started is False
        assert client._loop_thread.is_alive() is False
    finally:
        client.close()


def test_build_connection_params_byok_injects_header_and_query():
    c = _bare_client(
        _byok_manifest(), _FakeCredProvider({"api_key": "k123", "region": "cn"})
    )
    url, headers = c._build_connection_params()
    assert headers == {"X-API-Key": "Bearer k123"}  # secret → header，带 prefix
    assert url == "http://127.0.0.1:9100/mcp?region=cn"  # select → query，重写 URL


def test_build_connection_params_optional_missing_skipped():
    """非必填字段未配置：不注入（不发空头），必填字段照常注入。"""
    c = _bare_client(_byok_manifest(), _FakeCredProvider({"api_key": "k1", "region": "us"}))
    url, headers = c._build_connection_params()
    assert headers == {"X-API-Key": "Bearer k1"}
    assert "X-Endpoint" not in headers and "endpoint" not in url


def test_build_connection_params_missing_required_raises():
    c = _bare_client(_byok_manifest(), _FakeCredProvider({"api_key": "k1"}))  # 缺 region
    with pytest.raises(McpSkillError, match="缺少必填凭证：区域"):
        c._build_connection_params()


def test_build_connection_params_no_provider_raises():
    c = _bare_client(_byok_manifest(), None)
    with pytest.raises(McpSkillError, match="未配置凭证提供器"):
        c._build_connection_params()


def test_credential_provider_returns_values():
    store = type("S", (), {"get_credentials_plain": lambda self, u, s: {"configured": True, "values": {"api_key": "k"}}})()
    assert SkillCredentialProvider(store).get("u1", "region-mcp") == {"api_key": "k"}


def test_credential_provider_unconfigured_returns_empty():
    store = type("S", (), {"get_credentials_plain": lambda self, u, s: {"configured": False, "values": {}}})()
    assert SkillCredentialProvider(store).get("u1", "region-mcp") == {}


def test_credential_provider_store_down_raises_mcp_error():
    store = type("S", (), {"get_credentials_plain": lambda self, u, s: (_ for _ in ()).throw(StoreUnavailable("挂"))})()
    with pytest.raises(McpSkillError, match="凭证服务不可用"):
        SkillCredentialProvider(store).get("u1", "region-mcp")


class _FakeCallClient:
    """call_tool 直接抛预设异常（隔离真实 MCP 连接）。"""

    def __init__(self, exc=None):
        self._exc = exc

    def call_tool(self, name, arguments, timeout=30):
        if self._exc:
            raise self._exc
        return "ok"


def _handler_with_client(exc=None) -> MCPHandler:
    return MCPHandler(_byok_manifest(), _FakeCallClient(exc))


def test_handler_missing_cred_friendly_message():
    r = _handler_with_client(McpSkillError("缺少必填凭证：区域")).handle(
        "深圳", RouteContext()
    )
    assert r.status == "failed"
    assert r.text == "需要先配置「区域天气」的凭证：区域"


def test_handler_other_mcp_error_keeps_unavailable_text():
    r = _handler_with_client(McpSkillError("tool 超时")).handle("深圳", RouteContext())
    assert r.status == "failed"
    assert r.text == "区域天气 暂不可用：tool 超时"
