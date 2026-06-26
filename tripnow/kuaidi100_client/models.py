"""快递100 领域模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# 实时查询接口 state -> 中文状态
STATE_TEXT = {
    "0": "在途",
    "1": "已揽收",
    "2": "疑难",
    "3": "已签收",
    "4": "退签",
    "5": "派件中",
    "6": "退回",
    "7": "转投",
    "10": "待清关",
    "11": "清关中",
    "12": "已清关",
    "13": "清关异常",
    "14": "拒签",
}


@dataclass
class TrackNode:
    time: str
    context: str


@dataclass
class TrackResult:
    num: str
    com: str
    state: str
    nodes: list[TrackNode] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def state_text(self) -> str:
        return STATE_TEXT.get(self.state, "未知")

    @property
    def latest(self) -> str:
        return self.nodes[0].context if self.nodes else ""

    @classmethod
    def from_dict(cls, num: str, data: dict[str, Any]) -> "TrackResult":
        nodes = [
            TrackNode(time=d.get("ftime") or d.get("time", ""), context=d.get("context", ""))
            for d in data.get("data", []) or []
        ]
        return cls(
            num=data.get("nu", num),
            com=data.get("com", ""),
            state=str(data.get("state", "")),
            nodes=nodes,
            raw=data,
        )
