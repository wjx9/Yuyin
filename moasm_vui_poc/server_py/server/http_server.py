"""标准库 HTTP 适配器（零额外依赖）。

只把 HTTP 报文翻译成 ChatRequest 交给 ChatService，再把 ChatResponse 写回 JSON。
ThreadingHTTPServer 一请求一线程：dispatch 是阻塞的（单轮可能数秒），靠线程并发；
同一会话的并发由 SessionStore 的 per-session 锁串行化。
将来迁阿里云若要异步/流式/WebSocket，可整体替换本文件为 FastAPI 等，ChatService 不动。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .schemas import BadRequest, ChatRequest, normalize_platform
from .service import ChatService

_log = logging.getLogger("server.http")


def _first_qs(query: str, key: str) -> str | None:
    """取查询串里某参数的首个值（无则 None）。"""
    values = parse_qs(query).get(key)
    return values[0] if values else None


class _Handler(BaseHTTPRequestHandler):
    server_version = "TripNowServer/1"

    @property
    def _service(self) -> ChatService:
        return self.server.chat_service  # type: ignore[attr-defined]

    @property
    def _token(self) -> str | None:
        return self.server.auth_token  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        if parts.path in ("/", "/skill-store", "/skill-store/") or parts.path.startswith("/skill-store/"):
            if parts.path == "/":
                self._landing()
            else:
                self._proxy_store("GET")
            return
        if parts.path == "/health":
            # 能力清单按端过滤：client_flutter 带 ?platform=mobile，拿不到 PC-only 能力（music_control）。
            # 不带该参数（chat_app/client_py 或老客户端）默认 pc，全量能力，行为不变。
            # ?user_id= 则返回该用户的能力（内置 + 已选购 MCP），仍按 platform 过滤（设计 §4.5）。
            try:
                platform = normalize_platform(_first_qs(parts.query, "platform"))
            except BadRequest as e:
                self._json(400, {"error": str(e)})
                return
            user_id = _first_qs(parts.query, "user_id")
            if user_id:
                capabilities = self._service.capabilities_for_user(user_id, platform)
            else:
                capabilities = self._service.capabilities_for(platform)
            self._json(200, {"status": "ok", "capabilities": capabilities})
        else:
            self._json(404, {"error": "未知路径"})

    def do_POST(self) -> None:
        if self.path == "/skill-store" or self.path.startswith("/skill-store/"):
            self._proxy_store("POST")
            return
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

    def do_PUT(self) -> None:
        if self.path == "/skill-store" or self.path.startswith("/skill-store/"):
            self._proxy_store("PUT")
            return
        self._json(404, {"error": "未知路径"})

    def do_DELETE(self) -> None:
        if self.path == "/skill-store" or self.path.startswith("/skill-store/"):
            self._proxy_store("DELETE")
            return
        self._json(404, {"error": "未知路径"})

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

    def _landing(self) -> None:
        html = ("<!doctype html><meta charset='utf-8'><title>语音助手</title>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<h2>语音助手服务</h2><p><a href='/skill-store/'>打开技能商店</a></p>")
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _proxy_store(self, method: str) -> None:
        """把 8000/skill-store/* 转发到内部技能商店；手机和浏览器只需一个端口。"""
        base = getattr(self.server, "skill_store_url", None)  # type: ignore[attr-defined]
        if not base:
            self._json(503, {"error": "技能商店未配置"})
            return
        suffix = self.path[len("/skill-store"):] or "/"
        url = base.rstrip("/") + suffix
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        headers = {"Content-Type": self.headers.get("Content-Type", "application/json")}
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                payload = resp.read()
                status = resp.status
                content_type = resp.headers.get("Content-Type", "application/octet-stream")
        except urllib.error.HTTPError as e:
            payload = e.read()
            status = e.code
            content_type = e.headers.get("Content-Type", "application/json")
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            self._json(503, {"error": f"技能商店不可达：{type(e).__name__}"})
            return
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args) -> None:  # 走 logging，而非默认打到 stderr
        _log.info("%s %s", self.address_string(), fmt % args)


def build_http_server(
    service: ChatService,
    host: str = "0.0.0.0",
    port: int = 8000,
    auth_token: str | None = None,
    skill_store_url: str | None = None,
) -> ThreadingHTTPServer:
    httpd = ThreadingHTTPServer((host, port), _Handler)
    httpd.chat_service = service  # type: ignore[attr-defined]
    httpd.auth_token = auth_token  # type: ignore[attr-defined]
    httpd.skill_store_url = skill_store_url  # type: ignore[attr-defined]
    return httpd
