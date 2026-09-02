"""内置能力目录同步。

技能商店既可以独立运行（9000），也可以由主服务通过 8000 代理访问。
以前只有主服务启动时才会把内置 Handler 同步到商店，导致直接访问 9000
时只能看到 connectors/*.json 里的少数 MCP 技能。本模块提供一个不依赖
Dispatcher/Gemini 的轻量目录快照，保证两种启动方式看到同一组内置能力。

真正执行由统一的 MCP facade 负责：内置能力使用 local transport 转回原 Handler；
这里保存可被商店管理的 MCP-style manifest。能力依赖的 key 未配置时标记为 inactive，
避免商店展示无法执行的能力。
"""

from __future__ import annotations

import json
import os

from . import db


_META = {
    "chitchat": ("闲聊", "💬", "普通对话与问题回答"),
    "calendar_create": ("创建日历日程", "📅", "在手机日历中创建日程"),
    "alarm_create": ("闹钟", "⏰", "创建手机闹钟"),
    "timer_create": ("倒计时", "⏱", "创建手机倒计时"),
    "reminder_create": ("提醒", "🔔", "创建手机提醒"),
    "amap": ("附近地点搜索", "📍", "搜索附近的地点、商家和兴趣点"),
    "amap_geocode": ("地址转坐标", "🗺", "把地址转换为经纬度"),
    "amap_regeo": ("坐标转地址", "📌", "把经纬度转换为地址"),
    "amap_driving": ("驾车路线", "🚗", "查询驾车路线、距离和预计时间"),
    "amap_walking": ("步行路线", "🚶", "查询步行路线"),
    "amap_bicycling": ("骑行路线", "🚲", "查询骑行路线"),
    "amap_transit": ("公交路线", "🚌", "查询公交或地铁路线"),
    "amap_weather_live": ("实时天气", "🌤", "查询指定城市当前天气"),
    "amap_weather_forecast": ("天气预报", "☔", "查询指定城市未来天气"),
    "exa_search": ("联网搜索", "🔎", "搜索互联网中的最新信息"),
    "tencent_hot_news": ("热点新闻", "📰", "查询热点新闻"),
    "tencent_news_search": ("新闻搜索", "🗞", "按主题或地区搜索新闻"),
    "tripnow_public": ("公共出行查询", "🎫", "查询公开航班、火车等出行信息"),
    "tripnow_personal": ("个人出行查询", "🧳", "查询用户账号下的航班、火车等行程"),
    "express_tracking": ("快递查询", "📦", "查询快递物流轨迹"),
    "music_play": ("音乐播放", "🎵", "搜索并播放音乐"),
    "music_control": ("音乐控制（电脑端）", "🎚", "控制电脑端音乐播放"),
}

# 与 routing.factory 的可选 Handler 装配条件保持一致。
_REQUIRED_ENV = {
    "chitchat": ("GEMINI_API_KEY",),
    "amap": ("AMAP_KEY",),
    "amap_geocode": ("AMAP_KEY",),
    "amap_regeo": ("AMAP_KEY",),
    "amap_driving": ("AMAP_KEY",),
    "amap_walking": ("AMAP_KEY",),
    "amap_bicycling": ("AMAP_KEY",),
    "amap_transit": ("AMAP_KEY",),
    "amap_weather_live": ("AMAP_KEY",),
    "amap_weather_forecast": ("AMAP_KEY",),
    "exa_search": ("EXA_API_KEY",),
    "tencent_hot_news": ("TENCENT_NEWS_API_KEY",),
    "tencent_news_search": ("TENCENT_NEWS_API_KEY",),
    "tripnow_public": ("TRIPNOW_API_KEY",),
    "tripnow_personal": ("TRIPNOW_API_KEY",),
    "express_tracking": ("KUAIDI100_KEY", "KUAIDI100_CUSTOMER"),
    "music_play": ("MUSIC163_APPID", "MUSIC163_PRIVATE_KEY"),
    "music_control": ("MUSIC163_APPID", "MUSIC163_PRIVATE_KEY"),
}


def _available(intent: str) -> bool:
    return all(os.getenv(key, "").strip() for key in _REQUIRED_ENV.get(intent, ()))


def build_manifests() -> list[dict]:
    """构造当前环境中实际可装配的内置能力 manifest。"""
    manifests = []
    for intent, (name, icon, description) in _META.items():
        if not _available(intent):
            continue
        manifests.append(
            {
                "kind": "builtin",
                "skill_id": f"builtin:{intent}",
                "name": name,
                "icon": icon,
                "description": description,
                "intent": intent,
                "entry_tool": intent,
                "query_slot": None,
                "mcp_server": {"transport": "local", "url": f"handler://{intent}"},
                "always_enabled": True,
                "credentials": {"type": "none"},
                "tools": [],
                "pc_only": intent == "music_control",
            }
        )
    return manifests


def sync_catalog() -> dict:
    """把内置能力写入 skills 表，并将当前不可用的内置能力标为 inactive。"""
    manifests = build_manifests()
    active_ids = {m["skill_id"] for m in manifests}
    synced = []
    with db.connect() as conn:
        for manifest in manifests:
            raw = json.dumps(manifest, ensure_ascii=False)
            conn.execute(
                """INSERT INTO skills
                   (skill_id,name,description,icon,intent,manifest,publisher,status,updated_at)
                   VALUES (?,?,?,?,?,?,?,'active',datetime('now'))
                   ON CONFLICT(skill_id) DO UPDATE SET
                     name=excluded.name, description=excluded.description, icon=excluded.icon,
                     intent=excluded.intent, manifest=excluded.manifest,
                     publisher='builtin', updated_at=datetime('now')""",
                (manifest["skill_id"], manifest["name"], manifest["description"],
                 manifest["icon"], manifest["intent"], raw, "builtin"),
            )
            synced.append(manifest["skill_id"])

        # 不删除历史目录记录，避免用户选购关系断裂；只隐藏当前不可用的内置能力。
        rows = conn.execute(
            "SELECT skill_id FROM skills WHERE publisher='builtin'"
        ).fetchall()
        for row in rows:
            if row["skill_id"] not in active_ids:
                conn.execute(
                    "UPDATE skills SET status='inactive', updated_at=datetime('now') WHERE skill_id=?",
                    (row["skill_id"],),
                )
    return {"synced": synced, "count": len(synced)}
