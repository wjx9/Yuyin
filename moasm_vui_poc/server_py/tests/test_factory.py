"""装配工厂单测：build_dispatcher / build_assistant_graph 的顶替内置（replaces）行为。

跑法（仓库根）：
    .venv\\Scripts\\python -m pytest server_py\\tests\\test_factory.py -q
"""

from __future__ import annotations

from orchestration.factory import build_assistant_graph
from routing.factory import build_dispatcher

# 让 amap_weather_live 等内置能力注册，测顶替；GEMINI_API_KEY 是分流层硬依赖。
_BUILTIN_KEYS = {
    "GEMINI_API_KEY": "test-key",
    "AMAP_KEY": "test-amap",
}


def test_build_dispatcher_excludes_intents_keeps_chitchat(monkeypatch):
    for k, v in _BUILTIN_KEYS.items():
        monkeypatch.setenv(k, v)
    d = build_dispatcher(exclude_intents={"amap_weather_live"})
    assert "amap_weather_live" not in d.intents
    assert "chitchat" in d.intents  # 兜底永不排除
    assert "amap_geocode" in d.intents  # 只排除指定的，其他内置保留


def test_build_dispatcher_never_excludes_chitchat_even_if_asked(monkeypatch):
    """防御：管理员把 replaces 配错成 chitchat 也不能把兜底顶掉。"""
    for k, v in _BUILTIN_KEYS.items():
        monkeypatch.setenv(k, v)
    d = build_dispatcher(exclude_intents={"chitchat"})
    assert "chitchat" in d.intents


def test_build_assistant_graph_allowed_intents_excludes_replaced(monkeypatch):
    """静态白名单残留也要减掉：_PLANNABLE_INTENTS 仍含被顶替的意图，不修会被 Gemini 再次允许。"""
    for k, v in _BUILTIN_KEYS.items():
        monkeypatch.setenv(k, v)
    graph = build_assistant_graph(
        dispatcher=build_dispatcher(exclude_intents={"amap_weather_live"}),
        exclude_intents={"amap_weather_live"},
    )
    assert "amap_weather_live" not in graph._decider._allowed_intents
    assert "chitchat" in graph._decider._allowed_intents
