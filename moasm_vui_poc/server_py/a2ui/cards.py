"""按意图把技能结果转成 A2UI 卡片。

数据来源说明：
    腾讯新闻 CLI 输出的是排版好的纯文本（无 JSON 模式），所以这里用正则把
    文本解析回条目再组卡；解析不出（CLI 改版/异常输出）时回退"整文卡"——
    Text 组件支持 Markdown，整文也能看，只是没有结构化排版。
    TripNow 的 content 本身是模型生成的 Markdown，直接整文入卡。

卡片形态约定（穿戴设备）：
    根组件必须是 id="root" 的 Card；内容紧凑——标题行 + 分隔线 + 条目，
    条目正文用 body、辅助信息（来源/时间）用 caption（客户端渲染为灰度）。
"""

from __future__ import annotations

import re
import uuid

from . import components as c

# ---------- 腾讯新闻文本解析 ----------

_NEWS_HEADER_RE = re.compile(r"【腾讯新闻\s*-\s*(.+?)】")
_NEWS_ITEM_RE = re.compile(r"^\s*\d+\.\s*标题[:：]\s*(.+?)\s*$")
_NEWS_FIELD_RE = re.compile(r"^\s*(摘要|来源|发布时间|链接)[:：]?\s*(.+?)\s*$")
# "2026-07-04 07:25:09" → "07-04 07:25"（卡片空间有限，去掉年和秒）
_TIME_COMPACT_RE = re.compile(r"^\d{4}-(\d{2}-\d{2}) (\d{2}:\d{2})(?::\d{2})?$")


def _parse_news(text: str) -> tuple[str | None, list[dict]]:
    """从 CLI 文本抠出（榜单标题, [{title, source, time}...]）。"""
    header = _NEWS_HEADER_RE.search(text)
    items: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        m = _NEWS_ITEM_RE.match(line)
        if m:
            current = {"title": m.group(1)}
            items.append(current)
            continue
        if current is None:
            continue
        f = _NEWS_FIELD_RE.match(line)
        if not f:
            continue
        key, value = f.group(1), f.group(2)
        if key == "来源":
            current["source"] = value
        elif key == "发布时间":
            t = _TIME_COMPACT_RE.match(value)
            current["time"] = f"{t.group(1)} {t.group(2)}" if t else value
    return (header.group(1) if header else None, items)


def _news_card(intent: str, text: str) -> list[dict]:
    title, items = _parse_news(text)
    if not items:
        return _generic_card("腾讯新闻", text)
    comps: list[dict] = []
    children: list[str] = ["title", "sep"]
    comps.append(c.text("title", title or "腾讯新闻", variant="h4"))
    comps.append(c.divider("sep"))
    for i, item in enumerate(items):
        tid = f"item{i}"
        comps.append(c.text(tid, item["title"]))
        children.append(tid)
        meta = " · ".join(v for v in (item.get("source"), item.get("time")) if v)
        if meta:
            mid = f"meta{i}"
            comps.append(c.text(mid, meta, variant="caption"))
            children.append(mid)
    return _wrap_card(comps, children)


# ---------- 腾讯天气文本解析 ----------

_WEATHER_NOW_RE = re.compile(r"^\s*(天气|温度|湿度|风向|降水)[:：]\s*(.+?)\s*$")
_WEATHER_DAY_RE = re.compile(r"^\s*(\d{4})-(\d{2}-\d{2})\s+(.+?)\s*$")
_MAX_FORECAST_DAYS = 5


def _weather_card(intent: str, text: str) -> list[dict]:
    now: dict[str, str] = {}
    days: list[str] = []
    for line in text.splitlines():
        m = _WEATHER_NOW_RE.match(line)
        if m:
            now.setdefault(m.group(1), m.group(2))
            continue
        d = _WEATHER_DAY_RE.match(line)
        if d and len(days) < _MAX_FORECAST_DAYS:
            days.append(f"{d.group(2)}  {re.sub(r'\s+', ' ', d.group(3))}")
    if not now and not days:
        return _generic_card("天气", text)

    comps: list[dict] = [c.text("title", "天气", variant="h4"), c.divider("sep")]
    children = ["title", "sep"]
    if now:
        summary = "  ".join(
            v for v in (now.get("天气"), now.get("温度"), now.get("风向")) if v
        )
        extra = "  ".join(
            f"{k}{v}" for k, v in (("湿度", now.get("湿度")), ("降水", now.get("降水"))) if v
        )
        comps.append(c.text("now", summary or "当前实况"))
        children.append("now")
        if extra:
            comps.append(c.text("nowExtra", extra, variant="caption"))
            children.append("nowExtra")
    for i, day in enumerate(days):
        did = f"day{i}"
        comps.append(c.text(did, day, variant="caption"))
        children.append(did)
    return _wrap_card(comps, children)


# ---------- 整文卡（Markdown）与包装 ----------

def _generic_card(title: str, body: str) -> list[dict]:
    comps = [
        c.text("title", title, variant="h4"),
        c.divider("sep"),
        c.text("body", body),  # Text 支持 Markdown，整文直接入卡
    ]
    return _wrap_card(comps, ["title", "sep", "body"])


def _wrap_card(comps: list[dict], children: list[str]) -> list[dict]:
    """套上 Card 根（id 必须 "root"）+ Column 骨架。"""
    return [
        c.card("root", "col"),
        c.column("col", children),
        *comps,
    ]


# ---------- 意图 → builder 注册表 ----------

_BUILDERS = {
    "tencent_news_search": _news_card,
    "tencent_hot_news": _news_card,
    "tencent_weather": _weather_card,
    "tripnow_public": lambda intent, text: _generic_card("出行 · TripNow", text),
    "tripnow_personal": lambda intent, text: _generic_card("我的行程 · TripNow", text),
}


def build_a2ui(intent: str, text: str) -> list[dict] | None:
    """把一轮结果转成 A2UI 消息列表；该意图无卡片形态时返回 None（纯文本气泡）。"""
    builder = _BUILDERS.get(intent)
    if builder is None or not text.strip():
        return None
    surface_id = f"srf-{uuid.uuid4().hex[:12]}"
    comps = builder(intent, text)
    return [c.create_surface(surface_id), c.update_components(surface_id, comps)]
