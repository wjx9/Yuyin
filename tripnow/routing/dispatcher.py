"""分发器：把 query 分类到某个 Handler 并执行。

Dispatcher 从注册的 handlers 自动收集意图列表喂给分类器，因此"加能力"只是往
handlers 多塞一个对象，分类与分发逻辑零改动。
"""

from __future__ import annotations

import logging
import time

from .classifier import IntentClassifier
from .handler import Handler, IntentSpec, RouteContext, RouteResult

_log = logging.getLogger("routing.dispatcher")


class Dispatcher:
    def __init__(
        self,
        handlers: list[Handler],
        classifier: IntentClassifier,
        default_intent: str,
    ):
        self._handlers = {h.intent: h for h in handlers}
        if default_intent not in self._handlers:
            raise ValueError(f"default_intent {default_intent!r} 不在已注册 handlers 中")
        self._classifier = classifier
        self._default = default_intent
        self._specs = [h.spec() for h in handlers]

    @property
    def intents(self) -> list[str]:
        return list(self._handlers)

    @property
    def specs(self) -> list[IntentSpec]:
        """各能力的 (id, description)，供呈现层生成用法介绍等。"""
        return list(self._specs)

    def classify(self, query: str) -> str:
        return self._classifier.classify(query, self._specs, default=self._default)

    def dispatch(self, query: str, context: RouteContext | None = None) -> RouteResult:
        context = context or RouteContext()
        _log.info("收到 query: %r", query)

        t0 = time.perf_counter()
        intent = self.classify(query)
        classify_ms = (time.perf_counter() - t0) * 1000

        handler = self._handlers.get(intent)
        if handler is None:
            _log.warning("意图 %r 未注册，回退默认 %r", intent, self._default)
            handler = self._handlers[self._default]
            intent = self._default
        _log.info(
            "路由 -> 技能 %r (%s)，分类耗时 %.0fms",
            intent,
            type(handler).__name__,
            classify_ms,
        )

        t1 = time.perf_counter()
        result = handler.handle(query, context)
        _log.info(
            "技能 %r 执行完成，耗时 %.0fms，结果长度 %d",
            result.intent or intent,
            (time.perf_counter() - t1) * 1000,
            len(result.text or ""),
        )
        return result
