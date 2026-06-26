"""会话记忆：滑动窗口式的多轮对话历史，跨进程落盘。

每次 `python chat_app.py "..."` 都是独立进程，进程退出内存即清空。为了让单轮
命令模式也能"记住"最近若干轮，这里把历史持久化到一个 JSON 文件：启动时 load，
每轮 append 后 save。deque(maxlen) 天然实现"超出上限丢最旧"的环形缓冲。

存储格式（JSON 数组，按时间正序，最旧在前）：
    [{"query": "...", "response": "..."}, ...]
"""

from __future__ import annotations

import json
import logging
import os
from collections import deque
from dataclasses import dataclass

_log = logging.getLogger("routing.history")

_DEFAULT_MAX_TURNS = 30
_DEFAULT_PATH = os.path.join(os.path.expanduser("~"), ".tripnow", "history.json")
# 单轮回复入库时的长度上限：避免一条新闻/行程长文把历史文件和后续 Gemini 上下文撑爆
_MAX_RESPONSE_CHARS = 1000


@dataclass
class Turn:
    """一个问答对。"""

    query: str
    response: str


class SessionHistory:
    """最近 max_turns 个问答对的滑动窗口，可选落盘。

    path=None 时纯内存、不落盘（适合交互模式只想要单次会话内记忆的场景）。
    """

    def __init__(self, path: str | None = _DEFAULT_PATH, max_turns: int = _DEFAULT_MAX_TURNS):
        self._path = path
        self._turns: deque[Turn] = deque(maxlen=max_turns)

    @property
    def turns(self) -> list[Turn]:
        """按时间正序返回当前窗口内的问答对（最旧在前，最新在后）。"""
        return list(self._turns)

    def load(self) -> None:
        """从磁盘读取历史；文件不存在或损坏时静默从空开始。"""
        if not self._path or not os.path.isfile(self._path):
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError) as e:
            _log.warning("读取历史失败，忽略：%s", e)
            return
        if not isinstance(raw, list):
            return
        for item in raw:
            if not isinstance(item, dict):
                continue
            q, r = item.get("query"), item.get("response")
            if isinstance(q, str) and isinstance(r, str):
                self._turns.append(Turn(q, r))

    def append(self, query: str, response: str) -> None:
        """记录一轮；超出 max_turns 时自动丢弃最旧的一轮。"""
        if len(response) > _MAX_RESPONSE_CHARS:
            response = response[:_MAX_RESPONSE_CHARS] + "…（已截断）"
        self._turns.append(Turn(query, response))

    def save(self) -> None:
        """把当前窗口写回磁盘；写失败仅告警，不影响主流程。"""
        if not self._path:
            return
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(
                    [{"query": t.query, "response": t.response} for t in self._turns],
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except OSError as e:
            _log.warning("写入历史失败，忽略：%s", e)

    def clear(self) -> None:
        """清空内存窗口并删除磁盘文件。"""
        self._turns.clear()
        if self._path and os.path.isfile(self._path):
            try:
                os.remove(self._path)
            except OSError as e:
                _log.warning("清除历史失败，忽略：%s", e)
