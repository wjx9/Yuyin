"""分流层日志配置。

调试日志默认关闭，由配置开关控制（.env 里的 ROUTING_LOG_LEVEL，或入口的 --debug）。
关闭时只输出 WARNING 及以上；打开（DEBUG）时会打印：
    - 分类器拿到的候选意图、Gemini 原始输出、是否回退兜底
    - 最终命中的意图与 Handler、耗时

约定：业务代码只管 logging.getLogger("routing.xxx").debug(...)，是否输出由这里统一决定，
与 Android 的 Log.d + 总开关同理。
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable

_ROOT = "routing"
_configured: set[str] = set()  # 已安装过 handler 的命名空间


def setup_logging(
    level: str | None = None,
    formatter: logging.Formatter | None = None,
    namespaces: Iterable[str] = (_ROOT,),
) -> None:
    """配置日志。level 省略时读环境变量 ROUTING_LOG_LEVEL（默认 WARNING）。

    formatter 可选：由呈现层（presentation）传入，决定日志怎么显示（如缩进/变暗），
    "日志长什么样"属于 UI 关注点，这里只负责"打不打、打什么内容"。省略则用默认格式。

    namespaces：要配置的 logger 命名空间，默认仅 "routing"；其它入口（如服务端）
    可传入自己的命名空间（如 "server"）以共用同一套开关与格式，本函数对命名空间无感。

    幂等：每个命名空间的 handler 只安装一次，level 仍可被后续调用调整。
    """
    resolved = (level or os.getenv("ROUTING_LOG_LEVEL", "WARNING")).upper()
    lvl = getattr(logging, resolved, logging.WARNING)

    for ns in namespaces:
        logger = logging.getLogger(ns)
        logger.setLevel(lvl)
        if ns not in _configured:
            handler = logging.StreamHandler()
            handler.setFormatter(
                formatter or logging.Formatter("[%(levelname)s] %(name)s: %(message)s")
            )
            logger.addHandler(handler)
            logger.propagate = False  # 避免重复打印到 root
            _configured.add(ns)
