"""闲聊 Handler：兜底意图，直接用 Gemini 作答。

它既是 default_intent（分类器拿不准时落到这里），也承担"非任务型对话"，
并负责回答"你能做什么"这类元问题——为此它持有整个系统的能力清单
（由 factory 在装配完所有 handler 后回填），据此如实介绍真实能力，
而不是泛泛地说"我是通用语言模型"。能力清单与分类器同源：新增能力自动反映。
"""

from __future__ import annotations

from ..gemini import GeminiClient, GeminiError
from ..handler import Handler, IntentSpec, RouteContext, RouteResult


class ChitchatHandler(Handler):
    intent = "chitchat"
    description = (
        "日常闲聊、通用问答、与出行/地图/快递/新闻无关的对话；"
        "也包括需要联网才能回答的实时数值/最新信息查询"
        "（如股价、汇率、币价、油价等），会自动联网检索后作答"
    )

    _BASE_SYSTEM = (
        "你是一个出行生活助手的对话入口，回答简洁自然、用中文。"
    )

    def __init__(self, gemini: GeminiClient, capabilities: list[IntentSpec] | None = None):
        self._gemini = gemini
        self._capabilities: list[IntentSpec] = capabilities or []

    def set_capabilities(self, capabilities: list[IntentSpec]) -> None:
        """由 factory 装配完成后回填全系统能力（含 chitchat 自身）。"""
        self._capabilities = capabilities

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        history = [(t.query, t.response) for t in context.history]
        try:
            # grounded=True：挂上 Google Search 工具，是否真联网由模型自行判断
            # （"1+1等于几"不会触发，"apple 股价/最新消息"等时效问题才会搜）
            ans = self._gemini.answer(
                query, system=self._build_system(), history=history, grounded=True
            )
        except GeminiError as e:
            return RouteResult(text=f"（闲聊服务暂不可用：{e}）", intent=self.intent)
        text = ans.text
        if ans.sources:
            lines = "\n".join(f"  - {s.title}" for s in ans.sources[:3])
            text = f"{text}\n\n来源（联网检索）：\n{lines}"
        return RouteResult(text=text, intent=self.intent, data=ans.sources or None)

    def _build_system(self) -> str:
        if not self._capabilities:
            return self._BASE_SYSTEM
        # 排除自身闲聊项，列出真正的任务能力
        caps = [s for s in self._capabilities if s.id != self.intent]
        if not caps:
            return self._BASE_SYSTEM
        lines = "\n".join(f"- {s.description}" for s in caps)
        return (
            f"{self._BASE_SYSTEM}\n"
            "当用户询问你能做什么/有哪些能力时，必须依据下面这份【真实能力清单】如实回答，"
            "用自然的中文归纳介绍，不要说自己只是通用语言模型，也不要编造清单外的能力：\n"
            f"{lines}\n"
            "除上述能力外，你也能进行日常闲聊与通用问答。"
        )
