"""P1 装配入口：读本地 manifest → 生成 MCPHandler 列表。

P2 时把数据源从"本地 JSON 文件"换成"商店 /me/skills/sync"，返回结构保持一致
（(version, skills)），这里只需改数据获取那一段。
"""

from __future__ import annotations

import json
import os

from .manifest import SkillManifest
from .client import McpToolClient
from .handler import MCPHandler


def build_mcp_handlers() -> list[MCPHandler]:
    """读 .env 指定的本地 manifest JSON，装配 MCPHandler 列表（未配置则空列表）。"""
    path = os.getenv("MCP_SKILL_MANIFEST", "").strip()
    if not path:
        return []
    with open(path, encoding="utf-8") as f:
        manifests = [SkillManifest.from_dict(s) for s in json.load(f)["skills"]]
    return [MCPHandler(m, McpToolClient(m)) for m in manifests]
