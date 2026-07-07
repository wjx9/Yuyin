"""服务端数据契约：请求/响应。与具体传输（HTTP/WS）无关，纯数据 + 校验。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class BadRequest(ValueError):
    """请求体不合法（缺字段/类型错），由传输层映射成 400。"""


_PLATFORMS = ("pc", "mobile")


def normalize_platform(v: Any) -> str:
    """把入参归一成受支持的 platform；缺省/空 → "pc"，未知值视为非法（400）。

    /chat（请求体）与 /health（查询参数）共用此校验，保证"哪些端能看到哪些能力"只有一处判定。
    """
    if v is None or v == "":
        return "pc"
    if not isinstance(v, str) or v.strip() not in _PLATFORMS:
        raise BadRequest(f"字段 'platform' 只能是 {' / '.join(_PLATFORMS)}")
    return v.strip()


def _require_str(d: dict, key: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise BadRequest(f"字段 {key!r} 必填且为非空字符串")
    return v.strip()


def _optional_str(d: dict, key: str) -> str | None:
    v = d.get(key)
    if v is None:
        return None
    if not isinstance(v, str):
        raise BadRequest(f"字段 {key!r} 必须是字符串")
    return v.strip() or None


@dataclass
class ChatRequest:
    """一轮对话请求。

    query      —— 用户这轮说的话（语音助手里由端侧 ASR 转好的文本）
    session_id —— 客户端生成并固定的会话 id，服务端据此隔离多轮历史
    user_id    —— 我方平台的用户账号；将来真鉴权时用它查该用户的三方 token（现 mock）
    location   —— "经度,纬度"，供高德等基于位置的能力使用（可空）
    platform   —— 发起端类型："pc"（chat_app / client_py）或 "mobile"（client_flutter）。
                  据此屏蔽 PC-only 能力（如 music_control：只控服务端本机 mpv，对移动端无意义）。
                  缺省 "pc"，即老客户端不带此字段时行为不变。
    include_data—— 是否需要结构化数据（当前服务端只回文本，预留）
    """

    query: str
    session_id: str
    user_id: str = "mock-user"
    location: str | None = None
    platform: str = "pc"
    include_data: bool = True

    @classmethod
    def from_dict(cls, d: Any) -> "ChatRequest":
        if not isinstance(d, dict):
            raise BadRequest("请求体必须是 JSON 对象")
        user_id = _optional_str(d, "user_id") or "mock-user"
        include_data = d.get("include_data", True)
        if not isinstance(include_data, bool):
            raise BadRequest("字段 'include_data' 必须是布尔")
        return cls(
            query=_require_str(d, "query"),
            session_id=_require_str(d, "session_id"),
            user_id=user_id,
            location=_optional_str(d, "location"),
            platform=normalize_platform(d.get("platform")),
            include_data=include_data,
        )


@dataclass
class ChatResponse:
    """一轮对话响应：文本 + 命中意图 + 可选结构化 data + 可选 A2UI 卡片。

    data 仅在 handler 产出可序列化 dict 时下发（如音乐：含 orpheus 深链供端侧拉起 app）；
    多数能力的结构化结果（行程/新闻等富对象）暂不序列化，data 为 None。
    a2ui 是 A2UI v0.9 消息列表（createSurface + updateComponents），仅对声明了
    富 UI 能力的端（platform=mobile 的 client_flutter）在命中可卡片化意图时下发，
    由端上 genui 渲染；text 仍完整下发（TTS 朗读与纯文本端不受影响）。
    """

    text: str
    intent: str
    session_id: str
    data: dict | None = None
    a2ui: list[dict] | None = None

    def to_dict(self) -> dict:
        d = {"text": self.text, "intent": self.intent, "session_id": self.session_id}
        if self.data is not None:
            d["data"] = self.data
        if self.a2ui is not None:
            d["a2ui"] = self.a2ui
        return d
