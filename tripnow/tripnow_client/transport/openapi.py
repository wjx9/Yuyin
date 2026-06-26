"""OpenAPI 接入：REST + OpenAI 兼容，支持流式。"""

from __future__ import annotations

import json
from typing import Iterator

import requests

from ..errors import AuthError, TransportError
from ..models import ChatChunk, ChatRequest, ChatResponse
from .base import TripNowTransport

_TIMEOUT = (10, 120)  # (连接, 读取) 秒


class OpenApiClient(TripNowTransport):
    def __init__(self, endpoint: str, api_key: str, session: requests.Session | None = None):
        self._endpoint = endpoint
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._session = session or requests.Session()

    @property
    def supports_stream(self) -> bool:
        return True

    def chat(self, request: ChatRequest) -> ChatResponse:
        request.stream = False
        resp = self._post(request.to_payload(), stream=False)
        return ChatResponse.from_dict(resp.json())

    def chat_stream(self, request: ChatRequest) -> Iterator[ChatChunk]:
        request.stream = True
        resp = self._post(request.to_payload(), stream=True)
        for chunk in self._iter_sse(resp):
            yield chunk

    def close(self) -> None:
        self._session.close()

    # --- 内部实现 ---

    def _post(self, payload: dict, *, stream: bool) -> requests.Response:
        try:
            resp = self._session.post(
                self._endpoint,
                headers=self._headers,
                json=payload,
                stream=stream,
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            raise TransportError(f"请求 TripNow OpenAPI 失败: {e}") from e

        if resp.status_code in (401, 403):
            raise AuthError(f"鉴权失败({resp.status_code})，请检查 api_key")
        if not resp.ok:
            raise TransportError(
                f"OpenAPI 返回 {resp.status_code}: {resp.text[:500]}",
                status=resp.status_code,
            )
        return resp

    @staticmethod
    def _iter_sse(resp: requests.Response) -> Iterator[ChatChunk]:
        """解析 SSE 流（data: {...} 行），逐分片产出。"""
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip()
            if line.startswith("data:"):
                line = line[len("data:"):].strip()
            if not line or line == "[DONE]":
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or [{}]
            c0 = choices[0]
            delta = (c0.get("delta") or {}).get("content", "") or ""
            yield ChatChunk(
                delta=delta, finish_reason=c0.get("finish_reason"), raw=obj
            )
