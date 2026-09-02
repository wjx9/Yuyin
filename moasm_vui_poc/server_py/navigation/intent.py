"""导航意图分类器（规则引擎 + 云侧前置判断层）。

核心设计：
1. 导航域意图识别：导航意图、POI选择、导航控制等
2. 高置信度非导航意图判断：用于云侧前置拦截（场景5的关键保障）
3. 模糊意图：无法明确判断时，转发给 Agent 处理

规则引擎采用关键词匹配 + 正则表达式，零依赖，可独立运行。
大模型NLU作为可选增强，在规则引擎低置信度时调用。
"""

from __future__ import annotations

import re
from typing import Any

from .models import IntentResult


# ── 意图 ID 常量 ──────────────────────────────────────────────

INTENT_NAV_WITH_DEST = "nav_with_destination"       # 导航意图（带目的地）
INTENT_NAV_NO_DEST = "nav_no_destination"           # 导航意图（无目的地）
INTENT_NAV_DIRECT = "nav_direct_navigation"         # 直接导航（跳过POI选择）
INTENT_POI_SELECT = "poi_select"                     # POI选择（第N个）
INTENT_NAV_CONFIRM = "nav_confirm"                   # 导航确认（"开始导航"/"走吧"，在WAITING_POI_SELECTION状态下）
INTENT_NAV_STOP = "nav_stop"                         # 结束导航
INTENT_NAV_REROUTE = "nav_reroute"                   # 重新导航
INTENT_CANCEL = "cancel"                              # 取消
INTENT_NON_NAV = "non_navigation"                     # 非导航意图（高置信度，用于前置拦截）
INTENT_UNKNOWN = "unknown"                            # 未知/模糊意图


# ── 中文数字映射 ──────────────────────────────────────────────

_CN_NUM = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}


def _parse_index(text: str) -> int | None:
    """从文本中解析序号（第N个 / 第N / N个）。返回0-based索引，解析失败返回None。"""
    # 第N个 / 第N
    m = re.search(r"第([一二两三四五六七八九十\d]+)(?:个|家|条|站)?", text)
    if m:
        raw = m.group(1)
        if raw.isdigit():
            idx = int(raw)
        else:
            idx = _CN_NUM.get(raw)
        if idx is not None and idx >= 1:
            return idx - 1  # 转0-based

    # N个 / N家（无"第"字，如"一个""两个"）
    m = re.search(r"([一二两三四五六七八九十\d]+)(?:个|家|条|站)", text)
    if m:
        raw = m.group(1)
        if raw.isdigit():
            idx = int(raw)
        else:
            idx = _CN_NUM.get(raw)
        if idx is not None and idx >= 1:
            return idx - 1

    # "第一个" / "最后一个"
    if re.search(r"第一(?:个|家|条)", text):
        return 0
    if re.search(r"最后(?:一个|一家|一条)", text):
        return -1  # 特殊标记：最后一个，由调用方处理

    return None


def _extract_destination(text: str) -> str | None:
    """从导航指令中提取目的地。

    匹配模式：导航到X / 导航去X / 去X / 带我去X / 帮我导航到X / 导航X
    提取后清理尾部的标点、语气词和直接导航关键词（别问/直接/不要废话等）。
    """
    # 直接导航关键词，作为目的地提取的终止符
    direct_stop = r"(?:直接|别问|不要废话|别废话|不用选|不用问|赶紧|就走|出发)"
    patterns = [
        rf"(?:帮我|请|给我)?(?:开始)?导航(?:到|去|往|至)(.+?)(?:[，。！？、\s]|{direct_stop}|吧|啊|呀|呢|$)",
        rf"(?:帮我|请|给我)?(?:开始)?导航(.+?)(?:[，。！？、\s]|{direct_stop}|吧|啊|呀|呢|$)",
        rf"(?:带我|陪我|和我)?去(.+?)(?:[，。！？、\s]|{direct_stop}|吧|啊|呀|呢|$)",
        rf"往(.+?)(?:[，。！？、\s]|{direct_stop}|吧|啊|呀|呢|$)",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            dest = m.group(1).strip()
            # 清理尾部语气词和标点
            dest = re.sub(r"(?:吧|啊|呀|呢|哦|哈|啦|嘛)+$", "", dest).strip()
            dest = dest.strip("，。！？、；：")
            if dest and len(dest) <= 50:  # 合理长度限制
                return dest
    return None


# ── 高置信度非导航意图关键词（云侧前置拦截用）──────────────────
# 这些关键词出现时，高置信度判断为非导航意图，不转发给 Agent

_NON_NAV_KEYWORDS: dict[str, tuple[str, ...]] = {
    "alarm": ("闹钟", "闹铃", "提醒我", "定时", "叫我起床"),
    "weather": ("天气", "气温", "下雨", "下雪", "温度", "湿度", "风力", "风向"),
    "joke": ("讲个笑话", "说个笑话", "讲笑话", "说笑话", "逗我笑", "好笑的"),
    "music": ("放首歌", "播放音乐", "听歌", "唱首歌", "来点音乐", "放音乐"),
    "phone": ("打电话", "拨打电话", "呼叫", "给某人打电话", "接通"),
    "message": ("发消息", "发短信", "发条微信", "发个短信", "通知"),
    "calendar": ("日程", "日历", "会议", "安排", "今天有什么事", "待办"),
    "calculator": ("计算", "等于多少", "加减乘除", "算一下"),
    "translation": ("翻译", "翻译成", "用英语说", "怎么说"),
    "knowledge": ("为什么", "是什么", "怎么回事", "科普一下", "告诉我"),
    "chat": ("你好", "在吗", "聊聊", "说说话", "聊天", "你是谁"),
    "setting": ("设置", "音量", "亮度", "蓝牙", "wifi", "网络"),
    "app": ("打开", "启动", "运行", "退出", "关闭"),
}


def _check_non_navigation(text: str) -> tuple[bool, str | None]:
    """检查是否为高置信度非导航意图。

    返回 (is_non_nav, category)。
    注意：如果同时包含导航关键词和非导航关键词，以导航为准（用户可能说"导航到天气大厦"）。
    """
    # 先检查是否包含导航强信号，如果有则不算非导航
    nav_signals = ("导航", "路线", "怎么走", "去哪个", "带我去", "怎么走")
    has_nav = any(s in text for s in nav_signals)
    if has_nav:
        return False, None

    for category, keywords in _NON_NAV_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                return True, category
    return False, None


# ── 主分类器 ──────────────────────────────────────────────────

class NavigationIntentClassifier:
    """导航意图分类器（规则引擎）。

    输入用户文本 + 当前导航状态，输出意图分类结果。
    状态相关的意图（如POI选择、导航确认）需要结合当前状态判断。
    """

    def classify(self, text: str, *, nav_state: str = "idle",
                 is_in_navigation: bool = False) -> IntentResult:
        """分类用户输入。

        Args:
            text: 用户输入文本
            nav_state: 当前导航状态（NavState的值）
            is_in_navigation: 是否正在导航中
        """
        text = text.strip()
        if not text:
            return IntentResult(intent=INTENT_UNKNOWN, confidence=0.0)

        # 1. 取消意图（最高优先级，任何状态下）
        if self._is_cancel(text):
            return IntentResult(
                intent=INTENT_CANCEL, confidence=0.95,
                is_navigation_intent=True,
            )

        # 2. 结束导航（导航中）
        if is_in_navigation and self._is_stop_navigation(text):
            return IntentResult(
                intent=INTENT_NAV_STOP, confidence=0.95,
                is_navigation_intent=True,
            )

        # 3. 重新导航（导航中）
        if is_in_navigation:
            dest = self._extract_reroute_destination(text)
            if dest:
                return IntentResult(
                    intent=INTENT_NAV_REROUTE, confidence=0.9,
                    slots={"destination": dest},
                    is_navigation_intent=True,
                )

        # 4. POI选择（在WAITING_POI_SELECTION状态下）
        if nav_state == "waiting_poi_selection":
            idx = _parse_index(text)
            if idx is not None:
                return IntentResult(
                    intent=INTENT_POI_SELECT, confidence=0.95,
                    slots={"poi_index": idx},
                    is_navigation_intent=True,
                )
            # 导航确认（"开始导航"/"走吧"/"出发"）→ 默认选第一个
            if self._is_nav_confirm(text):
                return IntentResult(
                    intent=INTENT_NAV_CONFIRM, confidence=0.9,
                    slots={"poi_index": 0},  # 默认第一个
                    is_navigation_intent=True,
                )

        # 5. 直接导航（带目的地 + "直接"/"不要废话"等）
        dest = _extract_destination(text)
        if dest and self._is_direct_navigation(text):
            return IntentResult(
                intent=INTENT_NAV_DIRECT, confidence=0.9,
                slots={"destination": dest, "direct_navigation": True},
                is_navigation_intent=True,
            )

        # 6. 导航意图（带目的地）
        if dest:
            return IntentResult(
                intent=INTENT_NAV_WITH_DEST, confidence=0.85,
                slots={"destination": dest},
                is_navigation_intent=True,
            )

        # 7. 导航意图（无目的地）
        if self._is_nav_no_destination(text):
            return IntentResult(
                intent=INTENT_NAV_NO_DEST, confidence=0.9,
                is_navigation_intent=True,
            )

        # 8. 高置信度非导航意图（云侧前置拦截用）
        is_non_nav, category = _check_non_navigation(text)
        if is_non_nav:
            return IntentResult(
                intent=INTENT_NON_NAV, confidence=0.9,
                slots={"category": category},
                is_non_navigation_intent=True,
            )

        # 9. 未知/模糊意图
        return IntentResult(intent=INTENT_UNKNOWN, confidence=0.3)

    # ── 内部判断方法 ──────────────────────────────────────────

    @staticmethod
    def _is_cancel(text: str) -> bool:
        return bool(re.search(r"(?:取消|算了|不用了|别弄了|不要了|停止|退出)", text))

    @staticmethod
    def _is_stop_navigation(text: str) -> bool:
        return bool(re.search(
            r"(?:结束导航|停止导航|别导航了|终止导航|退出导航|导航结束)", text))

    @staticmethod
    def _is_nav_confirm(text: str) -> bool:
        """导航确认：在WAITING_POI_SELECTION状态下，"开始导航"/"走吧"/"出发"等。"""
        return bool(re.search(
            r"(?:开始导航|走吧|出发|就这个|就它了|确定|好的走|赶紧走|快走)", text))

    @staticmethod
    def _is_direct_navigation(text: str) -> bool:
        """直接导航：包含"直接"/"不要废话"/"不用选"/"别问"等。"""
        return bool(re.search(
            r"(?:直接导航|直接走|直接出发|不要废话|别废话|不用选|别问我|别问|直接开始|不用问|赶紧导航|别问了)", text))

    @staticmethod
    def _is_nav_no_destination(text: str) -> bool:
        """导航意图但无目的地：只说"开始导航"/"导航吧"等。"""
        # 必须包含导航关键词，但没有提取到目的地
        has_nav_kw = bool(re.search(r"(?:开始导航|导航吧|来导航|启动导航|打开导航)", text))
        # 排除"导航到X"等已提取目的地的情况（由_extract_destination处理）
        return has_nav_kw

    @staticmethod
    def _extract_reroute_destination(text: str) -> str | None:
        """重新导航到X：从"重新导航到X"/"换个路线去X"/"导航改到X"中提取目的地。"""
        m = re.search(
            r"(?:重新|换个|改|换)(?:导航|路线|目的地)?(?:到|去|往|至)(.+?)(?:[，。！？、\s]|吧|啊|呀|呢|$)",
            text)
        if m:
            dest = m.group(1).strip()
            dest = re.sub(r"(?:吧|啊|呀|呢|哦|哈|啦|嘛)+$", "", dest).strip()
            if dest:
                return dest
        return None
