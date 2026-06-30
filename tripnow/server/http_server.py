"""标准库 HTTP 适配器（零额外依赖）。

只把 HTTP 报文翻译成 ChatRequest 交给 ChatService，再把 ChatResponse 写回 JSON。
ThreadingHTTPServer 一请求一线程：dispatch 是阻塞的（单轮可能数秒），靠线程并发；
同一会话的并发由 SessionStore 的 per-session 锁串行化。
将来迁阿里云若要异步/流式/WebSocket，可整体替换本文件为 FastAPI 等，ChatService 不动。
"""

from __future__ import annotations

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .schemas import BadRequest, ChatRequest
from .service import ChatService

_log = logging.getLogger("server.http")


class _Handler(BaseHTTPRequestHandler):
    server_version = "TripNowServer/1"

    @property
    def _service(self) -> ChatService:
        return self.server.chat_service  # type: ignore[attr-defined]

    @property
    def _token(self) -> str | None:
        return self.server.auth_token  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        if self.path == "/health":
            self._json(200, {"status": "ok", "capabilities": self._service.capabilities})
        else:
            self._json(404, {"error": "未知路径"})

    def do_POST(self) -> None:
        if self.path != "/chat":
            self._json(404, {"error": "未知路径"})
            return
        if not self._authorized():
            self._json(401, {"error": "未授权"})
            return
        try:
            req = ChatRequest.from_dict(self._read_json())
        except BadRequest as e:
            self._json(400, {"error": str(e)})
            return
        except ValueError as e:
            self._json(400, {"error": f"JSON 解析失败: {e}"})
            return
        try:
            resp = self._service.handle_chat(req)
        except Exception:  # 传输边界：吞掉异常细节，避免把堆栈泄露给客户端
            _log.exception("处理 /chat 失败")
            self._json(500, {"error": "服务器内部错误"})
            return
        self._json(200, resp.to_dict())

    def _authorized(self) -> bool:
        if not self._token:  # 未配置 token（局域网）则不鉴权
            return True
        return self.headers.get("Authorization", "") == f"Bearer {self._token}"

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length > 0 else b""
        if not raw:
            raise BadRequest("空请求体")
        return json.loads(raw.decode("utf-8"))

    def _json(self, status: int, payload: dict) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args) -> None:  # 走 logging，而非默认打到 stderr
        _log.info("%s %s", self.address_string(), fmt % args)


def build_http_server(
    service: ChatService,
    host: str = "0.0.0.0",
    port: int = 8000,
    auth_token: str | None = None,
) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.chat_service = service  # type: ignore[attr-defined]
    httpd.auth_token = auth_token  # type: ignore[attr-defined]
    return httpd
