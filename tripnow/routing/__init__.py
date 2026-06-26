"""顶层分流编排层：闲聊 / TripNow / 快递100 / 高德 的统一路由。

用法：
    from routing import build_dispatcher, RouteContext
    dispatcher = build_dispatcher()
    result = dispatcher.dispatch("我的快递 12345678 到哪了", RouteContext())
    print(result.intent, result.text)
"""

from .classifier import GeminiClassifier, IntentClassifier, KeywordClassifier
from .dispatcher import Dispatcher
from .factory import build_dispatcher
from .gemini import GeminiClient, GeminiError
from .handler import Handler, IntentSpec, RouteContext, RouteResult
from .history import SessionHistory, Turn
from .logconf import setup_logging

__all__ = [
    "build_dispatcher",
    "setup_logging",
    "Dispatcher",
    "Handler",
    "IntentSpec",
    "RouteContext",
    "RouteResult",
    "IntentClassifier",
    "GeminiClassifier",
    "KeywordClassifier",
    "GeminiClient",
    "GeminiError",
    "SessionHistory",
    "Turn",
]
