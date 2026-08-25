from __future__ import annotations

import pytest

from orchestration.planner import (
    AgentDecisionError,
    GeminiActionDecider,
    GeminiRequestAnalyzer,
)
from orchestration.factory import _PLANNABLE_INTENTS
from orchestration.task_models import RequestAnalysis
from routing.gemini import GeminiError
from routing.handler import IntentSpec, SlotSpec


SPECS = [
    IntentSpec("chitchat", "闲聊"),
    IntentSpec("amap_weather_live", "实时天气", (SlotSpec("city", "string", "城市"),)),
    IntentSpec("amap_transit", "公交路线", (SlotSpec("origin", "string", "起点", required=True),)),
    IntentSpec("exa_search", "网页搜索", (SlotSpec("limit", "integer", "条数"),)),
]
ALLOWED = {"chitchat", "amap_weather_live", "amap_transit", "exa_search"}


class FakeGemini:
    def __init__(self, replies: list[str] | None = None, error: bool = False):
        self.replies = list(replies or [])
        self.error = error
        self.calls = []

    def generate(
        self,
        prompt,
        *,
        system=None,
        temperature=0.0,
        history=None,
        response_mime_type=None,
    ):
        self.calls.append(
            {
                "prompt": prompt,
                "system": system,
                "temperature": temperature,
                "history": history,
                "response_mime_type": response_mime_type,
            }
        )
        if self.error:
            raise GeminiError("down")
        return self.replies.pop(0)


def test_analyzer_preserves_explicit_information_with_json_mode():
    gemini = FakeGemini(
        [
            '{"goal":"完成用户请求","known":["明确条件"],'
            '"constraints":["已说明限制"]}'
        ]
    )

    analysis = GeminiRequestAnalyzer(gemini).analyze(
        query="帮我处理这个请求", history=[]
    )

    assert analysis.known == ["明确条件"]
    assert gemini.calls[0]["response_mime_type"] == "application/json"


def test_decider_retries_once_when_first_json_is_not_an_executable_action():
    gemini = FakeGemini(
        [
            '{"actions":[{"intent":"unknown","query":"x","slots":{}}],"finish":false}',
            '{"actions":[{"intent":"amap_weather_live","query":"深圳天气",'
            '"slots":{"city":"深圳"}}],"finish":false,"reason":"","follow_up":""}',
        ]
    )
    decider = GeminiActionDecider(gemini, ALLOWED)

    decision = decider.decide(
        query="深圳天气怎么样",
        analysis=RequestAnalysis(goal="查询天气"),
        observations=[],
        specs=SPECS,
        history=[],
        remaining_steps=3,
        executed_actions=[],
    )

    assert decision.actions[0].intent == "amap_weather_live"
    assert len(gemini.calls) == 2
    assert "上一条输出未通过协议校验" in gemini.calls[1]["prompt"]
    assert all(call["response_mime_type"] == "application/json" for call in gemini.calls)


def test_decider_rejects_invalid_decisions_after_one_repair_attempt():
    decider = GeminiActionDecider(FakeGemini(["{}", "{}"]), ALLOWED)

    with pytest.raises(AgentDecisionError, match="非法动作"):
        decider.decide(
            query="任意请求",
            analysis=RequestAnalysis(goal="任意请求"),
            observations=[],
            specs=SPECS,
            history=[],
            remaining_steps=3,
            executed_actions=[],
        )


def test_decider_repairs_a_repeated_action_instead_of_returning_it_again():
    gemini = FakeGemini(
        [
            '{"actions":[{"intent":"amap_weather_live","query":"深圳天气",'
            '"slots":{"city":"深圳"}}],"finish":false,"reason":"","follow_up":""}',
            '{"actions":[{"intent":"exa_search","query":"深圳天气说明",'
            '"slots":{}}],"finish":false,"reason":"","follow_up":""}',
        ]
    )
    decider = GeminiActionDecider(gemini, ALLOWED)

    decision = decider.decide(
        query="深圳天气",
        analysis=RequestAnalysis(goal="查询天气"),
        observations=[{"intent": "amap_weather_live", "status": "success", "text": "晴"}],
        specs=SPECS,
        history=[],
        remaining_steps=2,
        executed_actions=["amap_weather_live|深圳天气|city=深圳"],
    )

    assert decision.actions[0].intent == "exa_search"
    assert len(gemini.calls) == 2
    assert "不能重复已完成调用" in gemini.calls[1]["prompt"]


def test_decider_accepts_only_a_follow_up_for_a_declared_required_slot():
    gemini = FakeGemini(
        [
            '{"actions":[],"finish":true,"reason":"缺少输入",'
            '"follow_up":{"intent":"amap_transit","slot":"origin"}}'
        ]
    )

    decision = GeminiActionDecider(gemini, ALLOWED).decide(
        query="任意请求",
        analysis=RequestAnalysis(goal="完成请求"),
        observations=[],
        specs=SPECS,
        history=[],
        remaining_steps=3,
        executed_actions=[],
    )

    assert (decision.follow_up_intent, decision.follow_up_slot) == (
        "amap_transit",
        "origin",
    )


def test_decider_keeps_an_empty_decision_without_retrying_the_model():
    gemini = FakeGemini(
        [
            '{"actions":[],"finish":true,"reason":"","follow_up":null}',
        ]
    )
    decision = GeminiActionDecider(gemini, ALLOWED).decide(
        query="任意请求",
        analysis=RequestAnalysis(goal="完成请求", known=["已知信息"]),
        observations=[],
        specs=SPECS,
        history=[],
        remaining_steps=3,
        executed_actions=[],
    )

    assert decision.actions == []
    assert decision.finished is True
    assert len(gemini.calls) == 1


def test_calendar_create_is_available_to_the_planner():
    assert "calendar_create" in _PLANNABLE_INTENTS


def test_decider_accepts_a_calendar_action_from_the_allowed_capabilities():
    gemini = FakeGemini(
        [
            '{"actions":[{"intent":"calendar_create","query":"创建下班日程",'
            '"slots":{"title":"下班","start_time":"2026-08-25T19:00:00"}}],'
            '"finish":true,"reason":"已准备创建","follow_up":null}'
        ]
    )
    spec = IntentSpec(
        "calendar_create",
        "创建手机日程",
        (
            SlotSpec("title", "string", "标题", required=True),
            SlotSpec("start_time", "string", "开始时间", required=True),
        ),
    )

    decision = GeminiActionDecider(gemini, _PLANNABLE_INTENTS).decide(
        query="今天晚上七点创建一个下班日程",
        analysis=RequestAnalysis(goal="创建一个下班日程", known=["今晚七点"]),
        observations=[],
        specs=[spec],
        history=[],
        remaining_steps=3,
        executed_actions=[],
    )

    assert len(decision.actions) == 1
    assert decision.actions[0].intent == "calendar_create"
    assert decision.actions[0].slots["title"] == "下班"
