"""导航状态机定义。

包含两层状态：
1. Controller（控制权状态）：PRIMARY / AMAP_AGENT
2. NavState（导航对话状态）：IDLE / WAITING_DESTINATION / POI_SEARCHING /
   WAITING_POI_SELECTION / NAV_STARTING / NAVIGATING / COMPLETED
"""

from __future__ import annotations

from enum import Enum


class Controller(str, Enum):
    """对话控制权持有方。"""

    PRIMARY = "primary"          # 主语音助手
    AMAP_AGENT = "amap_agent"   # 高德导航 Agent


class NavState(str, Enum):
    """导航对话状态（端侧维护，云侧感知）。"""

    IDLE = "idle"                              # 空闲，无导航流程
    WAITING_DESTINATION = "waiting_destination"  # 等待用户提供目的地
    POI_SEARCHING = "poi_searching"            # 正在搜索 POI 列表
    WAITING_POI_SELECTION = "waiting_poi_selection"  # 等待用户选择 POI
    NAV_STARTING = "nav_starting"              # 正在启动导航
    NAVIGATING = "navigating"                  # 导航进行中
    COMPLETED = "completed"                    # 导航流程结束（成功或失败）


class NavEvent(str, Enum):
    """导航状态变更事件。"""

    NAV_STARTED = "navigation_started"    # 导航已启动
    NAV_ENDED = "navigation_ended"        # 导航已结束
    NAV_REROUTED = "navigation_rerouted"  # 导航重新规划
