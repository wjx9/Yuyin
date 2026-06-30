"""MCP 接入：JSON-RPC 2.0，tools/call 包裹 chat_completions。不支持流式。

注意：MCP tools/call 返回一次性结果，文档未给出 result 的确切结构，因此对
result 做了兼容解析（既支持直接返回 chat.completion，也支持 MCP 标准的
content 文本块里嵌 JSON）。这是与外部系统交互的边界，需要防御性解析。
"""

from __future__ import annotations

import json
from itertools import count
from typing import Any

import requests

from ..errors import AuthError, TransportError
from ..models import ChatRequest, ChatResponse
from .base import TripNowTransport

_TIMEOUT = (10, 120)


class McpClient(TripNowTransport):
    def __init__(self, endpoint: str, api_key: str, session: requests.Session | None = None):
        self._endpoint = endpoint
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._session = session or requests.Session()
        self._ids = count(1)

    # --- TripNowTransport ---

    def chat(self, request: ChatRequest) -> ChatResponse:
        request.stream = False  # MCP 强制非流式
        result = self._call_tool("chat_completions", request.to_payload())
        return ChatResponse.from_dict(self._extract_completion(result))

    def close(self) -> None:
        self._session.close()

    # --- PromptsCapable（MCP 独有能力）---

    def get_prompts(self) -> Any:
        return self._call_tool("get_agent_intents_prompts", {})

    def update_prompts(self, prompts: list[dict[str, Any]]) -> Any:
        """批量覆盖当前账户 channel 下的 prompts，谨慎调用。"""
        return self._call_tool("update_agent_intents_prompts", {"prompts": prompts})

    def initialize(self) -> Any:
        return self._rpc("initialize", None)

    def list_tools(self) -> Any:
        return self._rpc("tools/list", {})

    # --- 内部实现 ---

    def _call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        return self._rpc("tools/call", {"name": name, "arguments": arguments})

    def _rpc(self, method: str, params: Any) -> Any:
        body: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": next(self._ids),
            "method": method,
        }
        if params is not None:
            body["params"] = params

        try:
            resp = self._session.post(
                self._endpoint, headers=self._headers, json=body, timeout=_TIMEOUT
            )
        except requests.RequestException as e:
            raise TransportError(f"请求 TripNow MCP 失败: {e}") from e

        if resp.status_code in (401, 403):
            raise AuthError(f"鉴权失败({resp.status_code})，请检查 api_key")
        if not resp.ok:
            raise TransportError(
                f"MCP 返回 {resp.status_code}: {resp.text[:500]}",
                status=resp.status_code,
            )

        data = resp.json()
        if "error" in data and data["error"]:
            err = data["error"]
            raise TransportError(
                f"JSON-RPC 错误 {err.get('code')}: {err.get('message')}",
                payload=err,
            )
        return data.get("result")

    @staticmethod
    def _extract_completion(result: Any) -> dict[str, Any]:
        """从 tools/call 的 result 中取出 chat.completion JSON。"""
        if isinstance(result, dict):
            # 形态一：result 直接就是 chat.completion
            if "choices" in result:
                return result
            # 形态二：MCP 标准 content 块，文本里是 JSON 字符串
            content = result.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        try:
                            return json.loads(block.get("text", ""))
                        except json.JSONDecodeError:
                            return {
                                "choices": [
                                    {"message": {"content": block.get("text", "")}}
                                ]
                            }
            # 形态三：structuredContent
            structured = result.get("structuredContent")
            if isinstance(structured, dict):
                return structured
        raise TransportError(f"无法解析 MCP chat_completions 结果: {result!r}")
