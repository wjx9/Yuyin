"""分流层单测：分类器（关键词+Gemini 兜底）、分发器、各 Handler（用假对象隔离网络）。"""

from __future__ import annotations

from routing.classifier import GeminiClassifier, KeywordClassifier, Route
from routing.dispatcher import Dispatcher
from routing.gemini import FunctionCall, GeminiAnswer, GeminiClient, GeminiError, Source
from routing.handler import Handler, IntentSpec, RouteContext, RouteResult, SlotSpec
from routing.handlers.chitchat import ChitchatHandler
from routing.handlers.kuaidi100 import ExpressTrackingHandler


# ---- 测试替身 ----

class FakeGemini:
    """假 GeminiClient：generate/answer 回固定文本；choose_function 回固定 FunctionCall。

    call 便捷写法：传 str 等价于 FunctionCall(str)（意图命中、无槽位）。
    """

    def __init__(self, reply="", call=None, raise_error=False, sources=None):
        self._reply = reply
        self._call = FunctionCall(call) if isinstance(call, str) else call
        self._raise = raise_error
        self._sources = sources or []
        self.last_prompt = None
        self.last_system = None
        self.last_history = None
        self.last_grounded = None
        self.last_declarations = None

    def generate(self, prompt, *, system=None, temperature=0.0, history=None):
        self.last_prompt = prompt
        self.last_system = system
        self.last_history = history
        if self._raise:
            raise GeminiError("down")
        return self._reply

    def answer(self, prompt, *, system=None, temperature=0.0, history=None, grounded=False):
        self.last_prompt = prompt
        self.last_system = system
        self.last_history = history
        self.last_grounded = grounded
        if self._raise:
            raise GeminiError("down")
        return GeminiAnswer(text=self._reply, sources=list(self._sources))

    def choose_function(self, prompt, *, declarations, system=None, temperature=0.0):
        self.last_prompt = prompt
        self.last_system = system
        self.last_declarations = declarations
        if self._raise:
            raise GeminiError("down")
        return self._call


class EchoHandler(Handler):
    def __init__(self, intent, description="desc"):
        self.intent = intent
        self.description = description

    def handle(self, query, context):
        return RouteResult(text=f"{self.intent}:{query}", intent=self.intent)


SPECS = [
    IntentSpec("chitchat", "闲聊"),
    IntentSpec("express_tracking", "查快递"),
    IntentSpec("amap", "地图"),
    IntentSpec("tripnow_public", "公开出行"),
    IntentSpec("news", "搜新闻", slots=(
        SlotSpec("keyword", "string", "检索词"),
        SlotSpec("limit", "integer", "条数"),
    )),
]


# ---- KeywordClassifier ----

def test_keyword_matches_express():
    c = KeywordClassifier()
    assert c.classify("我的快递到哪了", SPECS, default="chitchat") == Route("express_tracking")


def test_keyword_matches_amap():
    c = KeywordClassifier()
    assert c.classify("附近有什么好吃的", SPECS, default="chitchat").intent == "amap"


def test_keyword_falls_back_to_default():
    c = KeywordClassifier()
    assert c.classify("今天天气真好啊", SPECS, default="chitchat").intent == "chitchat"


def test_keyword_ignores_unregistered_intent():
    # amap 未注册时不应命中 amap
    specs = [IntentSpec("chitchat", "闲聊")]
    c = KeywordClassifier()
    assert c.classify("附近的咖啡", specs, default="chitchat").intent == "chitchat"


# ---- GeminiClassifier（function calling：一次调用出 意图+槽位）----

def test_gemini_classifier_uses_function_call():
    g = FakeGemini(call="amap")
    c = GeminiClassifier(g)
    assert c.classify("带我去哪", SPECS, default="chitchat") == Route("amap")
    # 每个意图编译成一个 function 声明，description 原样带上
    names = [d["name"] for d in g.last_declarations]
    assert names == [s.id for s in SPECS]
    assert g.last_declarations[2]["description"] == "地图"


def test_gemini_declarations_carry_slot_schema():
    g = FakeGemini(call="chitchat")
    GeminiClassifier(g).classify("x", SPECS, default="chitchat")
    news = next(d for d in g.last_declarations if d["name"] == "news")
    assert news["parameters"]["properties"]["keyword"] == {"type": "string", "description": "检索词"}
    assert news["parameters"]["properties"]["limit"]["type"] == "integer"
    # 无槽位的意图不带 parameters（空 schema 徒增 token 且部分模型不接受）
    assert "parameters" not in g.last_declarations[0]


def test_gemini_classifier_returns_cleaned_slots():
    g = FakeGemini(call=FunctionCall("news", {"keyword": " 深圳 ", "limit": 5.0, "bogus": 1}))
    route = GeminiClassifier(g).classify("看看深圳的新闻来5条", SPECS, default="chitchat")
    # 声明外的键被丢弃；string 去空白；integer 收敛 float 整数
    assert route == Route("news", {"keyword": "深圳", "limit": 5})


def test_gemini_classifier_drops_ill_typed_slots():
    g = FakeGemini(call=FunctionCall("news", {"keyword": "", "limit": "五"}))
    route = GeminiClassifier(g).classify("新闻", SPECS, default="chitchat")
    assert route == Route("news", {})  # 类型不对的槽位丢弃，交给 handler 兜底


def test_gemini_system_prompt_carries_default_for_fallback():
    g = FakeGemini(call="chitchat")
    GeminiClassifier(g).classify("含糊的输入", SPECS, default="chitchat")
    # system 指令里告知模型：拿不准就选兜底技能
    assert "chitchat" in g.last_system and "兜底" in g.last_system


def test_gemini_classifier_falls_back_on_error():
    g = FakeGemini(raise_error=True)
    c = GeminiClassifier(g, fallback=KeywordClassifier())
    # Gemini 挂了 -> 关键词兜底 -> 命中快递
    assert c.classify("快递单号查询", SPECS, default="chitchat").intent == "express_tracking"


def test_gemini_classifier_falls_back_on_unknown_function():
    g = FakeGemini(call="这不是任何一个id")
    c = GeminiClassifier(g, fallback=KeywordClassifier())
    assert c.classify("普通聊天", SPECS, default="chitchat").intent == "chitchat"


def test_gemini_classifier_falls_back_when_no_function_call():
    # mode=ANY 下模型极少数情况仍可能不回 functionCall（choose_function 返回 None）
    g = FakeGemini(call=None)
    c = GeminiClassifier(g, fallback=KeywordClassifier())
    assert c.classify("我的快递到哪了", SPECS, default="chitchat").intent == "express_tracking"


# ---- Dispatcher ----

def test_dispatcher_routes_to_classified_handler():
    handlers = [EchoHandler("chitchat"), EchoHandler("amap")]
    g = FakeGemini(call="amap")
    d = Dispatcher(handlers, GeminiClassifier(g), default_intent="chitchat")
    result = d.dispatch("找路线", RouteContext())
    assert result.intent == "amap"
    assert result.text == "amap:找路线"


def test_dispatcher_collects_intents_for_classifier():
    handlers = [EchoHandler("chitchat"), EchoHandler("amap", "地图周边")]
    g = FakeGemini(call="amap")
    Dispatcher(handlers, GeminiClassifier(g), default_intent="chitchat").classify("x")
    decls = {d["name"]: d for d in g.last_declarations}
    assert decls["amap"]["description"] == "地图周边"


def test_dispatcher_passes_slots_to_handler_context():
    seen = {}

    class SlottedHandler(Handler):
        intent = "news"
        description = "搜新闻"
        slots = (SlotSpec("keyword", "string", "检索词"),)

        def handle(self, query, context):
            seen.update(context.slots)
            return RouteResult(text="ok", intent=self.intent)

    g = FakeGemini(call=FunctionCall("news", {"keyword": "深圳"}))
    d = Dispatcher([EchoHandler("chitchat"), SlottedHandler()], GeminiClassifier(g), default_intent="chitchat")
    d.dispatch("看看深圳的新闻", RouteContext())
    assert seen == {"keyword": "深圳"}


def test_dispatcher_clears_slots_when_falling_back():
    # 分类命中不可用意图时回退默认，槽位是按原意图抽的，不得带给默认 handler
    from routing.classifier import IntentClassifier

    class GhostClassifier(IntentClassifier):
        def classify(self, query, intents, *, default):
            return Route("ghost_intent", {"keyword": "深圳"})  # 未注册的意图 + 残留槽位

    seen = {"marker": "not-touched"}

    class SpyChitchat(Handler):
        intent = "chitchat"
        description = "闲聊"

        def handle(self, query, context):
            seen.clear()
            seen.update(context.slots)
            return RouteResult(text="ok", intent=self.intent)

    d = Dispatcher([SpyChitchat()], GhostClassifier(), default_intent="chitchat")
    d.dispatch("x", RouteContext())
    assert seen == {}


def _pc_only_dispatcher(gemini):
    ctrl = EchoHandler("music_control", "暂停/切歌/音量")
    ctrl.pc_only = True
    handlers = [EchoHandler("chitchat"), ctrl]
    return Dispatcher(handlers, GeminiClassifier(gemini), default_intent="chitchat")


def test_pc_only_intent_hidden_from_mobile_capabilities():
    d = _pc_only_dispatcher(FakeGemini(call="chitchat"))
    assert "music_control" in d.intents_for("pc")
    assert "music_control" not in d.intents_for("mobile")
    assert d.intents == d.intents_for("pc")  # 默认 pc


def test_pc_only_intent_not_offered_to_mobile_classifier():
    g = FakeGemini(call="chitchat")
    _pc_only_dispatcher(g).classify("暂停", platform="mobile")
    # 分类器压根看不到它：function 声明里没有 music_control
    assert all(d["name"] != "music_control" for d in g.last_declarations)


def test_mobile_dispatch_falls_back_when_classifier_forces_pc_only():
    # 防御性兜底：即便分类器（如关键词兜底）硬命中 pc_only，mobile 请求也不落到它，回退默认
    g = FakeGemini(call="music_control")
    d = _pc_only_dispatcher(g)
    result = d.dispatch("暂停", RouteContext(platform="mobile"))
    assert result.intent == "chitchat"


def test_pc_dispatch_still_routes_to_pc_only():
    g = FakeGemini(call="music_control")
    d = _pc_only_dispatcher(g)
    result = d.dispatch("暂停", RouteContext(platform="pc"))
    assert result.intent == "music_control"


def test_dispatcher_rejects_unknown_default():
    try:
        Dispatcher([EchoHandler("a")], GeminiClassifier(FakeGemini()), default_intent="missing")
    except ValueError:
        return
    raise AssertionError("应当因 default_intent 不存在而报错")


# ---- Handlers ----

def test_chitchat_handler_uses_gemini():
    h = ChitchatHandler(FakeGemini(reply="你好呀"))
    assert h.handle("hi", RouteContext()).text == "你好呀"


class _FakeResp:
    ok = True
    status_code = 200

    def json(self):
        return {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}


class _RecordingSession:
    def __init__(self):
        self.posted_json = None

    def post(self, url, headers=None, json=None, timeout=None):
        self.posted_json = json
        return _FakeResp()


def test_gemini_expands_history_into_contents():
    sess = _RecordingSession()
    client = GeminiClient("key", session=sess)
    client.generate("现在呢", history=[("我叫小明", "你好小明")])
    contents = sess.posted_json["contents"]
    assert contents == [
        {"role": "user", "parts": [{"text": "我叫小明"}]},
        {"role": "model", "parts": [{"text": "你好小明"}]},
        {"role": "user", "parts": [{"text": "现在呢"}]},
    ]


def test_chitchat_handler_forwards_history():
    from routing.history import Turn

    gem = FakeGemini(reply="ok")
    h = ChitchatHandler(gem)
    ctx = RouteContext(history=[Turn("我叫小明", "你好小明"), Turn("今天天气", "晴")])
    h.handle("我刚才说我叫什么", ctx)
    assert gem.last_history == [("我叫小明", "你好小明"), ("今天天气", "晴")]


def test_chitchat_handler_degrades_on_error():
    h = ChitchatHandler(FakeGemini(raise_error=True))
    assert "不可用" in h.handle("hi", RouteContext()).text


def test_chitchat_enables_grounding():
    gem = FakeGemini(reply="股价约 275 美元")
    ChitchatHandler(gem).handle("apple 股价", RouteContext())
    assert gem.last_grounded is True


def test_chitchat_appends_sources_when_grounded():
    gem = FakeGemini(reply="股价约 275 美元", sources=[Source("robinhood.com", "https://x")])
    res = ChitchatHandler(gem).handle("apple 股价", RouteContext())
    assert "来源（联网检索）" in res.text
    assert "robinhood.com" in res.text
    assert res.data == [Source("robinhood.com", "https://x")]


def test_chitchat_no_source_section_without_grounding():
    gem = FakeGemini(reply="你好")
    res = ChitchatHandler(gem).handle("你好", RouteContext())
    assert "来源" not in res.text
    assert res.data is None


def test_gemini_grounded_adds_search_tool_and_parses_sources():
    class _GroundResp:
        ok = True
        status_code = 200

        def json(self):
            return {
                "candidates": [{
                    "content": {"parts": [{"text": "约 275 美元"}]},
                    "groundingMetadata": {
                        "groundingChunks": [
                            {"web": {"title": "robinhood.com", "uri": "https://a"}},
                            {"web": {"title": "robinhood.com", "uri": "https://a"}},  # 去重
                            {"web": {"title": "fidelity.com", "uri": "https://b"}},
                        ]
                    },
                }]
            }

    class _Sess:
        def __init__(self):
            self.posted = None

        def post(self, url, headers=None, json=None, timeout=None):
            self.posted = json
            return _GroundResp()

    sess = _Sess()
    ans = GeminiClient("key", session=sess).answer("apple 股价", grounded=True)
    assert sess.posted["tools"] == [{"google_search": {}}]
    assert ans.text == "约 275 美元"
    assert ans.sources == [Source("robinhood.com", "https://a"), Source("fidelity.com", "https://b")]


def test_gemini_choose_function_posts_declarations_and_parses_call():
    class _FcResp:
        ok = True
        status_code = 200

        def json(self):
            return {"candidates": [{"content": {"parts": [
                {"functionCall": {"name": "news", "args": {"keyword": "深圳"}}},
            ]}}]}

    class _Sess:
        def __init__(self):
            self.posted = None

        def post(self, url, headers=None, json=None, timeout=None):
            self.posted = json
            return _FcResp()

    sess = _Sess()
    decls = [{"name": "news", "description": "搜新闻"}]
    fc = GeminiClient("key", session=sess).choose_function("看看深圳的新闻", declarations=decls)
    assert sess.posted["tools"] == [{"functionDeclarations": decls}]
    # mode=ANY：强制模型必须调用一个函数，一次拿到 意图+槽位
    assert sess.posted["toolConfig"] == {"functionCallingConfig": {"mode": "ANY"}}
    assert fc == FunctionCall("news", {"keyword": "深圳"})


def test_gemini_choose_function_returns_none_on_text_reply():
    # 极少数情况模型不回 functionCall 只回文本 → None，由调用方兜底
    sess = _RecordingSession()  # 其 json() 只含 text part
    fc = GeminiClient("key", session=sess).choose_function("x", declarations=[{"name": "a", "description": "d"}])
    assert fc is None


def test_chitchat_system_prompt_lists_real_capabilities():
    g = FakeGemini(reply="我能查火车票…")
    h = ChitchatHandler(g)
    h.set_capabilities([
        IntentSpec("chitchat", "日常闲聊"),
        IntentSpec("express_tracking", "查询快递/物流轨迹"),
        IntentSpec("amap", "地图与位置服务"),
    ])
    h.handle("你有哪些能力?", RouteContext())
    # system prompt 里带上了真实任务能力、排除了 chitchat 自身描述
    assert "查询快递/物流轨迹" in g.last_system
    assert "地图与位置服务" in g.last_system
    assert "通用语言模型" in g.last_system  # 明确要求不要这么说


def test_chitchat_without_capabilities_uses_base_prompt():
    g = FakeGemini(reply="ok")
    ChitchatHandler(g).handle("hi", RouteContext())
    assert "真实能力清单" not in g.last_system


class FakeExpressService:
    def track(self, num, *, com=None, phone=None):
        from kuaidi100_client.models import TrackResult

        return TrackResult.from_dict(num, {
            "nu": num, "com": "shunfeng", "state": "3",
            "data": [{"time": "t", "context": "已签收"}],
        })


def test_express_handler_extracts_num_and_tracks():
    h = ExpressTrackingHandler(FakeExpressService())
    r = h.handle("帮我查下 SF1234567890 这个快递", RouteContext())
    assert "已签收" in r.text


def test_express_handler_without_num_prompts():
    h = ExpressTrackingHandler(FakeExpressService())
    r = h.handle("我的快递到哪了", RouteContext())
    assert "单号" in r.text


# ---- TripNow 个人能力：mock OAuth ----

def test_personal_handler_uses_context_union_id_without_mock_notice(fake_transport):
    from routing.handlers.tripnow import TripNowPersonalHandler

    h = TripNowPersonalHandler(fake_transport, mock_union_id="TEST_ACCOUNT_ID")
    r = h.handle("我的行程", RouteContext(union_id="REAL_ID"))
    assert "mock" not in r.text                       # 真身份不提示 mock
    assert fake_transport.last_request.union_id == "REAL_ID"


def test_personal_handler_falls_back_to_mock_account(fake_transport):
    from routing.handlers.tripnow import TripNowPersonalHandler

    h = TripNowPersonalHandler(fake_transport, mock_union_id="TEST_ACCOUNT_ID")
    r = h.handle("我的行程", RouteContext())            # context 无 union_id
    assert "mock" in r.text and "测试账号" in r.text     # 提示走了 mock 鉴权
    assert fake_transport.last_request.union_id == "TEST_ACCOUNT_ID"
    assert "TEST_ACCOUNT_ID" not in r.text             # 完整 id 应脱敏，不直接打印


def test_personal_handler_without_any_id_prompts_config(fake_transport):
    from routing.handlers.tripnow import TripNowPersonalHandler

    h = TripNowPersonalHandler(fake_transport, mock_union_id=None)
    r = h.handle("我的行程", RouteContext())
    assert "TRIPNOW_UNION_ID" in r.text or "--union-id" in r.text


# ---- 路由日志 ----

def test_dispatch_logs_routing_decision(caplog):
    import logging

    handlers = [EchoHandler("chitchat"), EchoHandler("amap")]
    d = Dispatcher(handlers, GeminiClassifier(FakeGemini(call="amap")), default_intent="chitchat")
    with caplog.at_level(logging.INFO, logger="routing.dispatcher"):
        d.dispatch("找路线", RouteContext())
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "'amap'" in text                       # 命中技能 id 出现在日志
    assert "EchoHandler" in text                  # 也记录了 Handler 类名


def test_classifier_warns_on_gemini_failure(caplog):
    import logging

    c = GeminiClassifier(FakeGemini(raise_error=True), fallback=KeywordClassifier())
    with caplog.at_level(logging.WARNING, logger="routing.classifier"):
        c.classify("快递单号查询", SPECS, default="chitchat")
    assert any("回退" in r.getMessage() for r in caplog.records)
