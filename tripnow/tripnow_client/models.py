"""与传输方式无关的领域模型。

OpenApiClient 和 McpClient 都基于这些模型收发数据，因此业务层、表现层
完全不感知底层是 REST 还是 JSON-RPC。迁移到其他语言时，这一层就是协议契约。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

# 文档里 union_id 在参数表/MCP 中写作 "union_id"，但个人行程示例里写作 "unionId"。
# 默认用 union_id；若后端实际只认 unionId，把这里改成 "unionId" 即可（只改一处）。
UNION_ID_KEY = "union_id"


@dataclass
class Message:
    role: str  # "user" | "assistant" | "system"
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class ChatRequest:
    """一次对话请求。union_id 为空即"公开信息"调用，非空即"个人信息"调用。"""

    messages: list[Message]
    model: str = "tripnow-travel-pro"
    include_data: bool = False
    union_id: str | None = None
    stream: bool = False

    def to_payload(self) -> dict[str, Any]:
        """转成 chat/completions 的 JSON body（MCP 会把它塞进 arguments）。"""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.to_dict() for m in self.messages],
            "stream": self.stream,
            "include_data": self.include_data,
        }
        if self.union_id:
            payload[UNION_ID_KEY] = self.union_id
        return payload


@dataclass
class Usage:
    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Usage":
        data = data or {}
        details = data.get("details", {}) or {}
        return cls(
            total_tokens=data.get("total_tokens", 0),
            prompt_tokens=details.get("prompt_tokens", data.get("prompt_tokens", 0)),
            completion_tokens=details.get(
                "completion_tokens", data.get("completion_tokens", 0)
            ),
            raw=data,
        )


@dataclass
class Choice:
    content: str
    finish_reason: str | None = None
    # include_data=true 时的结构化数据（航班/车次/行程等），结构因场景而异，原样保留。
    model_data: Any | None = None


@dataclass
class ChatResponse:
    id: str
    model: str
    created: int
    choices: list[Choice]
    usage: Usage
    raw: dict[str, Any]  # 完整原始响应，便于调试或访问未建模字段

    @property
    def content(self) -> str:
        """便捷取首个回复的文本。"""
        return self.choices[0].content if self.choices else ""

    @property
    def model_data(self) -> Any | None:
        return self.choices[0].model_data if self.choices else None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ChatResponse":
        choices = []
        for c in data.get("choices", []) or []:
            msg = c.get("message") or {}
            choices.append(
                Choice(
                    content=msg.get("content", ""),
                    finish_reason=c.get("finish_reason"),
                    model_data=c.get("model_data"),
                )
            )
        return cls(
            id=data.get("id", ""),
            model=data.get("model", ""),
            created=data.get("created", 0),
            choices=choices,
            usage=Usage.from_dict(data.get("usage")),
            raw=data,
        )


@dataclass
class ChatChunk:
    """流式分片（仅 OpenAPI 支持）。"""

    delta: str
    finish_reason: str | None
    raw: dict[str, Any]


def build_messages(
    query: str, history: Iterable[Message] | None = None
) -> list[Message]:
    """把多轮历史 + 本轮 query 组装成 messages。"""
    msgs = list(history) if history else []
    msgs.append(Message(role="user", content=query))
    return msgs
