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

    @staticmethod
    def _visible(handler: Handler, platform: str) -> bool:
        """该 handler 是否对指定端可见：PC-only 能力对 mobile 隐藏（不进能力清单、不参与分类）。"""
        return not (handler.pc_only and platform == "mobile")

    def intents_for(self, platform: str = "pc") -> list[str]:
        """指定端可用的意图 id 列表（供 /health 能力清单按端过滤）。"""
        return [i for i, h in self._handlers.items() if self._visible(h, platform)]

    @property
    def intents(self) -> list[str]:
        return self.intents_for("pc")

    @property
    def specs(self) -> list[IntentSpec]:
        """各能力的 (id, description)，供呈现层生成用法介绍等（PC 全量）。"""
        return list(self._specs)

    def _specs_for(self, platform: str) -> list[IntentSpec]:
        return [h.spec() for h in self._handlers.values() if self._visible(h, platform)]

    def classify(self, query: str, platform: str = "pc") -> str:
        return self._classifier.classify(query, self._specs_for(platform), default=self._default)

    def dispatch(self, query: str, context: RouteContext | None = None) -> RouteResult:
        context = context or RouteContext()
        _log.info("收到 query: %r (platform=%s)", query, context.platform)

        t0 = time.perf_counter()
        intent = self.classify(query, context.platform)
        classify_ms = (time.perf_counter() - t0) * 1000

        handler = self._handlers.get(intent)
        # 未注册，或该端不可见（PC-only 能力被 mobile 请求命中）——都回退默认。
        # 正常路径下分类器压根看不到隐藏能力，这里是防御性兜底（如关键词兜底分类器命中）。
        if handler is None or not self._visible(handler, context.platform):
            _log.warning("意图 %r 对 platform=%s 不可用，回退默认 %r", intent, context.platform, self._default)
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
