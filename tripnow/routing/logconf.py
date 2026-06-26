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

_ROOT = "routing"
_configured = False


def setup_logging(level: str | None = None, formatter: logging.Formatter | None = None) -> None:
    """配置 routing 日志。level 省略时读环境变量 ROUTING_LOG_LEVEL（默认 WARNING）。

    formatter 可选：由呈现层（presentation）传入，决定日志怎么显示（如缩进/变暗），
    "日志长什么样"属于 UI 关注点，这里只负责"打不打、打什么内容"。省略则用默认格式。

    幂等：多次调用只生效第一次的 handler 安装，level 仍可被后续调用调整。
    """
    global _configured
    resolved = (level or os.getenv("ROUTING_LOG_LEVEL", "WARNING")).upper()
    logger = logging.getLogger(_ROOT)
    logger.setLevel(getattr(logging, resolved, logging.WARNING))

    if not _configured:
        handler = logging.StreamHandler()
        handler.setFormatter(formatter or logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.propagate = False  # 避免重复打印到 root
        _configured = True
