"""ServerClient：唯一知道 HTTP 契约的地方。

契约（见 README §8.10 / server/schemas.py）：
    GET  /health -> { "status": "ok", "capabilities": [...] }
    POST /chat   { query, session_id, user_id?, location? } -> { text, intent, session_id }
    鉴权(可选)    Authorization: Bearer <token>

上层（app / run_cases）只调 health() / chat()，拿到的是普通 Python 对象，不碰传输细节。
将来服务端换流式/WebSocket，只改这一个文件即可，与服务端 http_server.py 的设计对称。
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

from .config import ClientConfig


class ServerError(RuntimeError):
    """与服务端通信失败（网络错误 / 非 2xx / 响应体不合法）。"""


@dataclass
class ChatReply:
    text: str
    intent: str
    session_id: str


@dataclass
class HealthInfo:
    status: str
    capabilities: list[str]


class ServerClient:
    def __init__(self, config: ClientConfig | None = None):
        self.config = config or ClientConfig.from_env()
        self._http = requests.Session()
        if self.config.auth_token:
            self._http.headers["Authorization"] = f"Bearer {self.config.auth_token}"

    @property
    def session_id(self) -> str:
        return self.config.session_id

    def health(self) -> HealthInfo:
        data = self._get("/health")
        return HealthInfo(
            status=str(data.get("status", "")),
            capabilities=list(data.get("capabilities", [])),
        )

    def chat(self, query: str, *, location: str | None = None) -> ChatReply:
        """发一轮对话。location 缺省用配置里的默认位置。"""
        payload = {
            "query": query,
            "session_id": self.config.session_id,
            "user_id": self.config.user_id,
        }
        loc = location if location is not None else self.config.location
        if loc:
            payload["location"] = loc
        data = self._post("/chat", payload)
        try:
            return ChatReply(
                text=data["text"], intent=data["intent"], session_id=data["session_id"]
            )
        except (KeyError, TypeError) as e:
            raise ServerError(f"响应体缺字段: {e}") from e

    # ---- 传输细节 ----

    def _get(self, path: str) -> dict:
        try:
            r = self._http.get(self.config.server_url + path, timeout=self.config.timeout)
        except requests.RequestException as e:
            raise ServerError(f"连接服务端失败: {e}") from e
        return self._parse(r)

    def _post(self, path: str, payload: dict) -> dict:
        try:
            r = self._http.post(
                self.config.server_url + path, json=payload, timeout=self.config.timeout
            )
        except requests.RequestException as e:
            raise ServerError(f"连接服务端失败: {e}") from e
        return self._parse(r)

    def _parse(self, r: requests.Response) -> dict:
        if r.status_code >= 400:
            # 服务端错误体形如 {"error": "..."}；取出来给用户更友好的提示
            detail = ""
            try:
                detail = r.json().get("error", "")
            except ValueError:
                detail = (r.text or "").strip()[:200]
            raise ServerError(f"服务端返回 {r.status_code}{('：' + detail) if detail else ''}")
        try:
            return r.json()
        except ValueError as e:
            raise ServerError(f"响应非 JSON: {e}") from e
