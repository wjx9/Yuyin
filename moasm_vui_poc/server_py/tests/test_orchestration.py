from __future__ import annotations

import logging

from orchestration.graph import AssistantGraph
from orchestration.planner import AgentDecisionError
from orchestration.task_models import AgentAction, AgentDecision, RequestAnalysis
from routing.classifier import Route
from routing.handler import IntentSpec, RouteContext, RouteResult, SlotSpec


class FakeDispatcher:
    def __init__(self, results_by_intent: dict[str, RouteResult | Exception]):
        self.results_by_intent = results_by_intent
        self.execute_calls = []
        self.classify_calls = []
        self._specs = [
            IntentSpec("chitchat", "闲聊"),
            IntentSpec("amap_weather_live", "实时天气", (SlotSpec("city", "string", "城市"),)),
            IntentSpec("amap_transit", "公交路线", (SlotSpec("origin", "string", "起点", required=True),)),
            IntentSpec("exa_search", "网页搜索"),
        ]

    @property
    def intents(self):
        return [spec.id for spec in self._specs]

    @property
    def specs(self):
        return list(self._specs)

    def intents_for(self, platform="pc"):
        return self.intents

    def visible_specs(self, platform="pc"):
        return list(self._specs)

    def classify(self, query, platform="pc", history=None):
        self.classify_calls.append((query, platform, history))
        return Route("amap_weather_live", {"city": "深圳"})

    def execute(self, *, intent, query, context, slots=None):
        self.execute_calls.append(
            {"intent": intent, "query": query, "slots": slots or {}, "context": context}
        )
        result = self.results_by_intent[intent]
        if isinstance(result, Exception):
            raise result
        return result


class FakeAnalyzer:
    def __init__(self, analysis: RequestAnalysis | None = None):
        self.analysis = analysis
        self.calls = []

    def analyze(self, *, query, history):
        self.calls.append({"query": query, "history": history})
        return self.analysis or RequestAnalysis(goal=query, known=[query])


class FakeDecider:
    def __init__(self, decisions: list[AgentDecision]):
        self.decisions = list(decisions)
        self.calls = []

    def decide(
        self, *, query, analysis, observations, specs, history, remaining_steps, executed_actions
    ):
        self.calls.append(
            {
                "query": query,
                "analysis": analysis,
                "observations": observations,
                "specs": specs,
                "history": history,
                "remaining_steps": remaining_steps,
                "executed_actions": executed_actions,
            }
        )
        return self.decisions.pop(0)


class FakeComposer:
    def __init__(self):
        self.calls = []

    def compose(self, *, query, intent, tool_text, history):
        self.calls.append(
            {"query": query, "intent": intent, "tool_text": tool_text, "history": history}
        )
        return "整理后的最终回答"


class FailingDecider:
    def decide(self, **_kwargs):
        raise AgentDecisionError("决策格式错误")


def _graph(dispatcher, decisions, composer=None, analyzer=None):
    return AssistantGraph(
        dispatcher,
        composer or FakeComposer(),
        analyzer or FakeAnalyzer(),
        FakeDecider(decisions),
    )


def test_graph_analyzes_then_executes_a_batch_before_finishing():
    dispatcher = FakeDispatcher(
        {"amap_weather_live": RouteResult(text="深圳：晴，28 摄氏度", intent="amap_weather_live")}
    )
    composer = FakeComposer()
    graph = _graph(
        dispatcher,
        [
            AgentDecision(actions=[AgentAction("amap_weather_live", "深圳现在天气", {"city": "深圳"})]),
            AgentDecision(finished=True, reason="天气已查到"),
        ],
        composer,
    )

    result = graph.run("深圳现在天气怎么样", RouteContext())

    assert dispatcher.classify_calls == []
    assert dispatcher.execute_calls[0]["intent"] == "amap_weather_live"
    assert dispatcher.execute_calls[0]["slots"] == {"city": "深圳"}
    assert "深圳：晴，28 摄氏度" in composer.calls[0]["tool_text"]
    assert result.text == "整理后的最终回答"


def test_graph_skips_second_decision_when_batch_is_terminal():
    dispatcher = FakeDispatcher(
        {"amap_weather_live": RouteResult(text="深圳：晴", intent="amap_weather_live")}
    )
    graph = _graph(
        dispatcher,
        [
            AgentDecision(
                actions=[AgentAction("amap_weather_live", "深圳天气")],
                finished=True,
            )
        ],
    )

    graph.run("深圳天气怎么样", RouteContext())

    assert len(graph._decider.calls) == 1
    assert len(dispatcher.execute_calls) == 1


def test_graph_exposes_mobile_location_as_a_route_origin_fact():
    dispatcher = FakeDispatcher({})
    decider = FakeDecider([AgentDecision(finished=True)])
    graph = AssistantGraph(
        dispatcher,
        FakeComposer(),
        FakeAnalyzer(RequestAnalysis(goal="去目的地", known=["目的地"])),
        decider,
    )

    graph.run(
        "去目的地怎么走",
        RouteContext(platform="mobile", location="113.9,22.5"),
    )

    known = decider.calls[0]["analysis"].known
    assert "系统已提供手机当前位置，可作为未明确说明的路线起点" in known


def test_graph_executes_independent_actions_in_one_batch_then_observes_together():
    dispatcher = FakeDispatcher(
        {
            "amap_weather_live": RouteResult(text="深圳：晴", intent="amap_weather_live"),
            "exa_search": RouteResult(text="酒店：A 酒店", intent="exa_search"),
        }
    )
    graph = _graph(
        dispatcher,
        [
            AgentDecision(
                actions=[
                    AgentAction("amap_weather_live", "深圳天气"),
                    AgentAction("exa_search", "深圳酒店"),
                ]
            ),
            AgentDecision(finished=True),
        ],
    )

    graph.run("看深圳天气和酒店", RouteContext())

    assert {call["intent"] for call in dispatcher.execute_calls} == {
        "amap_weather_live",
        "exa_search",
    }
    assert len(graph._decider.calls[1]["observations"]) == 2


def test_graph_finishes_honestly_when_no_tool_can_continue():
    dispatcher = FakeDispatcher({})
    analyzer = FakeAnalyzer(
        RequestAnalysis(goal="完成请求")
    )
    graph = _graph(
        dispatcher,
        [AgentDecision(finished=True, reason="缺少必要条件")],
        analyzer=analyzer,
    )

    result = graph.run("帮我完成请求", RouteContext())

    assert dispatcher.execute_calls == []
    assert "目前没有查到足以可靠完成该请求的信息" in result.text
    assert "缺少必要条件" not in result.text


def test_graph_does_not_fall_back_to_legacy_classifier_when_decision_fails():
    dispatcher = FakeDispatcher(
        {"amap_weather_live": RouteResult(text="不应执行", intent="amap_weather_live")}
    )
    graph = AssistantGraph(
        dispatcher,
        FakeComposer(),
        FakeAnalyzer(RequestAnalysis(goal="完成请求")),
        FailingDecider(),
    )

    result = graph.run("任意请求", RouteContext())

    assert dispatcher.classify_calls == []
    assert dispatcher.execute_calls == []
    assert "目前没有查到足以可靠完成该请求的信息" in result.text


def test_graph_passes_only_explicit_follow_up_to_the_composer():
    dispatcher = FakeDispatcher(
        {"amap_weather_live": RouteResult(text="杭州：小雨", intent="amap_weather_live")}
    )
    composer = FakeComposer()
    graph = _graph(
        dispatcher,
        [
            AgentDecision(actions=[AgentAction("amap_weather_live", "杭州天气")]),
            AgentDecision(
                finished=True,
                reason="已达到本轮工具调用上限",
                follow_up_intent="amap_transit",
                follow_up_slot="origin",
            ),
        ],
        composer,
    )

    graph.run("周末去杭州", RouteContext())

    tool_text = composer.calls[0]["tool_text"]
    assert "【待补充信息】" in tool_text
    assert "请补充：起点" in tool_text
    assert "已达到本轮工具调用上限" not in tool_text


def test_graph_answers_from_context_without_calling_chitchat():
    dispatcher = FakeDispatcher({})
    composer = FakeComposer()
    from routing.history import Turn

    context = RouteContext(
        history=[Turn("我在哪里", "我在广东省深圳市南山区。")]
    )
    graph = _graph(
        dispatcher,
        [AgentDecision(finished=True, direct_answer="上一轮位置来自手机 GPS，再由地图服务转换为地址。")],
        composer,
    )

    result = graph.run("你怎么获取的", context)

    assert dispatcher.execute_calls == []
    assert composer.calls[0]["intent"] == "agent"
    assert "手机 GPS" in composer.calls[0]["tool_text"]
    assert result.text == "整理后的最终回答"


def test_graph_keeps_other_results_when_one_batch_action_raises():
    AuthError = type("AuthError", (Exception,), {})
    dispatcher = FakeDispatcher(
        {
            "amap_weather_live": AuthError("401 with a sensitive request URL"),
            "exa_search": RouteResult(text="酒店：A 酒店", intent="exa_search"),
        }
    )
    composer = FakeComposer()
    graph = _graph(
        dispatcher,
        [
            AgentDecision(
                actions=[
                    AgentAction("amap_weather_live", "深圳天气"),
                    AgentAction("exa_search", "深圳酒店"),
                ]
            ),
            AgentDecision(finished=True),
        ],
        composer,
    )

    graph.run("看深圳天气和酒店", RouteContext())

    assert len(dispatcher.execute_calls) == 2
    assert "鉴权失败" in composer.calls[0]["tool_text"]
    assert "sensitive request URL" not in composer.calls[0]["tool_text"]


def test_graph_blocks_a_repeated_tool_call():
    dispatcher = FakeDispatcher(
        {"amap_weather_live": RouteResult(text="深圳：晴", intent="amap_weather_live")}
    )
    graph = _graph(
        dispatcher,
        [
            AgentDecision(actions=[AgentAction("amap_weather_live", "深圳天气")]),
            AgentDecision(actions=[AgentAction("amap_weather_live", "深圳天气")]),
        ],
    )

    graph.run("深圳天气", RouteContext())

    assert len(dispatcher.execute_calls) == 1


def test_graph_stops_after_three_total_tool_calls():
    dispatcher = FakeDispatcher(
        {
            "amap_weather_live": RouteResult(text="天气：晴", intent="amap_weather_live"),
            "exa_search": RouteResult(text="网页：A", intent="exa_search"),
        }
    )
    graph = _graph(
        dispatcher,
        [
            AgentDecision(
                actions=[
                    AgentAction("amap_weather_live", "深圳天气"),
                    AgentAction("exa_search", "深圳酒店"),
                    AgentAction("amap_weather_live", "深圳天气2"),
                ]
            ),
            AgentDecision(finished=True),
        ],
    )

    graph.run("查三个信息", RouteContext())

    assert len(dispatcher.execute_calls) == 3


def test_graph_logs_agent_batch_node_boundaries_in_debug(caplog):
    graph = _graph(
        FakeDispatcher({"amap_weather_live": RouteResult(text="天气：晴", intent="amap_weather_live")} ),
        [
            AgentDecision(actions=[AgentAction("amap_weather_live", "深圳天气")]),
            AgentDecision(finished=True),
        ],
    )

    with caplog.at_level(logging.INFO, logger="orchestration.graph"):
        graph.run("深圳天气", RouteContext())

    text = "\n".join(record.getMessage() for record in caplog.records)
    assert "analyze -> decide -> execute_batch -> observe" in text
    assert "节点 analyze" in text
    assert "节点 decide" in text
    assert "节点 execute_batch" in text
    assert "节点 observe" in text
    assert "节点 compose" in text
