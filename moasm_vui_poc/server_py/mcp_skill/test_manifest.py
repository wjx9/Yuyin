"""P1 单测：manifest 映射规则 + MCPHandler 兜底（见 最终技术路线.md §2.2/§2.3）。

跑法（仓库根）：
    .venv\\Scripts\\python -m pytest server_py\\mcp_skill\\test_manifest.py -q
"""

import os
import sys

import pytest

# 让 mcp_skill / routing 可导入
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from routing.handler import RouteContext

from .manifest import SkillManifest, to_slot_specs
from .handler import MCPHandler
from .client import McpToolClient


def _weather_manifest():
    return SkillManifest.from_dict(
        {
            "skill_id": "weather-mcp",
            "name": "天气查询（MCP）",
            "description": "查询指定城市未来几天的天气情况",
            "intent": "weather_mcp",
            "pc_only": False,
            "entry_tool": "get_weather",
            "query_slot": "city",
            "mcp_server": {"transport": "http", "url": "http://127.0.0.1:9/mcp"},
            "credentials": {"type": "none"},
            "tools": [
                {
                    "name": "get_weather",
                    "description": "查询城市天气",
                    "input_schema": {
                        "required": ["city"],
                        "properties": {
                            "city": {"type": "string", "description": "城市名，如 深圳"},
                            "days": {"type": "integer", "description": "未来几天，默认 1"},
                        },
                    },
                }
            ],
        }
    )


def test_required_is_top_level_array():
    """required 是顶层数组（["city"]），不是属性级布尔。"""
    slots = to_slot_specs(_weather_manifest().tools)
    by = {s.name: s for s in slots}
    assert by["city"].required is True
    assert by["days"].required is False


def test_number_maps_to_string():
    """number（浮点）映射 string 而非 integer，避免转 int 丢精度。"""
    slots = to_slot_specs(
        [{"name": "t", "input_schema": {"properties": {"price": {"type": "number"}}}}]
    )
    assert slots[0].type == "string"


def test_query_fallback_uses_query_slot():
    """槽位为空时，整句 query 喂 query_slot（city），不盲传 {"query": ...}。"""
    h = MCPHandler(_weather_manifest(), McpToolClient(_weather_manifest()))
    # mock server 不可达（端口 9）→ 收敛成 failed，不抛异常
    r = h.handle("深圳明天天气", RouteContext())
    assert r.status == "failed"
    assert "暂不可用" in r.text


def test_query_fallback_no_string_slot_returns_clean_failed():
    """工具没有 string 槽、也没声明 query_slot → 返回需要更具体参数，不抛异常。"""
    m = SkillManifest.from_dict(
        {
            "skill_id": "x",
            "name": "X",
            "description": "x",
            "intent": "x",
            "entry_tool": "t",
            "mcp_server": {"transport": "http", "url": "http://127.0.0.1:9/mcp"},
            "tools": [
                {"name": "t", "input_schema": {"properties": {"n": {"type": "integer"}}}}
            ],
        }
    )
    r = MCPHandler(m, McpToolClient(m)).handle("随便说", RouteContext())
    assert r.status == "failed"
    assert "需要更具体的参数" in r.text


def test_new_keywords_and_replaces_fields_parsed():
    """keywords/replaces 字段解析为 list（管理员可配置的确定性路由/顶替元数据）。"""
    m = SkillManifest.from_dict(
        {
            "skill_id": "k",
            "name": "K",
            "description": "k",
            "intent": "k_mcp",
            "entry_tool": "t",
            "mcp_server": {"transport": "http", "url": "http://127.0.0.1:9/mcp"},
            "tools": [],
            "keywords": ["天气", "股价"],
            "replaces": ["amap_weather_live"],
        }
    )
    assert m.keywords == ["天气", "股价"]
    assert m.replaces == ["amap_weather_live"]


def test_old_dict_without_new_fields_uses_defaults():
    """旧数据源（P1 本地 JSON / 存量商店 manifest）没有新字段 → 默认空列表，不崩。"""
    m = SkillManifest.from_dict(
        {
            "skill_id": "old",
            "name": "O",
            "description": "o",
            "intent": "o_mcp",
            "entry_tool": "t",
            "mcp_server": {"transport": "http", "url": "http://127.0.0.1:9/mcp"},
            "tools": [],
        }
    )
    assert m.keywords == []
    assert m.replaces == []


def test_from_dict_ignores_unknown_fields():
    """管理员手输 manifest 有多余/拼错的字段 → 只取已知键，不抛 TypeError（防一个 typo 搞挂整张图）。"""
    m = SkillManifest.from_dict(
        {
            "skill_id": "typo",
            "name": "T",
            "description": "t",
            "intent": "t_mcp",
            "entry_tool": "t",
            "mcp_server": {"transport": "http", "url": "http://127.0.0.1:9/mcp"},
            "tools": [],
            "keywordz": ["typo"],  # 拼错：应被忽略而非炸
            "nonsense": 123,
        }
    )
    assert m.keywords == []


def test_mcp_handler_spec_passes_keywords_through():
    """spec() 把 manifest.keywords 透传给 IntentSpec，decide 层据此确定性收窄。"""
    m = SkillManifest.from_dict(
        {
            "skill_id": "kw",
            "name": "KW",
            "description": "kw",
            "intent": "kw_mcp",
            "entry_tool": "t",
            "mcp_server": {"transport": "http", "url": "http://127.0.0.1:9/mcp"},
            "tools": [],
            "keywords": ["股票", "股价"],
        }
    )
    spec = MCPHandler(m, McpToolClient(m)).spec()
    assert spec.keywords == ("股票", "股价")
