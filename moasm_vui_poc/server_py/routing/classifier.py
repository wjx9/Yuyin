"""意图分类器。

IntentClassifier 是抽象：输入 query + 当前已注册的意图列表(IntentSpec)，输出 Route
（意图 id + 顺带抽出的槽位）。关键点：意图列表是**传进来的**（由 Dispatcher 从已
注册 handler 动态收集），分类器自身不写死任何业务意图——所以新增能力无需改分类器。

- GeminiClassifier：把每个意图编译成一个 function 声明（description 即函数说明、
  handler 声明的 SlotSpec 即参数 schema），用 Gemini function calling（mode=ANY，
  强制选一个函数）**一次调用**同时得到意图与槽位。相比"先分类、命中后再单独调一次
  LLM 抽槽位"的两段式，延迟与调用成本各省一半。
- KeywordClassifier：零依赖兜底；Gemini 不可用/输出非法时回退。只出意图不出槽位
  （槽位缺失由各 handler 的确定性解析兜底，见 handler.py 的槽位契约）。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .gemini import GeminiClient, GeminiError
from .handler import IntentSpec, SlotSpec

_log = logging.getLogger("routing.classifier")


@dataclass(frozen=True)
class Route:
    """一次分类的结果：意图 + 槽位（可能为空 dict）。"""

    intent: str
    slots: dict[str, Any] = field(default_factory=dict)


class IntentClassifier(ABC):
    @abstractmethod
    def classify(self, query: str, intents: list[IntentSpec], *, default: str) -> Route:
        raise NotImplementedError


class KeywordClassifier(IntentClassifier):
    """基于关键词的兜底分类器。只在 default 之外做有限的强信号判断。"""

    _RULES: list[tuple[str, tuple[str, ...]]] = [
        ("express_tracking", ("快递", "物流", "运单", "单号", "包裹", "签收", "到哪了")),
        ("amap", ("附近", "周边", "导航", "路线", "怎么走", "景点", "美食", "咖啡", "商场", "加油站", "扫街")),
        ("tripnow_personal", ("我的行程", "我关注", "帮我查我", "我订阅", "我买的票")),
        ("tripnow_public", ("机票", "车票", "高铁", "车次", "航班", "余票", "抢票", "车站", "动态")),
        ("tencent_weather", ("天气", "下雨", "气温", "温度", "风力", "空气质量", "预警", "降水", "雾霾")),
        # 先于 hot 判断：出现"XX的新闻/分类新闻"这类点名对象的强信号才走 search，
        # 否则"新闻/头条"落到 hot。城市/地区无法穷举，Gemini 不可用时地区新闻
        # 主要靠"的新闻"这个组合命中（"深圳的新闻"、"美国的新闻"）。
        ("tencent_news_search", ("的新闻", "相关新闻", "科技新闻", "财经新闻", "体育新闻",
                                 "娱乐新闻", "国际新闻", "军事新闻", "本地新闻")),
        ("tencent_hot_news", ("新闻", "头条", "大新闻", "热点", "时事", "最近发生")),
    ]

    def classify(self, query: str, intents: list[IntentSpec], *, default: str) -> Route:
        ids = {s.id for s in intents}
        for intent_id, keywords in self._RULES:
            if intent_id in ids:
                hit = next((k for k in keywords if k in query), None)
                if hit:
                    _log.debug("关键词分类命中 %r（关键词=%r）", intent_id, hit)
                    return Route(intent_id)
        _log.debug("关键词无命中，回退默认 %r", default)
        return Route(default)


class GeminiClassifier(IntentClassifier):
    """function calling 分类器：一次调用出 意图+槽位；失败回退 KeywordClassifier。"""

    def __init__(self, gemini: GeminiClient, fallback: IntentClassifier | None = None):
        self._gemini = gemini
        self._fallback = fallback or KeywordClassifier()

    def classify(self, query: str, intents: list[IntentSpec], *, default: str) -> Route:
        _log.debug("候选意图: %s", [s.id for s in intents])
        try:
            call = self._gemini.choose_function(
                query,
                declarations=[_declaration(s) for s in intents],
                system=self._system(default),
                temperature=0.0,
            )
        except GeminiError as e:
            _log.warning("Gemini 分类失败(%s)，回退关键词分类器", e)
            return self._fallback.classify(query, intents, default=default)

        by_id = {s.id: s for s in intents}
        if call is None or call.name not in by_id:
            # mode=ANY 下极少发生（模型没回 functionCall / 编了个不存在的函数名）
            _log.warning("Gemini 未返回合法意图(%r)，回退关键词分类器", call)
            return self._fallback.classify(query, intents, default=default)

        slots = _clean_slots(by_id[call.name].slots, call.args)
        _log.debug("Gemini 分类: intent=%r slots=%r (原始 args=%r)", call.name, slots, call.args)
        return Route(call.name, slots)

    @staticmethod
    def _system(default: str) -> str:
        return (
            "你是语音助手的意图路由器。每个函数代表一个技能，为用户输入选择且只选择"
            "一个函数，并从输入里抽取该函数的参数。\n"
            "判定规则：\n"
            "1. 只有当用户输入【明确且完整】地属于某个技能时，才选该技能；\n"
            f"2. 若输入含糊、自相矛盾、玩笑、或无法明确归类，一律选择兜底技能 \"{default}\"；\n"
            "3. 不要因为出现了某个关键词（如\"单号\"）就强行归类，要看整句的真实诉求；\n"
            "4. 参数只填用户明确表达了的信息，绝不编造；没说到的参数不要填。"
        )


def _declaration(spec: IntentSpec) -> dict:
    """IntentSpec -> Gemini functionDeclaration。无槽位的意图不带 parameters。"""
    decl: dict = {"name": spec.id, "description": spec.description}
    if spec.slots:
        decl["parameters"] = {
            "type": "object",
            "properties": {
                s.name: {"type": s.type, "description": s.description} for s in spec.slots
            },
        }
    return decl


def _clean_slots(declared: tuple[SlotSpec, ...], args: dict) -> dict[str, Any]:
    """把模型返回的 args 净化成声明的槽位：丢未声明的键，按声明类型收敛值。

    只保证类型正确（str 非空 / int 整数），业务范围（如条数 1..50）由 handler 校验。
    """
    cleaned: dict[str, Any] = {}
    for spec in declared:
        v = args.get(spec.name)
        if spec.type == "string":
            if isinstance(v, str) and v.strip():
                cleaned[spec.name] = v.strip()
        elif spec.type == "integer":
            # JSON 数字可能解析为 float（5.0）；bool 是 int 子类，须显式排除
            if isinstance(v, bool):
                continue
            if isinstance(v, int):
                cleaned[spec.name] = v
            elif isinstance(v, float) and v.is_integer():
                cleaned[spec.name] = int(v)
    return cleaned
