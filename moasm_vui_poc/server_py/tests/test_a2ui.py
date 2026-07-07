"""A2UI 呈现层单测：文本解析、卡片结构、意图注册表、服务端下发开关。

新闻/天气样本取自真实 tencent-news-cli 输出（截断），保证解析器对线上格式有效。
"""

from __future__ import annotations

from a2ui import build_a2ui
from a2ui.cards import _parse_news

_NEWS_TEXT = """【腾讯新闻 - 搜索「美国」】 2026-07-04 15:36

1. 标题：美国曝出惊天虐童案：16个孩子挤在十余平米小房间
   摘要: 7月1日，美国俄亥俄州警方称……
   来源: 封面新闻
   发布时间: 2026-07-04 07:25:09
   链接: https://view.inews.qq.com/a/20260704A0248300?scene=news-skill

2. 标题：纽约街头现新婚标语牌
   摘要: 据美国有线电视新闻网（CNN）报道……
   来源: 环球网
   发布时间: 2026-07-04 10:26:10
   链接: https://view.inews.qq.com/a/20260704A03F4300?scene=news-skill

共 2 条搜索结果，还有更多结果"""

_WEATHER_TEXT = """【腾讯新闻 - 天气查询】 2026-07-04 15:36

🌤 当前实况
   天气：雨
   温度：25°C
   湿度：90%
   风向：东南风 3-4级
   降水：0.1mm

📅 未来天气
   2026-07-03  25/32°C  中雨  东南风  空气:优
   2026-07-04  26/29°C  中雨  东南风  空气:优"""


def _components_of(messages: list[dict]) -> dict[str, dict]:
    """updateComponents 里的组件按 id 索引。"""
    comps = messages[1]["updateComponents"]["components"]
    return {comp["id"]: comp for comp in comps}


def _surface_id(messages: list[dict]) -> str:
    return messages[0]["createSurface"]["surfaceId"]


# ---------- 消息骨架 ----------

def test_build_returns_create_then_update_with_same_surface():
    msgs = build_a2ui("tencent_news_search", _NEWS_TEXT)
    assert msgs is not None and len(msgs) == 2
    assert msgs[0]["version"] == "v0.9" and msgs[1]["version"] == "v0.9"
    create = msgs[0]["createSurface"]
    assert create["catalogId"].endswith("basic_catalog.json")
    assert msgs[1]["updateComponents"]["surfaceId"] == create["surfaceId"]


def test_root_is_card_wrapping_column():
    comps = _components_of(build_a2ui("tencent_news_search", _NEWS_TEXT))
    assert comps["root"]["component"] == "Card"  # 穿戴设备约定：Card 必须是根
    col_id = comps["root"]["child"]
    assert comps[col_id]["component"] == "Column"


def test_unknown_intent_returns_none():
    assert build_a2ui("chitchat", "随便聊聊") is None
    assert build_a2ui("music_play", "正在播放") is None


def test_empty_text_returns_none():
    assert build_a2ui("tencent_news_search", "   ") is None


# ---------- 新闻解析与成卡 ----------

def test_parse_news_extracts_items():
    title, items = _parse_news(_NEWS_TEXT)
    assert title == "搜索「美国」"
    assert [i["title"] for i in items] == [
        "美国曝出惊天虐童案：16个孩子挤在十余平米小房间",
        "纽约街头现新婚标语牌",
    ]
    assert items[0]["source"] == "封面新闻"
    assert items[0]["time"] == "07-04 07:25"  # 年和秒被压缩掉


def test_news_card_has_title_items_and_captions():
    comps = _components_of(build_a2ui("tencent_news_search", _NEWS_TEXT))
    assert comps["title"]["variant"] == "h4"
    assert comps["title"]["text"] == "搜索「美国」"
    assert comps["item0"]["text"].startswith("美国曝出")
    assert comps["meta0"] == {
        "id": "meta0", "component": "Text",
        "text": "封面新闻 · 07-04 07:25", "variant": "caption",
    }
    # Column children 顺序：标题、分隔线、条目与其 meta 交替
    col = comps[comps["root"]["child"]]
    assert col["children"][:4] == ["title", "sep", "item0", "meta0"]


def test_news_unparseable_falls_back_to_generic_card():
    comps = _components_of(build_a2ui("tencent_hot_news", "CLI 改版了，格式面目全非"))
    assert comps["root"]["component"] == "Card"
    assert comps["body"]["text"] == "CLI 改版了，格式面目全非"


# ---------- 天气成卡 ----------

def test_weather_card_summary_and_forecast():
    comps = _components_of(build_a2ui("tencent_weather", _WEATHER_TEXT))
    assert comps["now"]["text"] == "雨  25°C  东南风 3-4级"
    assert "湿度90%" in comps["nowExtra"]["text"]
    assert comps["day0"]["text"] == "07-03  25/32°C 中雨 东南风 空气:优"
    assert comps["day0"]["variant"] == "caption"


# ---------- 行程整文卡 ----------

def test_tripnow_uses_generic_markdown_card():
    comps = _components_of(build_a2ui("tripnow_public", "G1234 次列车 **有票**"))
    assert comps["title"]["text"] == "出行 · TripNow"
    assert comps["body"]["text"] == "G1234 次列车 **有票**"
