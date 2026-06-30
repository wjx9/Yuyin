"""多会话历史隔离。

每个 session_id 一份独立的 SessionHistory（默认纯内存，互不干扰），并配一把锁，
保证同一会话的并发请求串行追加历史（避免多轮交错），不同会话可并行。
默认内存态：进程重启即清空，适合 demo/试用；将来要持久化可给每个 session 落一份盘。
"""

from __future__ import annotations

import threading

from routing import SessionHistory


class SessionStore:
    def __init__(self, max_turns: int = 30):
        self._max_turns = max_turns
        self._histories: dict[str, SessionHistory] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def get(self, session_id: str) -> SessionHistory:
        with self._guard:
            hist = self._histories.get(session_id)
            if hist is None:
                hist = SessionHistory(path=None, max_turns=self._max_turns)  # 纯内存、会话隔离
                self._histories[session_id] = hist
            return hist

    def lock_for(self, session_id: str) -> threading.Lock:
        with self._guard:
            lock = self._locks.get(session_id)
            if lock is None:
                lock = threading.Lock()
                self._locks[session_id] = lock
            return lock
