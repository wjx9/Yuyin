"""装配 LangGraph 总入口。"""

from __future__ import annotations

import os

from routing import GeminiClient, build_dispatcher

from .composer import GeminiResultComposer, ResultComposer
from .graph import AssistantGraph
from .planner import (
    ActionDecider,
    GeminiActionDecider,
    GeminiRequestAnalyzer,
    RequestAnalyzer,
)

_PLANNABLE_INTENTS = {
    "chitchat",
    "calendar_create",
    "alarm_create",
    "timer_create",
    "reminder_create",
    "amap",
    "amap_geocode",
    "amap_regeo",
    "amap_weather_live",
    "amap_weather_forecast",
    "amap_driving",
    "amap_walking",
    "amap_bicycling",
    "amap_transit",
    "exa_search",
    "tencent_hot_news",
    "tencent_news_search",
    "tripnow_public",
    "tripnow_personal",
    "express_tracking",
    "music_play",
    "music_control",
}


def build_assistant_graph(
    *,
    dispatcher=None,
    composer: ResultComposer | None = None,
    analyzer: RequestAnalyzer | None = None,
    decider: ActionDecider | None = None,
) -> AssistantGraph:
    dispatcher = dispatcher or build_dispatcher()

    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key and (composer is None or analyzer is None or decider is None):
        raise RuntimeError("缺少 GEMINI_API_KEY：需求分析、决策与结果整理需要 Gemini")
    gemini = GeminiClient(key) if key else None
    if composer is None:
        composer = GeminiResultComposer(gemini)
    if analyzer is None:
        analyzer = GeminiRequestAnalyzer(gemini)
    if decider is None:
        decider = GeminiActionDecider(gemini, allowed_intents=_PLANNABLE_INTENTS)

    return AssistantGraph(dispatcher, composer, analyzer, decider)
