"""Exa Search API 的 HTTP 客户端。"""

from __future__ import annotations

from typing import Any

import requests

from .errors import ExaError

_SEARCH_URL = "https://api.exa.ai/search"
_TIMEOUT = (10, 30)
_VALID_SEARCH_TYPES = {
    "auto",
    "fast",
    "instant",
    "deep-lite",
    "deep",
    "deep-reasoning",
}


class ExaClient:
    def __init__(self, api_key: str, session: requests.Session | None = None):
        api_key = api_key.strip()
        if not api_key:
            raise ExaError("缺少 EXA_API_KEY")
        self._api_key = api_key
        self._session = session or requests.Session()

    def search(
        self,
        query: str,
        *,
        num_results: int = 5,
        search_type: str = "instant",
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ExaError("搜索内容不能为空")

        if not 1 <= num_results <= 10:
            raise ExaError("num_results 必须在 1 到 10 之间")

        if search_type not in _VALID_SEARCH_TYPES:
            raise ExaError(f"不支持的 Exa 搜索类型：{search_type}")

        payload = {
            "query": query,
            "type": search_type,
            "numResults": num_results,
            "contents": {
                "highlights": True,
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = self._session.post(
                _SEARCH_URL,
                json=payload,
                headers=headers,
                timeout=_TIMEOUT,
            )
        except requests.RequestException as error:
            raise ExaError(f"Exa 请求失败：{error}") from error

        try:
            data = response.json()
        except ValueError as error:
            raise ExaError(f"Exa 返回了无法解析的 JSON：{response.text[:200]}") from error

        if not response.ok:
            message = data.get("error") if isinstance(data, dict) else response.text[:200]
            raise ExaError(f"Exa REST 错误 {response.status_code}：{message}")

        if not isinstance(data, dict):
            raise ExaError("Exa 返回格式异常：根节点不是 JSON 对象")

        if data.get("error"):
            raise ExaError(f"Exa REST 错误：{data['error']}")

        return data