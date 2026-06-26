"""高德地图 A2A 客户端（Google A2A 协议 / JSON-RPC 2.0）。

协议要点（见高德官方 A2A 接入文档）：
    - Endpoint: https://agent.amap.com/a2a/agent/ai_native
    - 鉴权: HTTP header  key: <AMAP_KEY>
    - method: "message/send"（一次性返回）/ "message/stream"（SSE 流式）
    - params.message 为 A2A Message 结构（role + parts[]）
返回（非流式）：result 里含一个 Message（或 Task，里面再含 message/artifact）。
"""

from __future__ import annotations

import json
import uuid

import requests

from .errors import AmapError
from .models import MapResult

_URL = "https://mcp.amap.com/a2a/agent/ai_native"
_TIMEOUT = (10, 60)


class AmapClient:
    def __init__(self, key: str, session: requests.Session | None = None):
        self._key = key
        self._session = session or requests.Session()

    def send(self, message: dict) -> MapResult:
        """非流式：method=message/send，返回完整 MapResult。"""
        payload = self._rpc_payload("message/send", message)
        try:
            resp = self._session.post(
                _URL, json=payload, headers=self._headers(), timeout=_TIMEOUT
            )
        except requests.RequestException as e:
            raise AmapError(f"高德请求失败: {e}") from e
        if not resp.ok:
            raise AmapError(f"高德返回 {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        if data.get("error"):
            err = data["error"]
            raise AmapError(f"高德 A2A 错误: {err.get('message')} ({err.get('code')})")
        return self._extract(data.get("result") or {})

    def _rpc_payload(self, method: str, message: dict) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": uuid.uuid4().hex,
            "method": method,
            "params": {"message": message},
        }

    def _headers(self) -> dict:
        return {"Content-Type": "application/json", "key": self._key}

    @staticmethod
    def _extract(result: dict) -> MapResult:
        """result 可能直接是 Message，也可能是 Task（含 status.message 或 artifacts）。

        非流式 message/send 下，高德把流式过程的每个分片都落成一个独立 artifact
        （tips「思考中…」、custom_message、若干 markdown 正文片段、source、guide…），
        真正的回答文本散落在多个 type=markdown 的 DataPart 里，需要按序拼接。
        """
        if result.get("parts"):  # 直接就是 Message
            return MapResult.from_message(result)

        status = result.get("status") or {}
        if status.get("message"):
            return MapResult.from_message(status["message"])

        artifacts = result.get("artifacts") or []
        if artifacts:
            parts: list = []
            for a in artifacts:
                parts.extend(a.get("parts") or [])
            return MapResult.from_message({"parts": parts}, raw=result)

        # 兜底：把整个 result 序列化出来，避免吞掉信息
        return MapResult(text=json.dumps(result, ensure_ascii=False), raw=result)
