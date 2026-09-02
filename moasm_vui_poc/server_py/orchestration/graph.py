"""所有对话请求的统一 LangGraph Agent 编排入口。"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from typing import NotRequired, TypedDict

from langgraph.graph import END, START, StateGraph

from routing import RouteContext, RouteResult
from routing.dispatcher import Dispatcher
from tools import ToolRuntime

from .composer import ResultComposer
from .models import AssistantResult
from .planner import ActionDecider, AgentDecisionError, RequestAnalyzer
from .task_models import AgentAction, AgentDecision, RequestAnalysis

_log = logging.getLogger("orchestration.graph")
_MAX_TOOL_STEPS = 3


class AssistantState(TypedDict):
    query: str
    context: RouteContext
    analysis: NotRequired[RequestAnalysis]
    decision: NotRequired[AgentDecision]
    results: NotRequired[list[RouteResult]]
    batch_results: NotRequired[list[RouteResult]]
    executed_actions: NotRequired[list[str]]
    step_count: NotRequired[int]
    raw_result: NotRequired[RouteResult]
    final_text: NotRequired[str]


class AssistantGraph:
    def __init__(
        self,
        dispatcher: Dispatcher,
        composer: ResultComposer,
        analyzer: RequestAnalyzer,
        decider: ActionDecider,
        runtime: ToolRuntime | None = None,
    ):
        self._dispatcher = dispatcher
        self._composer = composer
        self._analyzer = analyzer
        self._decider = decider
        self._runtime = runtime or ToolRuntime.from_dispatcher(dispatcher)
        self._graph = self._build_graph()

    @property
    def capabilities(self) -> list[str]:
        return self._runtime.names("pc")

    @property
    def specs(self):
        return self._dispatcher.specs

    def capabilities_for(self, platform: str = "pc") -> list[str]:
        return self._runtime.names(platform)

    def run(self, query: str, context: RouteContext) -> AssistantResult:
        started = time.perf_counter()
        _log.info(
            "LangGraph Agent 开始：START -> analyze -> decide -> execute_batch -> observe -> ... -> compose -> END (platform=%s)",
            context.platform,
        )
        state = self._graph.invoke({"query": query, "context": context})
        raw_result = state["raw_result"]
        final_text = state["final_text"]
        _log.info(
            "LangGraph Agent 结束：intent=%r，工具调用=%d，总耗时 %.0fms，最终结果长度 %d",
            raw_result.intent,
            state.get("step_count", 0),
            (time.perf_counter() - started) * 1000,
            len(final_text),
        )
        return AssistantResult(
            text=final_text,
            intent=raw_result.intent,
            data=raw_result.data,
            card_text=raw_result.text,
        )

    def _build_graph(self):
        graph = StateGraph(AssistantState)
        graph.add_node("analyze", self._analyze)
        graph.add_node("decide", self._decide)
        graph.add_node("execute_batch", self._execute_batch)
        graph.add_node("observe", self._observe)
        graph.add_node("compose", self._compose)
        graph.add_edge(START, "analyze")
        graph.add_edge("analyze", "decide")
        graph.add_conditional_edges(
            "decide",
            self._next_node,
            {"execute_batch": "execute_batch", "compose": "compose"},
        )
        graph.add_edge("execute_batch", "observe")
        graph.add_conditional_edges(
            "observe",
            self._next_after_observe,
            {"decide": "decide", "compose": "compose"},
        )
        graph.add_edge("compose", END)
        return graph.compile()

    def _analyze(self, state: AssistantState) -> dict:
        started = time.perf_counter()
        _log.info("节点 analyze：理解用户目标、约束和缺失信息")
        analysis = self._analyzer.analyze(
            query=state["query"], history=state["context"].history
        )
        _log.info(
            "节点 analyze 完成：goal=%r，耗时 %.0fms",
            analysis.goal,
            (time.perf_counter() - started) * 1000,
        )
        return {
            "analysis": analysis,
            "results": [],
            "executed_actions": [],
            "step_count": 0,
        }

    def _decide(self, state: AssistantState) -> dict:
        context = state["context"]
        results = state.get("results", [])
        remaining = _MAX_TOOL_STEPS - state.get("step_count", 0)
        _log.info("节点 decide：根据需求分析和 %d 项已知结果决定下一批动作", len(results))
        try:
            analysis = state["analysis"]
            if context.location:
                analysis = replace(
                    analysis,
                    known=[
                        *analysis.known,
                        "系统已提供手机当前位置，可作为未明确说明的路线起点",
                    ],
                )
            decision = self._decider.decide(
                query=state["query"],
                analysis=analysis,
                observations=_observations(results),
                specs=self._runtime.specs(context.platform),
                history=context.history,
                remaining_steps=max(remaining, 0),
                executed_actions=state.get("executed_actions", []),
            )
        except AgentDecisionError as error:
            decision = self._stop_after_decision_failure(state, error)

        actions = [
            action
            for action in decision.actions
            if _action_signature(action) not in state.get("executed_actions", [])
        ][:remaining]
        if len(actions) != len(decision.actions):
            _log.warning("节点 decide：已过滤重复调用或超过本轮剩余上限")
        if not actions and not decision.finished:
            decision = AgentDecision(
                finished=True,
                reason="下一批动作全部重复、不可执行或超过本轮上限",
                follow_up_intent=decision.follow_up_intent,
                follow_up_slot=decision.follow_up_slot,
                direct_answer=decision.direct_answer,
            )
        else:
            decision = AgentDecision(
                actions=actions,
                finished=decision.finished,
                reason=decision.reason,
                follow_up_intent=decision.follow_up_intent,
                follow_up_slot=decision.follow_up_slot,
                direct_answer=decision.direct_answer,
            )
        return {"decision": decision}

    def _stop_after_decision_failure(
        self, state: AssistantState, error: AgentDecisionError
    ) -> AgentDecision:
        """决策协议失败时不绕回旧单意图链路，保留已有结果并如实结束。"""
        _log.warning(
            "决策失败，停止本轮并进入总结：已有结果=%d，原因=%s",
            len(state.get("results", [])),
            error,
        )
        return AgentDecision(finished=True, reason="决策模型输出不符合协议")

    @staticmethod
    def _next_node(state: AssistantState) -> str:
        return "execute_batch" if state["decision"].actions else "compose"

    @staticmethod
    def _next_after_observe(state: AssistantState) -> str:
        """终止批次可直接总结，只有需要后续工具时才再次询问模型。

        决策器可以用 ``finish=true`` 表示“这批动作完成后即可回答”。
        这会省掉一次 observe -> decide 的 Gemini 往返；默认的
        ``finish=false`` 仍然走原来的 Agent 循环。
        """
        return "compose" if state["decision"].finished else "decide"

    def _execute_batch(self, state: AssistantState) -> dict:
        actions = state["decision"].actions
        index = state.get("step_count", 0)
        _log.info("节点 execute_batch：并行执行 %d 项独立调用", len(actions))

        def execute(action: AgentAction) -> RouteResult:
            task_context = replace(state["context"], slots=dict(action.slots))
            try:
                return self._runtime.invoke(
                    tool_name=action.intent,
                    query=action.query,
                    context=task_context,
                    arguments=action.slots,
                )
            except Exception as error:
                _log.warning(
                    "调用 %r 异常：类型=%s", action.intent, type(error).__name__
                )
                return _task_failure_result(action.intent, error)

        for offset, action in enumerate(actions, start=1):
            _log.info(
                "批次调用 %d/%d：intent=%r，query=%r，slots=%s",
                index + offset,
                _MAX_TOOL_STEPS,
                action.intent,
                action.query,
                action.slots or "{}",
            )
        with ThreadPoolExecutor(max_workers=len(actions), thread_name_prefix="agent-tool") as executor:
            # executor.map 保持 actions 的原顺序，便于结果稳定展示和测试。
            results = list(executor.map(execute, actions))
        return {"batch_results": results}

    def _observe(self, state: AssistantState) -> dict:
        batch_results = state["batch_results"]
        actions = state["decision"].actions
        results = [*state.get("results", []), *batch_results]
        executed = [
            *state.get("executed_actions", []),
            *[_action_signature(action) for action in actions],
        ]
        _log.info("节点 observe：记录本批 %d 项结果；返回 decide", len(batch_results))
        return {
            "results": results,
            "executed_actions": executed,
            "step_count": state.get("step_count", 0) + len(batch_results),
        }

    def _compose(self, state: AssistantState) -> dict:
        results = list(state.get("results", []))
        decision = state["decision"]
        follow_up = _follow_up_text(
            decision, self._runtime.specs(state["context"].platform)
        )
        if not results and not state["context"].history and not follow_up:
            text = _unavailable_text(state["analysis"])
            result = RouteResult(text=text, intent="agent")
            _log.info("节点 compose：没有工具结果或历史，直接如实说明限制")
            return {"raw_result": result, "final_text": text}

        if follow_up and not results:
            results.append(RouteResult(text=f"【待补充信息】\n{follow_up}", intent="agent_note"))
        elif follow_up:
            results.append(
                RouteResult(
                    text=f"【待补充信息】\n{follow_up}", intent="agent_note"
                )
            )
        result = _merge_results(results) if results else RouteResult(
            text=decision.direct_answer or "本轮没有新增工具结果；请根据历史对话和系统已知事实直接回答。",
            intent="agent",
        )
        started = time.perf_counter()
        _log.info("节点 compose：调用 Gemini 结合 %d 项结果和历史生成最终回答", len(results))
        tool_text = _format_results(results) if results else result.text
        context_facts = _format_context_facts(state["context"])
        if context_facts:
            tool_text = f"{tool_text}\n\n【系统事实】\n{context_facts}"
        text = self._composer.compose(
            query=state["query"],
            intent=result.intent,
            tool_text=tool_text,
            history=state["context"].history,
        )
        _log.info(
            "节点 compose 完成：耗时 %.0fms，最终结果长度 %d",
            (time.perf_counter() - started) * 1000,
            len(text or ""),
        )
        return {"raw_result": result, "final_text": text}


def _observations(results: list[RouteResult]) -> list[dict[str, str]]:
    return [
        {
            "intent": result.intent,
            "status": result.status,
            "text": result.text,
            "source": result.source,
            "method": result.method,
        }
        for result in results
    ]


def _action_signature(action: AgentAction) -> str:
    slot_text = ";".join(f"{key}={value}" for key, value in sorted(action.slots.items()))
    return f"{action.intent}|{action.query}|{slot_text}"


def _unavailable_text(analysis: RequestAnalysis) -> str:
    return "目前没有查到足以可靠完成该请求的信息。"


def _follow_up_text(decision: AgentDecision, specs) -> str:
    if not decision.follow_up_intent or not decision.follow_up_slot:
        return ""
    spec = next((item for item in specs if item.id == decision.follow_up_intent), None)
    if spec is None:
        return ""
    slot = next((item for item in spec.slots if item.name == decision.follow_up_slot), None)
    if slot is None or not slot.required:
        return ""
    return f"请补充：{slot.description}"


def _merge_results(results: list[RouteResult]) -> RouteResult:
    """把 Agent 已知结果作为 compose 节点唯一且可追溯的事实输入。"""
    if len(results) == 1:
        return results[0]
    blocks = [
        f"【{result.status} / {result.intent}】\n"
        f"来源：{result.source or '未记录'}\n"
        f"方式：{result.method or '未记录'}\n{result.text}"
        for result in results
    ]
    return RouteResult(text="\n\n".join(blocks), intent="agent_multi")


def _format_results(results: list[RouteResult]) -> str:
    """给总结器的事实输入，统一携带来源和获取方式。"""
    blocks = []
    for result in results:
        if not result.source and not result.method:
            blocks.append(result.text)
            continue
        blocks.append(
            f"【{result.status} / {result.intent}】\n"
            f"来源：{result.source or '未记录'}\n"
            f"方式：{result.method or '未记录'}\n{result.text}"
        )
    return "\n\n".join(blocks)


def _format_context_facts(context: RouteContext) -> str:
    """只传递非敏感的请求来源元数据，不把精确坐标交给总结模型。"""
    source = context.metadata.get("location_source")
    if isinstance(source, str) and source and source != "unknown":
        return f"位置来源：{source}"
    return ""


def _task_failure_result(intent: str, error: Exception) -> RouteResult:
    """将未捕获的第三方异常收敛为不会泄露请求细节的观察结果。"""
    if type(error).__name__ == "AuthError":
        text = f"{intent} 查询失败：鉴权失败，请检查对应服务的 API 配置。"
    elif type(error).__name__ == "ConfigError":
        text = f"{intent} 查询失败：服务配置不完整。"
    else:
        text = f"{intent} 查询失败：该服务暂时不可用（{type(error).__name__}）。"
    return RouteResult(text=text, intent=intent, status="failed")
