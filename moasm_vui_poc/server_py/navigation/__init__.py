"""导航对话引擎模块。

基于技术设计文档实现的高德导航接入POC，核心包括：
- 导航状态机
- 对话控制权管理（PRIMARY / AMAP_AGENT）
- 云侧前置判断层（非导航意图拦截）
- 主动召回机制
- 5个边界场景处理

快速开始：
    from navigation import NavigationEngine, PoiSearchService, NavigationService

    poi_service = PoiSearchService.from_key("your_amap_key")
    engine = NavigationEngine(poi_service)

    reply = engine.handle("导航到大新")
    print(reply.text)
"""

from .engine import NavigationEngine
from .intent import NavigationIntentClassifier
from .models import IntentResult, NavCommand, NavContext, NavReply, Poi
from .nav_service import NavigationResult, NavigationService
from .poi_service import PoiSearchService
from .state import Controller, NavEvent, NavState

__all__ = [
    "NavigationEngine",
    "NavigationIntentClassifier",
    "IntentResult",
    "NavCommand",
    "NavContext",
    "NavReply",
    "Poi",
    "NavigationResult",
    "NavigationService",
    "PoiSearchService",
    "Controller",
    "NavEvent",
    "NavState",
]
