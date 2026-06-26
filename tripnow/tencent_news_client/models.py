"""腾讯新闻领域模型。

腾讯新闻官方只提供 Skill/CLI 接入（tencent-news-cli），没有公开的直连 REST。
CLI 的 stdout 已是人类可读文本（截图里是 markdown），我们原样保留为 text；
若 stdout 恰好是 JSON，则顺手解析进 data 供上层结构化使用。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NewsResult:
    text: str
    data: Any | None = None  # stdout 若为 JSON 则解析后放这里，否则 None
    raw: str = ""            # 原始 stdout，便于调试

    @classmethod
    def from_stdout(cls, stdout: str) -> "NewsResult":
        text = (stdout or "").strip()
        data = _try_json(text)
        return cls(text=text, data=data, raw=stdout)


def _try_json(text: str) -> Any | None:
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None
