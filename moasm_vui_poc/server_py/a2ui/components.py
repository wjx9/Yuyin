"""A2UI v0.9 消息与组件的构造函数。

只封装本项目用到的最小词汇表（Card/Column/Text/Divider），字段名与
genui 0.9.x 的 basic catalog schema 严格一致（客户端会做 schema 校验，
多字段/错枚举会导致整卡不渲染）：
    Text:    {text: str, variant?: h1..h5|caption|body}
    Column:  {children: [id...], justify?, align?}
    Card:    {child: id}
    Divider: {axis?: horizontal|vertical}
根组件 id 约定为 "root"（genui 从 "root" 开始渲染，没有它整面不显示）。
"""

from __future__ import annotations

# genui BasicCatalogItems 的 catalogId（basic_catalog 常量，双方必须一致）。
BASIC_CATALOG_ID = "https://a2ui.org/specification/v0_9/basic_catalog.json"

_VERSION = "v0.9"


def create_surface(surface_id: str) -> dict:
    return {
        "version": _VERSION,
        "createSurface": {"surfaceId": surface_id, "catalogId": BASIC_CATALOG_ID},
    }


def update_components(surface_id: str, components: list[dict]) -> dict:
    return {
        "version": _VERSION,
        "updateComponents": {"surfaceId": surface_id, "components": components},
    }


def text(cid: str, content: str, variant: str | None = None) -> dict:
    comp = {"id": cid, "component": "Text", "text": content}
    if variant:
        comp["variant"] = variant
    return comp


def column(cid: str, children: list[str]) -> dict:
    return {"id": cid, "component": "Column", "children": children}


def card(cid: str, child: str) -> dict:
    return {"id": cid, "component": "Card", "child": child}


def divider(cid: str) -> dict:
    return {"id": cid, "component": "Divider"}
