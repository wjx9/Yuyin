"""MCP 传输：tools/call 结果的三种形态兼容解析。"""

import json

import pytest

from tripnow_client.errors import TransportError
from tripnow_client.transport.mcp import McpClient

_extract = McpClient._extract_completion


def test_extract_direct_completion():
    result = {"id": "c1", "choices": [{"message": {"content": "hi"}}]}
    assert _extract(result) == result


def test_extract_from_mcp_text_block_json():
    completion = {"id": "c2", "choices": [{"message": {"content": "hi"}}]}
    result = {"content": [{"type": "text", "text": json.dumps(completion)}]}
    assert _extract(result) == completion


def test_extract_from_text_block_plain_text():
    result = {"content": [{"type": "text", "text": "纯文本回复"}]}
    parsed = _extract(result)
    assert parsed["choices"][0]["message"]["content"] == "纯文本回复"


def test_extract_from_structured_content():
    completion = {"choices": [{"message": {"content": "x"}}]}
    result = {"structuredContent": completion}
    assert _extract(result) == completion


def test_extract_raises_on_unknown_shape():
    with pytest.raises(TransportError):
        _extract({"foo": "bar"})
