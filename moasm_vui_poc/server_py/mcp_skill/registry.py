"""SkillRegistry：商店选购的按用户缓存（设计 最终技术路线.md §4.2）。

resolve() 的 TTL 缓存让多数请求不发网络 IO；网络 IO 在锁外，避免把商店延迟
串进所有用户的聊天线程。TTL 语义：用户改选购后最多 ttl 秒生效。

并发：registry 自带锁；ChatService 另有锁做"锁内重验版本、杜绝并发重复建图"，
两层职责不同，见 §4.3。
"""

from __future__ import annotations

import threading
import time

from .manifest import SkillManifest


class SkillRegistry:
    def __init__(self, store, ttl: float = 30.0):
        self._store = store
        self._ttl = ttl
        # user_id -> (fetched_at_monotonic, version, [SkillManifest])
        self._cache: dict[str, tuple[float, int, list[SkillManifest]]] = {}
        self._lock = threading.Lock()

    def resolve(self, user_id: str) -> tuple[int, list[SkillManifest]]:
        """返回 (version, manifests)。TTL 内命中直接返回；否则锁外 sync 后写缓存。"""
        now = time.monotonic()
        with self._lock:  # 查缓存是短临界区
            hit = self._cache.get(user_id)
            if hit and now - hit[0] < self._ttl:
                return hit[1], hit[2]

        sync = self._store.sync(user_id)  # 锁外网络 IO

        with self._lock:
            self._cache[user_id] = (
                time.monotonic(),
                sync["version"],
                [SkillManifest.from_dict(m) for m in sync["skills"]],
            )
            _, version, manifests = self._cache[user_id]
            return version, manifests

    def invalidate(self, user_id: str) -> None:
        """用户改选购后立刻生效用（可选；演示可用它代替等 TTL）。"""
        with self._lock:
            self._cache.pop(user_id, None)
