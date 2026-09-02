"""导航领域数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .state import Controller, NavState


@dataclass
class Poi:
    """一个 POI 地址。"""

    name: str
    address: str | None = None
    location: str | None = None       # "经度,纬度"
    distance_m: int | None = None
    rating: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class NavContext:
    """导航上下文：在控制权交接时保存，回退/重新进入时恢复。"""

    destination: str | None = None          # 目的地关键词
    poi_list: list[Poi] = field(default_factory=list)  # POI 候选列表
    selected_poi: Poi | None = None         # 用户选中的 POI
    direct_navigation: bool = False          # 是否直接导航（跳过选择）
    route_id: str | None = None              # 导航路线 ID
    is_in_navigation: bool = False           # 是否正在导航中


@dataclass
class IntentResult:
    """意图分类结果。"""

    intent: str                    # 意图 ID
    slots: dict[str, Any] = field(default_factory=dict)  # 槽位
    confidence: float = 1.0        # 置信度
    is_navigation_intent: bool = False  # 是否导航域意图
    is_non_navigation_intent: bool = False  # 是否高置信度非导航意图（用于云侧前置拦截）


@dataclass
class NavReply:
    """导航引擎对用户输入的回复。"""

    text: str                           # 回复文本（TTS 播报内容）
    controller: Controller              # 当前控制权
    nav_state: NavState                 # 当前导航状态
    nav_context: NavContext             # 导航上下文
    handover_requested: bool = False    # 是否请求交还控制权给主助手
    handover_reason: str | None = None  # 交还原因
    should_recall: bool = False          # 处理完非导航请求后是否主动召回导航
    recall_text: str | None = None       # 主动召回的话术
    nav_command: "NavCommand | None" = None  # 需要手机端执行的导航控制指令
    raw: dict[str, Any] = field(default_factory=dict)  # 原始数据（调试用）


@dataclass
class NavCommand:
    """导航控制指令：对应高德 AmapLinkClient 的 execute() 协议。

    手机端收到后，将 to_json() 的结果传给 AmapLinkClient.execute(jsonStr)，
    与高德地图 App 通过 IPC 通信，执行真正的导航控制。

    指令码（cmd）对应 AmapLinkClient 协议：
      1 = 切换路线      data: {"pathID": "123"}
      2 = 停止导航      data: {}
      3 = 添加途经点    data: {"lon","lat","name","poiid","entranceList"}
      4 = 设置/变更终点 data: {"lon","lat","name","poiid"}
      5 = 查询导航结构化信息 data: {}
      6 = 切换播报方式  data: {"mode": 2} 或 {"value": "1"}
      7 = 触发导航关键信息刷新 data: {}
    """

    cmd: int                    # 指令码
    request_id: int             # 请求 ID（用于回调关联）
    data: dict[str, Any]        # 指令参数
    description: str = ""       # 人类可读描述（调试/日志用）

    def to_json(self) -> str:
        """序列化为 AmapLinkClient.execute() 可直接传入的 JSON 字符串。"""
        import json
        return json.dumps({
            "cmd": self.cmd,
            "requestId": self.request_id,
            "data": self.data,
        }, ensure_ascii=False)

    def to_dict(self) -> dict[str, Any]:
        """转为字典（放入 ChatResponse.data 供手机端解析）。"""
        return {
            "cmd": self.cmd,
            "requestId": self.request_id,
            "data": self.data,
            "description": self.description,
            "amap_execute_json": self.to_json(),
        }
