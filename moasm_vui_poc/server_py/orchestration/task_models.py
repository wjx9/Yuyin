"""LangGraph 任务规划的数据模型与安全校验。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from routing.handler import IntentSpec, SlotSpec

_MAX_TASKS = 3


@dataclass(frozen=True)
class RequestAnalysis:
    """模型对用户目标的结构化理解，不包含任何工具选择。"""

    goal: str
    known: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentAction:
    """Agent 要执行的一项工具调用。"""

    intent: str
    query: str
    slots: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentDecision:
    """一次决策可安排多个互不依赖的工具调用，或结束本轮。"""

    actions: list[AgentAction] = field(default_factory=list)
    finished: bool = False
    reason: str = ""
    follow_up_intent: str = ""
    follow_up_slot: str = ""
    direct_answer: str = ""


def _sanitize_actions(
    raw_tasks: object,
    *,
    available_specs: list[IntentSpec],
    allowed_intents: set[str],
) -> list[AgentAction]:
    """只保留已注册、允许执行、参数类型正确的至多三项动作。"""
    if not isinstance(raw_tasks, list):
        return []

    specs_by_id = {spec.id: spec for spec in available_specs}
    actions: list[AgentAction] = []
    for raw in raw_tasks:
        if len(actions) >= _MAX_TASKS:
            break
        if not isinstance(raw, dict):
            continue

        intent, query = raw.get("intent"), raw.get("query")
        if not isinstance(intent, str) or intent not in allowed_intents:
            continue
        spec = specs_by_id.get(intent)
        if spec is None or not isinstance(query, str) or not query.strip():
            continue

        actions.append(
            AgentAction(
                intent=intent,
                query=query.strip(),
                slots=_sanitize_slots(spec.slots, raw.get("slots")),
            )
        )
    return actions


def sanitize_analysis(raw: object, *, fallback_goal: str) -> RequestAnalysis:
    """把模型分析收敛成可安全存入 Graph 状态的纯文本数据。"""
    if not isinstance(raw, dict):
        return RequestAnalysis(goal=fallback_goal)

    goal = raw.get("goal")
    return RequestAnalysis(
        goal=goal.strip() if isinstance(goal, str) and goal.strip() else fallback_goal,
        known=_sanitize_text_list(raw.get("known")),
        constraints=_sanitize_text_list(raw.get("constraints")),
    )


def sanitize_decision(
    raw: object,
    *,
    available_specs: list[IntentSpec],
    allowed_intents: set[str],
) -> AgentDecision | None:
    """验证决策器输出，避免模型调用未注册能力或伪造槽位。"""
    if not isinstance(raw, dict):
        return None

    actions = _sanitize_actions(
        raw.get("actions"), available_specs=available_specs, allowed_intents=allowed_intents
    )
    reason = raw.get("reason")
    # finish=true 与 actions 可以同时出现：表示执行这一批后即可总结，
    # 用于省掉一次无意义的 observe -> decide 往返。
    finished = raw.get("finish") is True
    follow_up_intent, follow_up_slot = _sanitize_follow_up(
        raw.get("follow_up"), available_specs=available_specs, allowed_intents=allowed_intents
    )
    direct_answer = raw.get("direct_answer")
    if not isinstance(direct_answer, str):
        direct_answer = ""
    direct_answer = direct_answer.strip()
    decision = AgentDecision(
        actions=actions,
        # finished=true 且有工具调用时，执行本批后直接进入总结。
        finished=finished,
        reason=reason.strip() if isinstance(reason, str) else "",
        follow_up_intent=follow_up_intent if finished else "",
        follow_up_slot=follow_up_slot if finished else "",
        direct_answer=direct_answer if finished and not actions else "",
    )
    return decision if decision.actions or decision.finished else None


def _sanitize_follow_up(
    raw: object,
    *,
    available_specs: list[IntentSpec],
    allowed_intents: set[str],
) -> tuple[str, str]:
    """追问只能针对已声明的必填输入，避免模型制造开放式偏好问题。"""
    if not isinstance(raw, dict):
        return "", ""
    intent, slot_name = raw.get("intent"), raw.get("slot")
    if not isinstance(intent, str) or intent not in allowed_intents:
        return "", ""
    if not isinstance(slot_name, str):
        return "", ""
    spec = next((item for item in available_specs if item.id == intent), None)
    if spec is None:
        return "", ""
    slot = next((item for item in spec.slots if item.name == slot_name), None)
    if slot is None or not slot.required:
        return "", ""
    return intent, slot_name


def _sanitize_slots(declared: tuple[SlotSpec, ...], raw_slots: object) -> dict[str, Any]:
    if not isinstance(raw_slots, dict):
        return {}

    slots: dict[str, Any] = {}
    for spec in declared:
        value = raw_slots.get(spec.name)
        if spec.type == "string" and isinstance(value, str) and value.strip():
            slots[spec.name] = value.strip()
        elif spec.type == "integer":
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                slots[spec.name] = value
            elif isinstance(value, float) and value.is_integer():
                slots[spec.name] = int(value)
    return slots


def _sanitize_text_list(raw: object, *, limit: int = 8) -> list[str]:
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    for value in raw:
        if len(values) >= limit:
            break
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return values
