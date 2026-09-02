"""把现有内置 Handler 转成技能商店可展示的 manifest。

内置能力仍由原来的 Handler 执行，不会被改写成 MCP；manifest 只用于商店目录展示，
这样商店可以同时管理/展示内置能力和外部 MCP 技能。
"""

from __future__ import annotations


_NAMES = {
    "chitchat": ("闲聊", "💬"),
    "calendar_create": ("创建日历日程", "📅"),
    "alarm_create": ("闹钟", "⏰"),
    "timer_create": ("倒计时", "⏱"),
    "reminder_create": ("提醒", "🔔"),
    "amap": ("附近地点搜索", "📍"),
    "amap_geocode": ("地址转坐标", "🗺"),
    "amap_regeo": ("坐标转地址", "📌"),
    "amap_driving": ("驾车路线", "🚗"),
    "amap_walking": ("步行路线", "🚶"),
    "amap_bicycling": ("骑行路线", "🚲"),
    "amap_transit": ("公交路线", "🚌"),
    "amap_weather_live": ("实时天气", "🌤"),
    "amap_weather_forecast": ("天气预报", "☔"),
    "exa_search": ("联网搜索", "🔎"),
    "tencent_hot_news": ("热点新闻", "📰"),
    "tencent_news_search": ("新闻搜索", "🗞"),
    "tripnow_public": ("公共出行查询", "🎫"),
    "tripnow_personal": ("个人出行查询", "🧳"),
    "express_tracking": ("快递查询", "📦"),
    "music_play": ("音乐播放", "🎵"),
    "music_control": ("音乐控制（电脑端）", "🎚"),
}


def build_builtin_manifests(dispatcher) -> list[dict]:
    """从当前实际注册的 Dispatcher 生成目录，缺少 key 的能力不会虚假展示。

    内置能力也声明成 MCP skill manifest，但 transport 使用 ``local``：执行时
    由 LocalHandlerClient 转回原 Handler，避免为了统一协议再增加本机 HTTP 跳转。
    """
    manifests = []
    for spec in dispatcher.visible_specs("pc"):
        name, icon = _NAMES.get(spec.id, (spec.id, "🧩"))
        properties = {}
        required = []
        for slot in spec.slots:
            properties[slot.name] = {
                "type": slot.type,
                "description": slot.description,
            }
            if slot.required:
                required.append(slot.name)
        manifests.append(
            {
                "kind": "builtin",
                "skill_id": f"builtin:{spec.id}",
                "name": name,
                "icon": icon,
                "description": spec.description,
                "intent": spec.id,
                "entry_tool": spec.id,
                "query_slot": next((s.name for s in spec.slots if s.type == "string"), None),
                "mcp_server": {"transport": "local", "url": f"handler://{spec.id}"},
                "always_enabled": True,
                "keywords": list(spec.keywords),
                "tools": [{
                    "name": spec.id,
                    "description": spec.description,
                    "input_schema": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                }],
                "credentials": {"type": "none"},
                "pc_only": spec.id == "music_control",
            }
        )
    return manifests
