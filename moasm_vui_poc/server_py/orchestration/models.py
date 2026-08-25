"""Graph 编排层对上层返回的统一结果。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AssistantResult:
    text: str
    intent: str
    data: Any | None = None
    # 给 A2UI 使用的原始工具文本。
    # 新闻卡片等仍按原格式解析，不能改用大模型润色后的文本。
    card_text: str = ""