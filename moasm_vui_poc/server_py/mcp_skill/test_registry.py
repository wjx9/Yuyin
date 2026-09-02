"""SkillRegistry 单测：TTL 缓存 / invalidate / ttl=0 强制重取（设计 §4.2）。

跑法（仓库根）：
    .venv\\Scripts\\python -m pytest server_py\\mcp_skill\\test_registry.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_skill.registry import SkillRegistry

_MANIFEST = {
    "skill_id": "weather-mcp",
    "name": "天气查询（MCP）",
    "description": "x",
    "intent": "weather_mcp",
    "entry_tool": "get_weather",
    "mcp_server": {"transport": "http", "url": "http://127.0.0.1:9100/mcp"},
    "tools": [],
}


class FakeStore:
    """记录 sync 调用次数的假商店。"""

    def __init__(self, payload=None):
        self.payload = payload or {"version": 1, "skills": [_MANIFEST]}
        self.calls = 0

    def sync(self, user_id):
        self.calls += 1
        return self.payload


def test_resolve_cached_within_ttl():
    store = FakeStore()
    reg = SkillRegistry(store, ttl=30.0)
    v1, s1 = reg.resolve("u")
    assert store.calls == 1
    v2, s2 = reg.resolve("u")  # TTL 内 → 不再次请求
    assert store.calls == 1
    assert (v1, s1) == (v2, s2)


def test_invalidate_refetches():
    store = FakeStore()
    reg = SkillRegistry(store, ttl=30.0)
    reg.resolve("u")
    reg.invalidate("u")
    reg.resolve("u")
    assert store.calls == 2


def test_ttl_zero_always_refetches():
    """ttl=0：任何 resolve 都强制重取（演示/测试用）。"""
    store = FakeStore()
    reg = SkillRegistry(store, ttl=0.0)
    reg.resolve("u")
    reg.resolve("u")
    assert store.calls == 2
