"""McpToolClient（方案 A）单测：常驻连接调用 / close 回收 / 未就绪干净失败。

跑法（仓库根）：
    .venv\\Scripts\\python -m pytest server_py\\mcp_skill\\test_client_a.py -q

happy path 依赖 mock MCP server 在 9100；未起则自动跳过（其余用例不依赖）。
"""

from __future__ import annotations

import os
import socket
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_skill.client import McpSkillError, McpToolClient
from mcp_skill.manifest import SkillManifest


def _mock_up() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 9100), timeout=1):
            return True
    except OSError:
        return False


def _manifest(url: str, skill_id: str = "weather-mcp") -> SkillManifest:
    return SkillManifest(
        skill_id=skill_id,
        name="天气查询（MCP）",
        description="x",
        intent=f"{skill_id}_intent",
        entry_tool="get_weather",
        mcp_server={"transport": "http", "url": url},
        query_slot="city",
        tools=[
            {
                "name": "get_weather",
                "input_schema": {
                    "required": ["city"],
                    "properties": {"city": {"type": "string"}},
                },
            }
        ],
    )


@pytest.mark.skipif(not _mock_up(), reason="mock MCP server 未在 9100")
def test_call_and_close():
    """常驻连接：调用返回 mock 数据；close 停线程、可幂等。"""
    c = McpToolClient(_manifest("http://127.0.0.1:9100/mcp"))
    time.sleep(1.5)  # 等后台连接建立
    try:
        text = c.call_tool("get_weather", {"city": "深圳"})
        assert "多云转晴" in text
        assert c._loop_thread.is_alive()
    finally:
        c.close()
    assert not c._loop_thread.is_alive()
    c.close()  # 幂等


def test_call_before_ready_fails_cleanly():
    """连接未就绪（不可达地址）→ 干净 McpSkillError，不挂死。"""
    c = McpToolClient(_manifest("http://127.0.0.1:9/mcp"))
    time.sleep(1.0)  # 让连接尝试失败、session 保持 None
    try:
        with pytest.raises(McpSkillError):
            c.call_tool("get_weather", {"city": "深圳"}, timeout=5)
    finally:
        c.close()
