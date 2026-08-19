"""高德 A2A 领域模型。

A2A 协议把一切都包成 Message：role + parts[]，每个 part 是 {type, text}。
高德返回的 text 内部往往又是一段 JSON 字符串（业务结果），这里只保留
人类可读的文本，业务结构原样塞进 raw 供上层需要时解析。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MapQuery:
    """把自然语言诉求拆成 REST 检索所需的结构化参数。

    REST 接口不像 A2A agent 能自己理解整句，必须显式给出"搜什么 + 在哪搜"：
        keywords —— 要检索的对象/品类（如"美食""川菜""景点"），必填
        near     —— 用户指定的地点/地标（如"深圳万科云城"），需先定位成坐标再周边搜；
                    为空表示"我附近"，退回 GPS/默认坐标
        city     —— 限定城市（辅助 near 的定位与关键词搜索），可为空
    """

    keywords: str
    near: str | None = None
    city: str | None = None


@dataclass
class Poi:
    """一个榜单 POI（店铺/景点）。高德把它埋在 contentInfos 的结构里。"""

    name: str
    rating: float | None = None
    rating_desc: str | None = None
    distance_m: int | None = None
    address: str | None = None
    open_time: str | None = None
    reason: str | None = None

@dataclass
class GeoPoint:
    """一个地址解析后的地点。location 格式固定为 '经度,纬度'。"""

    formatted_address: str
    location: str
    adcode: str | None = None
    city: str | None = None

@dataclass
class WeatherLive:
    """高德实时天气。"""

    city: str
    weather: str
    temperature: str
    winddirection: str | None = None
    windpower: str | None = None
    humidity: str | None = None
    reporttime: str | None = None

@dataclass
class WeatherDay:
    """某一天的天气预报。"""

    date: str
    day_weather: str
    night_weather: str
    day_temp: str
    night_temp: str
    day_wind: str | None = None
    night_wind: str | None = None
    day_power: str | None = None
    night_power: str | None = None


@dataclass
class WeatherForecast:
    """高德未来天气预报。"""

    city: str
    reporttime: str | None = None
    days: list[WeatherDay] = field(default_factory=list)

@dataclass
class RouteStep:
    """一段驾车导航指令。"""

    instruction: str
    distance_m: int | None = None
    road_name: str | None = None


@dataclass
class DrivingRoute:
    """高德驾车路线规划结果。"""

    origin: GeoPoint
    destination: GeoPoint
    distance_m: int
    duration_s: int
    strategy: str | None = None
    tolls: float | None = None
    toll_distance_m: int | None = None
    steps: list[RouteStep] = field(default_factory=list)


@dataclass
class ActiveRoute:
    """步行或骑行路线规划结果。"""

    origin: GeoPoint
    destination: GeoPoint
    distance_m: int
    duration_s: int
    steps: list[RouteStep] = field(default_factory=list)


@dataclass
class TransitRoute:
    """公交/地铁路线规划结果。"""

    origin: GeoPoint
    destination: GeoPoint
    distance_m: int | None
    duration_s: int | None
    walking_distance_m: int | None = None
    cost_yuan: float | None = None
    transfers: int | None = None
    segments: list[str] = field(default_factory=list)



@dataclass
class MapResult:
    text: str
    pois: list[Poi] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_message(cls, message: dict[str, Any], raw: dict[str, Any] | None = None) -> "MapResult":
        """从 A2A Message/Artifact 提取文本 + 结构化榜单。

        高德的回答是 DataPart（kind="data"）：
          - 正文文案散在 type=markdown 的 data.displayText/text，需按序拼接（只是开场白/小结）；
          - 真正的榜单（店名/评分/距离/地址/推荐语）埋在 type=container 的
            data...contentInfos 结构里，必须挖出来，否则只剩一句营销话术。
        raw 默认存这段 message，调用方可传完整 result 便于调试。
        """
        parts = message.get("parts") or []
        texts: list[str] = []
        content_infos: list[Any] = []
        for p in parts:
            data = p.get("data") or {}
            t = p.get("text") or data.get("displayText") or data.get("text")
            if t:
                texts.append(t)
            content_infos.extend(_find_content_infos(data))

        pois = _pois_from_content_infos(content_infos)
        text = _compose_text("".join(texts), pois)
        return cls(text=text, pois=pois, raw=raw if raw is not None else message)

    @classmethod
    def from_rest(cls, data: dict[str, Any]) -> "MapResult":
        """从高德 Web 服务 REST（place/around|text）的响应构造结果。"""
        pois = pois_from_rest(data.get("pois") or [])
        text = _compose_text("", pois) if pois else "附近没有找到匹配的地点。"
        return cls(text=text, pois=pois, raw=data)


# device_id 仅作设备标识占位（demo 用固定值）；真实产品应传各端唯一 id。
_DEVICE_ID = "tripnow-cli"


def build_message(query: str, *, location: str | None = None) -> dict[str, Any]:
    """构造 A2A message/send 的 params.message。

    高德 ai_native agent 会把 part.text 再当 JSON 解析，约定字段为：
        query     —— 自然语言诉求（必填，缺失会触发服务端 NPE）
        user_loc  —— "经度,纬度"，给 agent 位置上下文
        think     —— 是否返回思考过程，"0" 关闭
        device_id —— 设备标识
        history   —— 多轮历史，无则空数组
    只传 {"query": ...} 时 agent 会回固定兜底话术「网络有些波动」（不报错），
    必须带齐这些字段才会真正调模型。
    """
    inner = {
        "query": query,
        "user_loc": location or "",
        "think": "0",
        "device_id": _DEVICE_ID,
        "history": [],
    }
    # A2A 规范要求 Message/Part 带 "kind" 判别字段（高德用的 Java A2A SDK
    # 靠 Jackson 多态反序列化，缺 kind 会报 "missing type id property 'kind'"）。
    return {
        "kind": "message",
        "role": "user",
        "parts": [{"kind": "text", "text": json.dumps(inner, ensure_ascii=False)}],
        "messageId": _new_id(),
    }


def _new_id() -> str:
    import uuid

    return uuid.uuid4().hex


_MAX_POIS = 10  # 榜单可能含 20+ 条，截断避免刷屏


def _find_content_infos(obj: Any) -> list[Any]:
    """递归找出所有 contentInfos 列表（高德嵌套层级不固定，按 key 名兜底搜索）。"""
    found: list[Any] = []
    if isinstance(obj, dict):
        ci = obj.get("contentInfos")
        if isinstance(ci, list):
            found.extend(ci)
        for v in obj.values():
            found.extend(_find_content_infos(v))
    elif isinstance(obj, list):
        for it in obj:
            found.extend(_find_content_infos(it))
    return found


def _pois_from_content_infos(content_infos: list[Any]) -> list[Poi]:
    """从 contentInfos -> content.paragraphList -> paragraphInfoList -> pointInfo 提取 POI。"""
    pois: list[Poi] = []
    for ci in content_infos:
        content = (ci or {}).get("content") or {}
        for para in content.get("paragraphList") or []:
            for info in para.get("paragraphInfoList") or []:
                point = info.get("pointInfo") or {}
                name = point.get("name")
                if not name:
                    continue
                poi = point.get("poi") or {}
                ev = poi.get("evaluation") or {}
                reasons = (info.get("attributes") or {}).get("recommendReason") or []
                pois.append(
                    Poi(
                        name=name,
                        rating=ev.get("rating"),
                        rating_desc=ev.get("ratingDesc"),
                        distance_m=(poi.get("distance") or {}).get("directDistance"),
                        address=poi.get("address"),
                        open_time=poi.get("openTime"),
                        reason=(reasons[0].get("text") if reasons else None),
                    )
                )
                if len(pois) >= _MAX_POIS:
                    return pois
    return pois


def _fmt_distance(m: int) -> str:
    return f"{m / 1000:.1f}km" if m >= 1000 else f"{m}m"


def _compose_text(prose: str, pois: list[Poi]) -> str:
    """把开场白文案 + 结构化榜单拼成可读文本。无榜单时退回纯文案。"""
    if not pois:
        return prose
    lines = [prose, ""] if prose else []
    for i, p in enumerate(pois, 1):
        meta: list[str] = []
        if p.rating:
            meta.append(f"评分{p.rating}" + (f"（{p.rating_desc}）" if p.rating_desc else ""))
        if p.distance_m is not None:
            meta.append(_fmt_distance(p.distance_m))
        head = f"{i}. {p.name}"
        if meta:
            head += "  " + " · ".join(meta)
        lines.append(head)
        if p.address:
            lines.append(f"   地址：{p.address}")
        if p.open_time:
            lines.append(f"   营业：{p.open_time}")
        if p.reason:
            lines.append(f"   推荐：{p.reason}")
    return "\n".join(lines)


def _as_str(v: Any) -> str | None:
    """高德 REST 在字段为空时返回 [] 而非 ""/null，这里统一归一为 str | None。"""
    return v if isinstance(v, str) and v.strip() else None


def _as_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _as_int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def pois_from_rest(items: list[Any]) -> list[Poi]:
    """从高德 Web 服务 REST（place/around|text，extensions=all）的 pois[] 提取 Poi。

    评分/营业时间埋在 biz_ext 里；高德在无数据时把 biz_ext 返回成 [] 而非 {}，需兜底。
    """
    pois: list[Poi] = []
    for it in items[:_MAX_POIS]:
        if not isinstance(it, dict):
            continue
        name = _as_str(it.get("name"))
        if not name:
            continue
        biz = it.get("biz_ext")
        if not isinstance(biz, dict):  # 空时高德给 []，归一为 {}
            biz = {}
        pois.append(
            Poi(
                name=name,
                rating=_as_float(biz.get("rating")),
                distance_m=_as_int(it.get("distance")),
                address=_as_str(it.get("address")),
                open_time=_as_str(biz.get("open_time")),
            )
        )
    return pois


def parse_inner_json(text: str) -> Any | None:
    """高德常把结构化结果塞进 text 字段的 JSON 串里，尝试解析，失败返回 None。"""
    text = text.strip()
    if not text or text[0] not in "[{":
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None
