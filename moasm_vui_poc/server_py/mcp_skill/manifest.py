"""SkillManifest 模型 + manifest→IntentSpec(SlotSpec) 映射。

约束（见 最终技术路线.md §2.2）：
- `required` 是 JSON Schema 顶层数组（["city"]），不是属性级布尔；
- 现有 `SlotSpec.type` 只支持 string/integer：integer→integer，其余（number/
  boolean/array/object）一律映射 string，description 里写清取值。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from routing.handler import SlotSpec

# 现有 _clean_slots 只认这两种类型；number 映射 string（浮点转 int 丢精度）
_TYPE_MAP = {"integer": "integer"}


@dataclass
class SkillManifest:
    """商店返回的完整 manifest（P1 来自本地 JSON，P2 来自商店 sync）。"""

    skill_id: str
    name: str
    description: str
    intent: str  # 复用现有 intents 机制；必须与内置意图不冲突（见 §2.2）
    # 远程 MCP 技能必填；内置技能只作为目录记录，不需要这两个字段。
    entry_tool: str = ""  # 主工具；MCPHandler.handle() 调它
    mcp_server: dict = field(default_factory=dict)  # {transport, url, ...}
    tools: list[dict] = field(default_factory=list)  # JSON Schema 工具描述
    icon: str = ""  # 商店 web 页卡片用；对 MCPHandler 无意义
    pc_only: bool = False  # 同 Handler.pc_only
    query_slot: str | None = None  # §2.3：槽位缺失时整句 query 喂给哪个槽
    credentials: dict = field(default_factory=dict)  # §10：platform/byok/none
    keywords: list[str] = field(default_factory=list)  # decide 层确定性收窄用：命中即锁定本技能（修复内置抢跑）
    replaces: list[str] = field(default_factory=list)  # 顶替内置意图：装配时从该用户 plannable 集剔除（管理员可配）
    kind: str = "mcp"  # builtin 仅用于商店目录展示，执行仍走现有 Handler
    always_enabled: bool = False

    @classmethod
    def from_dict(cls, d: dict) -> "SkillManifest":
        # 只取已知字段：商店 sync 数据源不可信（管理员手输 manifest 有拼写/多余字段），
        # 用 cls(**d) 会因未知键抛 TypeError，让一个 typo 搞挂整张聊天图。见 P2 §5.2 校验。
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


def to_slot_specs(tools) -> tuple[SlotSpec, ...]:
    """tools 的 JSON Schema → SlotSpec 列表。required 读顶层数组。"""
    slots: list[SlotSpec] = []
    for t in tools:
        schema = t["input_schema"]
        required = set(schema.get("required", []))
        for name, prop in schema.get("properties", {}).items():
            slots.append(
                SlotSpec(
                    name=name,
                    type=_TYPE_MAP.get(prop.get("type"), "string"),
                    description=prop.get("description", ""),
                    required=name in required,
                )
            )
    return tuple(slots)
