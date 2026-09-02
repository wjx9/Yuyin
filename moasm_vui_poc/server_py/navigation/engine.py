"""导航对话引擎（核心）。

整合以下核心设计：
1. 导航状态机：IDLE → WAITING_DESTINATION → POI_SEARCHING →
   WAITING_POI_SELECTION → NAV_STARTING → NAVIGATING → COMPLETED
2. 对话控制权管理：PRIMARY / AMAP_AGENT
3. 云侧前置判断层：高置信度非导航意图直接拦截，不转发给 Agent
4. 主动召回机制：处理完非导航请求后，主动提示用户是否继续导航
5. 5 个边界场景处理

对应技术设计文档中的核心模块。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from .intent import (
    INTENT_CANCEL,
    INTENT_NAV_CONFIRM,
    INTENT_NAV_DIRECT,
    INTENT_NAV_NO_DEST,
    INTENT_NAV_REROUTE,
    INTENT_NAV_STOP,
    INTENT_NAV_WITH_DEST,
    INTENT_NON_NAV,
    INTENT_POI_SELECT,
    INTENT_UNKNOWN,
    NavigationIntentClassifier,
)
from .models import IntentResult, NavContext, NavReply, Poi
from .nav_service import NavigationService
from .poi_service import PoiSearchService
from .state import Controller, NavState

_log = logging.getLogger("navigation.engine")

# 非导航意图处理回调：接收用户原始输入，返回主助手的回复文本
# 真实产品中由主语音助手处理；POC 中可注入模拟实现
NonNavHandler = Callable[[str], str]


def _default_non_nav_handler(text: str) -> str:
    """默认非导航意图处理（POC 模拟）。"""
    return f"【主助手】已为你处理：{text}（这是主语音助手的回复，非高德Agent）"


class NavigationEngine:
    """导航对话引擎。"""

    def __init__(
        self,
        poi_service: PoiSearchService,
        nav_service: NavigationService | None = None,
        *,
        classifier: NavigationIntentClassifier | None = None,
        non_nav_handler: NonNavHandler | None = None,
        max_pois_display: int = 3,  # TTS 播报时最多展示的 POI 数量
    ):
        self._poi = poi_service
        self._nav = nav_service or NavigationService()
        self._classifier = classifier or NavigationIntentClassifier()
        self._non_nav_handler = non_nav_handler or _default_non_nav_handler
        self._max_pois_display = max_pois_display

        # 状态
        self._controller: Controller = Controller.PRIMARY
        self._nav_state: NavState = NavState.IDLE
        self._context: NavContext = NavContext()

    # ── 公共属性 ──────────────────────────────────────────────

    @property
    def controller(self) -> Controller:
        return self._controller

    @property
    def nav_state(self) -> NavState:
        return self._nav_state

    @property
    def nav_context(self) -> NavContext:
        return self._context

    @property
    def is_in_navigation(self) -> bool:
        return self._nav.is_in_navigation

    # ── 核心入口 ──────────────────────────────────────────────

    def handle(self, user_input: str) -> NavReply:
        """处理用户输入，返回回复。

        这是引擎的唯一入口，对应技术设计文档中的对话编排逻辑。
        """
        user_input = user_input.strip()
        if not user_input:
            return self._reply("请再说一遍好吗？")

        _log.info(
            "收到用户输入: %s | controller=%s | nav_state=%s | is_in_nav=%s",
            user_input, self._controller.value, self._nav_state.value, self._nav.is_in_navigation,
        )

        # 1. 意图分类（结合当前状态）
        intent = self._classifier.classify(
            user_input,
            nav_state=self._nav_state.value,
            is_in_navigation=self._nav.is_in_navigation,
        )

        _log.info("意图分类: intent=%s, confidence=%.2f, slots=%s",
                  intent.intent, intent.confidence, intent.slots)

        # 1.5 特殊状态处理：WAITING_DESTINATION 状态下，UNKNOWN输入当作目的地
        # （NON_NAV高置信度非导航意图不在这里处理，走正常的拦截逻辑）
        if (self._nav_state == NavState.WAITING_DESTINATION
                and intent.intent == INTENT_UNKNOWN):
            _log.info("WAITING_DESTINATION状态下，将用户输入当作目的地: %s", user_input)
            intent = IntentResult(
                intent=INTENT_NAV_WITH_DEST,
                slots={"destination": user_input},
                confidence=0.8,
                is_navigation_intent=True,
            )

        # 2. 云侧前置判断层：高置信度非导航意图拦截（场景5的核心保障）
        if intent.is_non_navigation_intent and self._controller == Controller.AMAP_AGENT:
            return self._handle_non_navigation_intercept(user_input, intent)

        # 3. 根据意图分发处理
        try:
            if intent.intent == INTENT_NAV_WITH_DEST:
                return self._handle_nav_with_dest(intent)
            if intent.intent == INTENT_NAV_NO_DEST:
                return self._handle_nav_no_dest()
            if intent.intent == INTENT_NAV_DIRECT:
                return self._handle_nav_direct(intent)
            if intent.intent == INTENT_POI_SELECT:
                return self._handle_poi_select(intent)
            if intent.intent == INTENT_NAV_CONFIRM:
                return self._handle_nav_confirm(intent)
            if intent.intent == INTENT_NAV_STOP:
                return self._handle_nav_stop()
            if intent.intent == INTENT_NAV_REROUTE:
                return self._handle_nav_reroute(intent)
            if intent.intent == INTENT_CANCEL:
                return self._handle_cancel()
            if intent.intent == INTENT_NON_NAV:
                # 控制权在PRIMARY时，非导航意图直接交给主助手
                if self._controller == Controller.PRIMARY:
                    return self._reply(self._non_nav_handler(user_input))
                # 控制权在AMAP_AGENT时，应该已经被前置判断拦截，这里是兜底
                return self._handle_non_navigation_intercept(user_input, intent)
            if intent.intent == INTENT_UNKNOWN:
                return self._handle_unknown(user_input)
        except Exception as e:
            _log.exception("处理用户输入时异常: %s", e)
            return self._reply(f"抱歉，处理你的请求时出了点问题：{e}")

        return self._reply("抱歉，我没理解你的意思。")

    # ── 场景1：导航意图（无目的地）────────────────────────────

    def _handle_nav_no_dest(self) -> NavReply:
        """场景1：用户说"开始导航"，没提供目的地。

        期望：识别到导航意图但缺少参数，反问"请问要去哪里？"
        """
        self._controller = Controller.AMAP_AGENT
        self._nav_state = NavState.WAITING_DESTINATION
        self._context = NavContext()  # 重置上下文

        return self._reply(
            "请问要去哪里？",
            controller=Controller.AMAP_AGENT,
            nav_state=NavState.WAITING_DESTINATION,
        )

    # ── 场景2/正常流程：导航意图（带目的地）───────────────────

    def _handle_nav_with_dest(self, intent: IntentResult) -> NavReply:
        """导航意图（带目的地）：搜索POI，根据结果数量处理。

        - 空列表 → 报错（场景3）
        - 唯一POI → 直接导航
        - 多个POI → 询问选择（正常流程）
        """
        destination = intent.slots.get("destination", "")
        if not destination:
            return self._handle_nav_no_dest()

        self._controller = Controller.AMAP_AGENT
        self._nav_state = NavState.POI_SEARCHING
        self._context = NavContext(destination=destination)

        # 搜索POI
        pois = self._poi.query_poi_list(destination)
        self._context.poi_list = pois

        if not pois:
            # 场景3：搜不到任何POI
            return self._handle_poi_not_found(destination)

        if len(pois) == 1:
            # 唯一POI，直接导航
            return self._start_navigation(pois[0], skip_confirmation=True)

        # 多个POI，询问选择
        self._nav_state = NavState.WAITING_POI_SELECTION
        display = pois[:self._max_pois_display]
        poi_text = "；".join(f"{i+1}. {p.name}" for i, p in enumerate(display))
        more_text = f"等{len(pois)}个结果" if len(pois) > self._max_pois_display else ""

        return self._reply(
            f"为你找到以下地址：{poi_text}{more_text}，请选择第几个？",
            controller=Controller.AMAP_AGENT,
            nav_state=NavState.WAITING_POI_SELECTION,
        )

    # ── 场景3：搜不到任何POI ──────────────────────────────────

    def _handle_poi_not_found(self, destination: str) -> NavReply:
        """场景3：搜不到任何POI，报错并收回控制权。"""
        self._nav_state = NavState.COMPLETED
        reply_text = f"找不到{destination}，无法为你导航。"

        # 收回控制权
        self._controller = Controller.PRIMARY
        self._context = NavContext()

        return self._reply(
            reply_text,
            controller=Controller.PRIMARY,
            nav_state=NavState.IDLE,
        )

    # ── 场景2：直接导航（跳过POI选择）─────────────────────────

    def _handle_nav_direct(self, intent: IntentResult) -> NavReply:
        """场景2：用户说"导航到大新，直接导航，不要废话"。

        期望：跳过POI选择，直接开始第一个POI的导航。
        """
        destination = intent.slots.get("destination", "")
        if not destination:
            return self._handle_nav_no_dest()

        self._controller = Controller.AMAP_AGENT
        self._nav_state = NavState.POI_SEARCHING
        self._context = NavContext(destination=destination, direct_navigation=True)

        # 搜索POI
        pois = self._poi.query_poi_list(destination)
        self._context.poi_list = pois

        if not pois:
            return self._handle_poi_not_found(destination)

        # 直接取第一个导航
        return self._start_navigation(pois[0], skip_confirmation=True)

    # ── 正常流程/场景4：POI选择 ───────────────────────────────

    def _handle_poi_select(self, intent: IntentResult) -> NavReply:
        """POI选择：用户说"第一个"/"第N个"。

        正常流程：用户选择后启动导航。
        """
        if self._nav_state != NavState.WAITING_POI_SELECTION or not self._context.poi_list:
            return self._reply("当前没有可选择的地址，请先告诉我要去哪里。")

        idx = intent.slots.get("poi_index", 0)
        pois = self._context.poi_list

        # 处理"最后一个"（idx=-1）
        if idx == -1:
            idx = len(pois) - 1

        if idx < 0 or idx >= len(pois):
            return self._reply(
                f"没有第{idx+1}个地址，请重新选择。共有{len(pois)}个地址。",
                controller=Controller.AMAP_AGENT,
                nav_state=NavState.WAITING_POI_SELECTION,
            )

        selected = pois[idx]
        return self._start_navigation(selected)

    # ── 场景4：列表后说"开始导航"（默认第一个）────────────────

    def _handle_nav_confirm(self, intent: IntentResult) -> NavReply:
        """场景4：出现POI列表后，用户说"开始导航"（没说第N个）。

        期望：直接按照第一个地址开始导航。
        由意图分类器在WAITING_POI_SELECTION状态下把"开始导航"转为poi_index=0。
        """
        # 复用POI选择逻辑（intent.slots里已经有poi_index=0）
        return self._handle_poi_select(intent)

    # ── 启动导航（公共方法）───────────────────────────────────

    def _start_navigation(self, poi: Poi, *, skip_confirmation: bool = False) -> NavReply:
        """启动导航：生成 AmapLinkClient cmd=4 指令，下发手机端执行真正导航。"""
        self._nav_state = NavState.NAV_STARTING
        self._context.selected_poi = poi

        result = self._nav.start_navigation(poi)

        if not result.success:
            self._nav_state = NavState.COMPLETED
            return self._reply(
                f"导航启动失败：{result.error or '未知错误'}",
                controller=Controller.AMAP_AGENT,
                nav_state=NavState.COMPLETED,
            )

        self._context.route_id = result.route_id
        self._context.is_in_navigation = True
        self._nav_state = NavState.NAVIGATING

        # 回复文本（TTS 播报）；真正的导航执行由手机端调用 AmapLinkClient 完成
        reply_text = f"好的，已为你导航到{poi.name}。"

        return self._reply(
            reply_text,
            controller=Controller.AMAP_AGENT,
            nav_state=NavState.NAVIGATING,
            nav_command=result.command,
        )

    # ── 结束导航 ──────────────────────────────────────────────

    def _handle_nav_stop(self) -> NavReply:
        """结束导航：生成 AmapLinkClient cmd=2 指令，下发手机端执行。"""
        if not self._nav.is_in_navigation:
            return self._reply("当前不在导航中。")

        poi_name = self._context.selected_poi.name if self._context.selected_poi else "当前路线"
        result = self._nav.stop_navigation()

        self._nav_state = NavState.IDLE
        self._controller = Controller.PRIMARY
        self._context = NavContext()

        return self._reply(
            f"好的，已结束到{poi_name}的导航。",
            controller=Controller.PRIMARY,
            nav_state=NavState.IDLE,
            nav_command=result.command if result.success else None,
        )

    # ── 重新导航 ──────────────────────────────────────────────

    def _handle_nav_reroute(self, intent: IntentResult) -> NavReply:
        """重新导航到新目的地。"""
        # 先停止当前导航
        if self._nav.is_in_navigation:
            self._nav.stop_navigation()

        destination = intent.slots.get("destination", "")
        if not destination:
            return self._handle_nav_no_dest()

        # 复用带目的地的导航逻辑
        return self._handle_nav_with_dest(IntentResult(
            intent=INTENT_NAV_WITH_DEST,
            slots={"destination": destination},
            confidence=0.9,
            is_navigation_intent=True,
        ))

    # ── 取消 ──────────────────────────────────────────────────

    def _handle_cancel(self) -> NavReply:
        """取消当前导航流程。"""
        was_navigating = self._nav.is_in_navigation
        stop_result = None
        if was_navigating:
            stop_result = self._nav.stop_navigation()

        self._nav_state = NavState.IDLE
        self._controller = Controller.PRIMARY
        self._context = NavContext()

        if was_navigating:
            return self._reply(
                "好的，已取消导航。",
                controller=Controller.PRIMARY,
                nav_state=NavState.IDLE,
                nav_command=stop_result.command if stop_result and stop_result.success else None,
            )
        return self._reply("好的，已取消。", controller=Controller.PRIMARY, nav_state=NavState.IDLE)

    # ── 场景5：非导航意图拦截（云侧前置判断层）─────────────────

    def _handle_non_navigation_intercept(self, user_input: str, intent: IntentResult) -> NavReply:
        """场景5：出现POI列表后（或导航中），用户说非导航意图（如"帮我看下我的闹钟"）。

        核心设计：云侧前置判断层拦截，不转发给Agent，直接由主助手处理。
        同时保存导航上下文，处理完后主动召回。
        """
        _log.info("云侧前置判断拦截非导航意图: %s (category=%s)",
                  user_input, intent.slots.get("category"))

        # 保存当前导航上下文（用于主动召回）
        saved_context = NavContext(
            destination=self._context.destination,
            poi_list=list(self._context.poi_list),
            selected_poi=self._context.selected_poi,
            is_in_navigation=self._context.is_in_navigation,
        )
        saved_state = self._nav_state

        # 交给主助手处理
        main_reply = self._non_nav_handler(user_input)

        # 收回控制权
        self._controller = Controller.PRIMARY

        # 判断是否需要主动召回
        should_recall = False
        recall_text = None
        if saved_state == NavState.WAITING_POI_SELECTION and saved_context.poi_list:
            # 等待POI选择时被打断，需要召回
            should_recall = True
            first_poi = saved_context.poi_list[0].name if saved_context.poi_list else ""
            recall_text = f"还需要继续导航到{saved_context.destination}吗？（第一个地址是{first_poi}）"
        elif saved_state == NavState.WAITING_DESTINATION:
            # 等待目的地时被打断
            should_recall = True
            recall_text = "还需要继续导航吗？请告诉我要去哪里。"
        elif saved_context.is_in_navigation:
            # 导航中被打断（导航仍在进行，不需要召回，控制权还在Agent）
            # 注意：导航中问非导航问题，导航继续进行，只是这一轮由主助手回答
            self._controller = Controller.AMAP_AGENT  # 导航中控制权保持在Agent
            should_recall = False

        # 构造回复：主助手回复 + 主动召回
        if should_recall and recall_text:
            reply_text = f"{main_reply}\n\n{recall_text}"
        else:
            reply_text = main_reply

        return NavReply(
            text=reply_text,
            controller=self._controller,
            nav_state=saved_state if saved_context.is_in_navigation else NavState.IDLE,
            nav_context=saved_context,
            handover_requested=True,
            handover_reason="non_navigation_intercept",
            should_recall=should_recall,
            recall_text=recall_text,
            raw={"original_input": user_input, "category": intent.slots.get("category")},
        )

    # ── 未知/模糊意图 ─────────────────────────────────────────

    def _handle_unknown(self, user_input: str) -> NavReply:
        """未知/模糊意图处理。

        所有非导航控制类的模糊输入都召回主语音助手，由其路由到对应技能
        （天气、闹钟、倒计时、麦当劳等）。导航控制指令（停止/重新导航）
        会被分类器正确识别，不会走到这里。
        """
        # 保存导航上下文用于召回
        saved_state = self._nav_state
        saved_context = NavContext(
            destination=self._context.destination,
            poi_list=list(self._context.poi_list),
            selected_poi=self._context.selected_poi,
            is_in_navigation=self._nav.is_in_navigation,
        )

        # 判断是否需要主动召回导航
        should_recall = False
        recall_text = None
        if saved_state == NavState.WAITING_POI_SELECTION and saved_context.poi_list:
            should_recall = True
            first_poi = saved_context.poi_list[0].name
            recall_text = f"还需要继续导航到{saved_context.destination}吗？（第一个地址是{first_poi}）"
        elif saved_state == NavState.WAITING_DESTINATION:
            should_recall = True
            recall_text = "还需要继续导航吗？请告诉我要去哪里。"

        # 构造主助手回复 + 召回提示
        main_reply = self._non_nav_handler(user_input)
        reply_text = f"{main_reply}\n\n{recall_text}" if should_recall and recall_text else main_reply

        return self._reply(
            reply_text,
            controller=Controller.PRIMARY,
            nav_state=saved_state if saved_context.is_in_navigation else NavState.IDLE,
            handover_requested=True,
            handover_reason="non_navigation_intercept",
            should_recall=should_recall,
            recall_text=recall_text,
        )

    # ── 工具方法 ──────────────────────────────────────────────

    def _reply(
        self,
        text: str,
        *,
        controller: Controller | None = None,
        nav_state: NavState | None = None,
        **kwargs: Any,
    ) -> NavReply:
        """构造回复。"""
        return NavReply(
            text=text,
            controller=controller or self._controller,
            nav_state=nav_state or self._nav_state,
            nav_context=NavContext(
                destination=self._context.destination,
                poi_list=list(self._context.poi_list),
                selected_poi=self._context.selected_poi,
                route_id=self._context.route_id,
                is_in_navigation=self._nav.is_in_navigation,
            ),
            **kwargs,
        )

    def reset(self) -> None:
        """重置引擎状态（用于测试或新会话）。"""
        if self._nav.is_in_navigation:
            self._nav.stop_navigation()
        self._controller = Controller.PRIMARY
        self._nav_state = NavState.IDLE
        self._context = NavContext()
