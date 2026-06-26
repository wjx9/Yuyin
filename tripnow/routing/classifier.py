"""意图分类器。

IntentClassifier 是抽象：输入 query + 当前已注册的意图列表(IntentSpec)，输出意图 id。
关键点：意图列表是**传进来的**（由 Dispatcher 从已注册 handler 动态收集），分类器自身
不写死任何业务意图——所以新增能力无需改分类器。

- GeminiClassifier：用 LLM 分类，鲁棒，提示词由意图列表动态拼装。
- KeywordClassifier：零依赖兜底；Gemini 不可用/输出非法时回退。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

from .gemini import GeminiClient, GeminiError
from .handler import IntentSpec

_log = logging.getLogger("routing.classifier")


class IntentClassifier(ABC):
    @abstractmethod
    def classify(self, query: str, intents: list[IntentSpec], *, default: str) -> str:
        raise NotImplementedError


class KeywordClassifier(IntentClassifier):
    """基于关键词的兜底分类器。只在 default 之外做有限的强信号判断。"""

    _RULES: list[tuple[str, tuple[str, ...]]] = [
        ("express_tracking", ("快递", "物流", "运单", "单号", "包裹", "签收", "到哪了")),
        ("amap", ("附近", "周边", "导航", "路线", "怎么走", "景点", "美食", "咖啡", "商场", "加油站", "扫街")),
        ("tripnow_personal", ("我的行程", "我关注", "帮我查我", "我订阅", "我买的票")),
        ("tripnow_public", ("机票", "车票", "高铁", "车次", "航班", "余票", "抢票", "车站", "动态")),
        ("tencent_weather", ("天气", "下雨", "气温", "温度", "风力", "空气质量", "预警", "降水", "雾霾")),
        ("tencent_hot_news", ("新闻", "头条", "大新闻", "热点", "时事", "最近发生")),
    ]

    def classify(self, query: str, intents: list[IntentSpec], *, default: str) -> str:
        ids = {s.id for s in intents}
        for intent_id, keywords in self._RULES:
            if intent_id in ids:
                hit = next((k for k in keywords if k in query), None)
                if hit:
                    _log.debug("关键词分类命中 %r（关键词=%r）", intent_id, hit)
                    return intent_id
        _log.debug("关键词无命中，回退默认 %r", default)
        return default


class GeminiClassifier(IntentClassifier):
    def __init__(self, gemini: GeminiClient, fallback: IntentClassifier | None = None):
        self._gemini = gemini
        self._fallback = fallback or KeywordClassifier()

    _SYSTEM = "你是一个意图分类器。只输出一个意图 id，不要任何解释、标点或多余文字。"

    def classify(self, query: str, intents: list[IntentSpec], *, default: str) -> str:
        _log.debug("候选意图: %s", [s.id for s in intents])
        prompt = self._build_prompt(query, intents, default)
        try:
            raw = self._gemini.generate(prompt, system=self._SYSTEM, temperature=0.0)
        except GeminiError as e:
            _log.warning("Gemini 分类失败(%s)，回退关键词分类器", e)
            return self._fallback.classify(query, intents, default=default)

        _log.debug("Gemini 原始输出: %r", raw)
        ids = {s.id for s in intents}
        choice = raw.strip().splitlines()[0].strip().strip("`\"' .").lower() if raw else ""
        if choice in ids:
            return choice
        for i in ids:  # 容错：输出里包含某个 id
            if i in raw:
                _log.debug("Gemini 输出含合法 id %r（非精确匹配）", i)
                return i
        _log.warning("Gemini 输出 %r 非合法意图，回退关键词分类器", raw)
        return self._fallback.classify(query, intents, default=default)

    @staticmethod
    def _build_prompt(query: str, intents: list[IntentSpec], default: str) -> str:
        lines = "\n".join(f"- {s.id}: {s.description}" for s in intents)
        return (
            "你是意图路由器。为用户输入选择一个意图 id，只输出该 id，不要任何解释。\n"
            "判定规则：\n"
            f"1. 只有当用户输入【明确且完整】地属于某个任务意图时，才选该意图；\n"
            f"2. 若输入含糊、自相矛盾、玩笑、或无法明确归类，一律选择兜底意图 \"{default}\"；\n"
            "3. 不要因为出现了某个关键词（如\"单号\"）就强行归类，要看整句的真实诉求。\n"
            f"可选意图：\n{lines}\n\n"
            f"用户输入：{query}\n意图id："
        )
