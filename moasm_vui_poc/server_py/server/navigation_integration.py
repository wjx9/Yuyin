"""导航引擎服务端集成。

在 ChatService.handle_chat 中前置拦截导航相关请求，按 session_id 维护
NavigationEngine 实例，确保多轮导航对话状态不丢失。

处理逻辑：
  1. 当前会话处于导航流程中（非 IDLE）→ 所有请求由导航引擎处理
     （含非导航意图，引擎内置云侧前置判断层会拦截并主动召回）
  2. 当前会话处于 IDLE → 仅导航意图由导航引擎处理，其余返回 None
     走正常 assistant_graph 流程
"""

from __future__ import annotations

import logging
import os
import threading
from collections import OrderedDict

from navigation import (
    Controller,
    NavState,
    NavigationEngine,
    NavigationService,
    PoiSearchService,
)
from navigation.intent import NavigationIntentClassifier

from .schemas import ChatRequest, ChatResponse

_log = logging.getLogger("server.navigation")

# 存活导航会话上限（LRU 淘汰）
MAX_NAV_SESSIONS = 100


def _build_poi_service() -> PoiSearchService:
    """构建 POI 搜索服务：有 AMAP_KEY 用真实 API，否则用 mock。"""
    amap_key = os.getenv("AMAP_KEY", "").strip()
    if amap_key:
        try:
            return PoiSearchService.from_key(amap_key)
        except Exception as e:
            _log.warning("初始化真实高德POI服务失败，回退mock: %s", e)
    # Mock 实现
    from navigation.demo import MockPoiService
    return MockPoiService()


def _server_non_nav_handler(text: str) -> str:
    """导航引擎内的非导航意图处理器（POC 阶段用 mock 回复）。

    在导航流程中，云侧前置判断层会拦截非导航意图，调用此函数模拟主助手处理，
    同时导航引擎会主动召回是否继续导航。
    后续优化：可注入真正的主助手处理函数，保证非导航请求的回复质量。
    """
    if "闹钟" in text:
        return "好的，已为你查看闹钟：你明天有3个闹钟（7:00起床、8:30出门、9:00晨会）。"
    if "天气" in text:
        return "深圳今天多云转晴，26-32℃，东南风3级，空气质量优。"
    if "笑话" in text or "讲个" in text:
        return "程序员最讨厌的数字是什么？是1024，因为它总让人想起加班。"
    if "音乐" in text or "歌" in text:
        return "好的，为你播放周杰伦的《晴天》。"
    return f"好的，已为你处理：{text}"


class NavigationSessionManager:
    """按 session_id 管理 NavigationEngine 实例（LRU 淘汰）。"""

    def __init__(self, max_sessions: int = MAX_NAV_SESSIONS):
        self._engines: OrderedDict[str, NavigationEngine] = OrderedDict()
        self._lock = threading.Lock()
        self._max_sessions = max_sessions
        self._poi_service = _build_poi_service()
        self._nav_service = NavigationService()
        self._classifier = NavigationIntentClassifier()

    def get_or_create(self, session_id: str) -> NavigationEngine:
        """获取或创建该会话的导航引擎。"""
        with self._lock:
            engine = self._engines.get(session_id)
            if engine is not None:
                self._engines.move_to_end(session_id)
                return engine

            engine = NavigationEngine(
                self._poi_service,
                nav_service=self._nav_service,
                non_nav_handler=_server_non_nav_handler,
            )
            self._engines[session_id] = engine
            self._engines.move_to_end(session_id)

            # LRU 淘汰
            while len(self._engines) > self._max_sessions:
                sid, _ = self._engines.popitem(last=False)
                _log.info("LRU 淘汰导航会话: %s", sid)

            return engine

    def is_navigation_intent(self, text: str) -> bool:
        """判断输入是否是导航意图（用于 IDLE 状态下的前置判断）。"""
        result = self._classifier.classify(text)
        return result.is_navigation_intent

    def reset(self, session_id: str) -> None:
        """重置指定会话的导航引擎。"""
        with self._lock:
            engine = self._engines.pop(session_id, None)
            if engine:
                engine.reset()


# 全局单例
_manager: NavigationSessionManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> NavigationSessionManager:
    """获取全局导航会话管理器单例。"""
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = NavigationSessionManager()
    return _manager


def try_handle_navigation(req: ChatRequest) -> ChatResponse | None:
    """尝试用导航引擎处理请求。

    返回 ChatResponse 表示已由导航引擎处理；返回 None 表示应走正常主流程。
    """
    manager = get_manager()
    engine = manager.get_or_create(req.session_id)

    # 判断是否应由导航引擎处理
    in_nav_flow = engine.nav_state != NavState.IDLE
    is_nav_intent = manager.is_navigation_intent(req.query)

    if not in_nav_flow and not is_nav_intent:
        # IDLE 状态且非导航意图 → 走正常主流程
        return None

    _log.info(
        "导航引擎接管: session=%s, in_flow=%s, is_nav=%s, state=%s, query=%s",
        req.session_id, in_nav_flow, is_nav_intent, engine.nav_state.value, req.query[:50],
    )

    # 由导航引擎处理
    reply = engine.handle(req.query)

    # 非导航意图召回：导航引擎识别到这不是导航指令，透明交还给主语音助手
    # 导航状态由 NavigationSessionManager 按 session_id 保留，不丢失
    if reply.handover_requested and reply.handover_reason == "non_navigation_intercept":
        _log.info(
            "非导航意图召回，走主语音助手流程: session=%s, query=%s",
            req.session_id, req.query[:50],
        )
        return None

    # 构造 ChatResponse
    # intent 字段：用导航状态作为意图标识，方便端侧识别
    intent = f"navigation.{reply.nav_state.value}"
    if reply.handover_requested:
        intent = f"navigation.handover.{reply.handover_reason or 'unknown'}"

    # data 字段：携带导航上下文 + 导航控制指令，供手机端使用
    data = {
        "nav_state": reply.nav_state.value,
        "controller": reply.controller.value,
        "is_in_navigation": reply.nav_context.is_in_navigation,
        "destination": reply.nav_context.destination,
        "poi_list": [
            {
                "name": p.name,
                "address": p.address,
                "location": p.location,
                "distance_m": p.distance_m,
            }
            for p in reply.nav_context.poi_list
        ],
        "selected_poi": (
            {
                "name": reply.nav_context.selected_poi.name,
                "address": reply.nav_context.selected_poi.address,
                "location": reply.nav_context.selected_poi.location,
            }
            if reply.nav_context.selected_poi
            else None
        ),
        "route_id": reply.nav_context.route_id,
        "should_recall": reply.should_recall,
        "recall_text": reply.recall_text,
        "handover_requested": reply.handover_requested,
        "handover_reason": reply.handover_reason,
        # 导航控制指令：手机端收到后调用 AmapLinkClient.execute(amap_execute_json)
        "nav_command": reply.nav_command.to_dict() if reply.nav_command else None,
    }

    return ChatResponse(
        text=reply.text,
        intent=intent,
        session_id=req.session_id,
        data=data,
    )
