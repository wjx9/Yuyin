"""Gemini 驱动的需求分析与逐步决策组件。"""

from __future__ import annotations

import logging
from typing import Protocol

from routing.gemini import GeminiClient, GeminiError, loads_json_loose
from routing.handler import IntentSpec
from routing.history import Turn

from .task_models import (
    AgentAction,
    AgentDecision,
    RequestAnalysis,
    sanitize_decision,
    sanitize_analysis,
)

_log = logging.getLogger("orchestration.planner")


class AgentDecisionError(RuntimeError):
    """决策模型不可用或输出不符合动作协议。"""


class RequestAnalyzer(Protocol):
    def analyze(self, *, query: str, history: list[Turn]) -> RequestAnalysis: ...


class ActionDecider(Protocol):
    def decide(
        self,
        *,
        query: str,
        analysis: RequestAnalysis,
        observations: list[dict[str, str]],
        specs: list[IntentSpec],
        history: list[Turn],
        remaining_steps: int,
        executed_actions: list[str],
    ) -> AgentDecision: ...


class GeminiRequestAnalyzer:
    """只理解需求，不选择工具。"""

    _SYSTEM = (
        "你是手机语音助手的需求分析器。请理解用户真正想完成的目标，"
        "但不要推荐工具、不要给出答案、不要执行任务。只输出 JSON。\n"
        "输出格式：\n"
        '{"goal":"用户最终目标","known":["已知信息"],'
        '"constraints":["时间地点等限制"]}\n'
        "规则：\n"
        "1. known 必须完整保留用户原话中已经明确给出的时间、地点、对象和目标，不能遗漏。\n"
        "2. 只记录用户明确表达或可直接确定的信息；未知信息不要猜测。"
    )

    def __init__(self, gemini: GeminiClient):
        self._gemini = gemini

    def analyze(self, *, query: str, history: list[Turn]) -> RequestAnalysis:
        try:
            text = self._gemini.generate(
                f"当前日期：{_today()}\n用户原话：{query}\n请输出需求分析 JSON。",
                system=self._SYSTEM,
                temperature=0.0,
                history=[(turn.query, turn.response) for turn in history[-3:]],
                response_mime_type="application/json",
            )
        except GeminiError as error:
            _log.warning("需求分析失败，使用原始问题作为目标：%s", error)
            return RequestAnalysis(goal=query)

        analysis = sanitize_analysis(loads_json_loose(text), fallback_goal=query)
        _log.info(
            "需求分析完成：goal=%r，known=%s，constraints=%s",
            analysis.goal,
            analysis.known,
            analysis.constraints,
        )
        return analysis


class GeminiActionDecider:
    """根据已知事实决定下一批互不依赖的工具调用。"""

    _SYSTEM = (
        "你是手机语音助手的下一步决策器。根据需求分析、已执行结果和可用能力，"
        "每次决定下一批动作。只输出 JSON。\n"
        "输出格式：\n"
        '{"actions":[{"intent":"能力id","query":"完整可执行的请求","slots":{}}],'
        '"finish":false,"reason":"","follow_up":null,"direct_answer":""}\n'
        "或\n"
        '{"actions":[],"finish":true,"reason":"已完成或暂时无法可靠继续",'
        '"follow_up":{"intent":"能力id","slot":"必填槽位名"},"direct_answer":""}\n'
        "规则：\n"
        "1. 优先选择能推进用户目标的可用能力；不要把能力名称当作答案。\n"
        "2. 可以在同一批中安排 1 到 3 个彼此不依赖的能力调用；"
        "只有必须读取前一项结果后才能决定的动作，才留给下一轮。\n"
        "当本轮剩余工具调用次数为 0 时，actions 必须为空，只能选择 finish。\n"
        "3. 必须利用已执行结果决定下一步，不能重复已执行的相同调用。\n"
        "7. action.query 只能描述工具要执行的查询或动作，不能写成给用户的最终答案、"
        "解释、结论或虚构的工具输入；如果已有历史和系统事实足够回答，返回 actions=[]、finish=true。\n"
        "8. 当用户是在询问上一轮结果、信息来源、计算过程或要求继续说明，且历史对话或已执行结果"
        "已经包含回答依据时，必须返回 actions=[]、finish=true，并使用 direct_answer 写一个简短回答草稿；"
        "不得调用 chitchat。direct_answer 只能复述已有依据，不能新增事实。\n"
        "9. 只有用户提出新的、与历史无关的闲聊话题时，才允许把 chitchat 作为动作；"
        "普通闲聊也可以直接用 actions=[]、finish=true 交给总结器回答。\n"
        "如果当前 actions 执行完成后已经足以回答用户，可以同时设置 finish=true；"
        "此时系统会在这批动作完成后直接总结，不再额外请求下一轮决策。\n"
        "10. 先执行无需额外信息即可推进目标的动作。只有某个相关能力的声明中标为必填的"
        "输入缺失、且没有其他可执行动作时，才选择 finish 并填写 follow_up。"
        "追问只能针对一个必填输入，并优先选择能解锁最多后续动作的信息。\n"
        "11. 调用工具时，query 和 slots 只能使用用户原话、需求分析或已执行结果中已有的事实；"
        "不得自行加入偏好、地点、对象或其他限定条件。\n"
        "12. slots 只能填写能力说明中声明且用户明确提供的参数。"
    )

    def __init__(self, gemini: GeminiClient, allowed_intents: set[str]):
        self._gemini = gemini
        self._allowed_intents = allowed_intents

    def decide(
        self,
        *,
        query: str,
        analysis: RequestAnalysis,
        observations: list[dict[str, str]],
        specs: list[IntentSpec],
        history: list[Turn],
        remaining_steps: int,
        executed_actions: list[str],
    ) -> AgentDecision:
        usable_specs = [spec for spec in specs if spec.id in self._allowed_intents]
        prompt = (
            f"当前日期：{_today()}\n用户原话：{query}\n\n"
            f"最近历史对话：\n{_format_history(history)}\n\n"
            f"需求分析：\n{_format_analysis(analysis)}\n\n"
            f"已执行结果：\n{_format_observations(observations)}\n\n"
            f"本轮剩余工具调用次数：{remaining_steps}\n\n"
            f"已完成调用（不得重复）：\n{_format_executed_actions(executed_actions)}\n\n"
            f"可用能力：\n{_format_specs(usable_specs)}\n\n"
            "请输出下一步动作 JSON。"
        )
        decision = self._generate_valid_decision(
            prompt=prompt,
            usable_specs=usable_specs,
            history=history,
            executed_actions=set(executed_actions),
        )
        if decision is None:
            raise AgentDecisionError("决策模型返回了非法动作")
        _log.info(
            "下一批决策：actions=%s，finish=%s，follow_up=%s，reason=%r，direct_answer=%s",
            [(action.intent, action.query) for action in decision.actions],
            decision.finished,
            (decision.follow_up_intent, decision.follow_up_slot),
            decision.reason,
            bool(decision.direct_answer),
        )
        return decision

    def _generate_valid_decision(
        self,
        *,
        prompt: str,
        usable_specs: list[IntentSpec],
        history: list[Turn],
        executed_actions: set[str],
    ) -> AgentDecision | None:
        """请求一次 JSON；格式不合法时以相同协议修复一次。"""
        repair_note = ""
        for attempt in range(2):
            try:
                text = self._gemini.generate(
                    prompt + repair_note,
                    system=self._SYSTEM,
                    temperature=0.0,
                    history=[(turn.query, turn.response) for turn in history[-3:]],
                    response_mime_type="application/json",
                )
            except GeminiError as error:
                raise AgentDecisionError("决策模型调用失败") from error

            raw = loads_json_loose(text)
            decision = sanitize_decision(
                raw,
                available_specs=usable_specs,
                allowed_intents=self._allowed_intents,
            )
            if decision is not None and not _has_only_repeated_actions(
                decision, executed_actions
            ):
                return decision
            _log.debug(
                "决策 JSON 未通过协议校验：尝试=%d，输出长度=%d，顶层类型=%s",
                attempt + 1,
                len(text),
                type(raw).__name__,
            )
            repair_note = (
                "\n\n上一条输出未通过协议校验。请严格只输出一个 JSON 对象，"
                "必须包含 actions、finish、reason、follow_up、direct_answer 五个字段；"
                "actions 中每一项的 intent 必须来自可用能力，query 必须是非空字符串，"
                "且不能重复已完成调用。follow_up 只能为 null，或包含 intent 和必填 slot 的对象。"
            )
        return None


def _format_specs(specs: list[IntentSpec]) -> str:
    lines: list[str] = []
    for spec in specs:
        line = f"- intent={spec.id}: {spec.description}"
        if spec.slots:
            line += "\n  slots: " + "；".join(
                f"{slot.name}({slot.type}{'，必填' if slot.required else ''}): {slot.description}"
                for slot in spec.slots
            )
        lines.append(line)
    return "\n".join(lines) or "（没有可用能力）"


def _format_analysis(analysis: RequestAnalysis) -> str:
    return (
        f"目标：{analysis.goal}\n"
        f"已知：{'；'.join(analysis.known) or '无'}\n"
        f"限制：{'；'.join(analysis.constraints) or '无'}"
    )


def _format_observations(observations: list[dict[str, str]]) -> str:
    if not observations:
        return "（尚未执行任何能力）"
    return "\n\n".join(
        f"【{item['status']} / {item['intent']}】\n{item['text'][:2000]}"
        for item in observations[-3:]
    )


def _format_executed_actions(actions: list[str]) -> str:
    return "\n".join(f"- {action}" for action in actions) or "（无）"


def _format_history(history: list[Turn]) -> str:
    if not history:
        return "（无历史对话）"
    return "\n\n".join(
        f"用户：{turn.query}\n助手：{turn.response[:1200]}"
        for turn in history[-3:]
    )


def _has_only_repeated_actions(
    decision: AgentDecision, executed_actions: set[str]
) -> bool:
    if decision.finished or not decision.actions:
        return False
    return all(_action_signature(action) in executed_actions for action in decision.actions)


def _action_signature(action: AgentAction) -> str:
    slot_text = ";".join(
        f"{key}={value}" for key, value in sorted(action.slots.items())
    )
    return f"{action.intent}|{action.query}|{slot_text}"


def _today() -> str:
    from datetime import date

    return date.today().isoformat()
