"""分流层的核心契约：Handler(能力) / SlotSpec(槽位) / RouteContext / RouteResult。

每个能力自带 intent(唯一id) 与 description(自然语言)，还可以声明 slots（槽位）。
分类器把每个能力编译成一个 LLM function（description 即函数说明、slots 即参数
schema），一次 function calling 同时得到"选哪个能力 + 抽出哪些参数"——因此新增
一个能力(快递100/高德/其他 MCP) = 实现一个 Handler 并注册进 Dispatcher，分类器
无需改动即可识别它。这是"灵活增加"的关键。

槽位契约（对 Handler 作者）：
    - slots 是"顺带抽取"：分类器尽力而为，handler 拿到的 context.slots **可能是
      空 dict**（关键词兜底分类、模型没填参数）。handler 必须能只凭 query 工作，
      槽位缺失时用自己的确定性解析（正则等）兜底。
    - 类型只允许 "string" / "integer"（够用且映射到 JSON Schema 无歧义）；
      分类器负责把模型输出净化成声明的类型，handler 仍需做业务范围校验。

本层是顶层编排层：依赖各 provider 包（tripnow_client / kuaidi100_client /
amap_client）和 Gemini，但 provider 之间互不依赖。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .history import Turn


@dataclass(frozen=True)
class SlotSpec:
    """Handler 声明的一个槽位 = function calling 的一个参数。

    description 直接进 LLM 的参数 schema，写法同提示词：说清取值形态、给正反例。
    """

    name: str
    type: str  # "string" | "integer"
    description: str


@dataclass
class RouteContext:
    """一次分发的上下文（与具体能力无关的通用信息）。"""

    union_id: str | None = None  # TripNow 个人身份
    location: str | None = None  # "经度,纬度"，高德等基于位置的能力用
    include_data: bool = True
    history: list[Turn] = field(default_factory=list)  # 最近若干轮问答（最旧在前），供需要上下文的 handler 使用
    platform: str = "pc"  # 发起端类型："pc"（chat_app / client_py）或 "mobile"（client_flutter）。见 Handler.pc_only
    slots: dict[str, Any] = field(default_factory=dict)  # 分类时顺带抽出的槽位（见模块 docstring：可能为空，handler 须自行兜底）


@dataclass
class RouteResult:
    """统一的分发结果，屏蔽不同能力的返回差异。"""

    text: str
    data: Any | None = None  # 结构化数据（TripNow model_data / 快递轨迹 / 高德 POI）
    intent: str = ""  # 实际命中的能力


@dataclass(frozen=True)
class IntentSpec:
    """供分类器使用的意图描述（含可选的槽位声明）。"""

    id: str
    description: str
    slots: tuple[SlotSpec, ...] = ()


class Handler(ABC):
    """一种可被路由到的能力。"""

    intent: str = ""  # 唯一 id，如 "tripnow_public" / "express_tracking" / "amap_poi"
    description: str = ""  # 给分类器看的自然语言说明
    slots: tuple[SlotSpec, ...] = ()  # 希望分类器顺带抽取的槽位；空表示该能力无参数
    # PC-only：该能力的副作用发生在**服务端本机**（如控制本机 mpv 的暂停/切歌/音量），
    # 对"通过深链在自己设备上播放"的移动端毫无意义甚至误导。置 True 后，platform=="mobile"
    # 的请求既看不到它（不进 /health 能力清单），分类器也不会路由到它。默认 False（全端可见）。
    pc_only: bool = False

    def spec(self) -> IntentSpec:
        return IntentSpec(self.intent, self.description, self.slots)

    @abstractmethod
    def handle(self, query: str, context: RouteContext) -> RouteResult:
        raise NotImplementedError
