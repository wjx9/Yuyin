"""手机端日历本地动作。"""

from __future__ import annotations

from datetime import datetime, timedelta
import re

from ..handler import Handler, RouteContext, RouteResult, SlotSpec


class CalendarCreateHandler(Handler):
    intent = "calendar_create"
    description = (
        "在用户手机系统日历中准备创建一个日程。适用于用户明确要求新建、添加或安排日程；"
        "需要提取标题和开始时间，时间必须使用 ISO 8601 格式，例如 2026-08-26T15:00:00。"
    )
    slots = (
        SlotSpec("title", "string", "日程标题，必填", required=True),
        SlotSpec("start_time", "string", "开始时间，必填；可用 ISO 8601 或用户原话中的中文日期时间", required=True),
        SlotSpec("end_time", "string", "结束时间；可用 ISO 8601 或中文日期时间，未提供时默认持续一小时"),
        SlotSpec("location", "string", "日程地点，没有则留空"),
        SlotSpec("description", "string", "备注内容，没有则留空"),
    )

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        import logging

        logging.getLogger("routing.handlers.calendar").info(
            "日历动作请求：platform=%s，slots=%s", context.platform, context.slots
        )
        if context.platform != "mobile":
            return RouteResult(text="创建日程需要在手机端打开系统日历。", intent=self.intent, status="blocked")
        slots = context.slots
        title = _text(slots.get("title"))
        start_text = _text(slots.get("start_time"))
        if not title or not start_text:
            return RouteResult(text="创建日程还缺少标题或开始时间。", intent=self.intent, status="blocked")
        try:
            start = _parse_datetime(start_text)
            end_text = _text(slots.get("end_time"))
            end = _parse_datetime(end_text) if end_text else start + timedelta(hours=1)
        except ValueError:
            return RouteResult(
                text="创建日程失败：开始或结束时间不是有效的 ISO 8601 时间。",
                intent=self.intent,
                status="blocked",
            )
        if end <= start:
            return RouteResult(text="创建日程失败：结束时间必须晚于开始时间。", intent=self.intent, status="blocked")
        event = {
            "kind": "calendar_event",
            "title": title,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "location": _text(slots.get("location")),
            "description": _text(slots.get("description")),
        }
        text = f"已准备创建日程“{title}”，时间是{start.strftime('%Y年%m月%d日 %H:%M')}。请在手机日历页面确认保存。"
        return RouteResult(text=text, data=event, intent=self.intent)


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _parse_datetime(value: str) -> datetime:
    value = value.strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass

    now = datetime.now()
    date_match = re.search(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", value)
    if date_match:
        year = int(date_match.group(1) or now.year)
        month = int(date_match.group(2))
        day = int(date_match.group(3))
    elif "明天" in value:
        target = now.date() + timedelta(days=1)
        year, month, day = target.year, target.month, target.day
    elif "后天" in value:
        target = now.date() + timedelta(days=2)
        year, month, day = target.year, target.month, target.day
    elif "今天" in value:
        year, month, day = now.year, now.month, now.day
    else:
        raise ValueError("unsupported calendar time")

    clock = re.search(
        r"(上午|早上|中午|下午|晚上)?\s*([0-9一二两三四五六七八九十]{1,3})(?:点|时)"
        r"(?:(\d{1,2})分?)?",
        value,
    )
    if not clock:
        raise ValueError("missing clock time")
    period, hour_text, minute_text = clock.groups()
    hour = _chinese_number(hour_text)
    minute = int(minute_text or 0)
    if period in ("下午", "晚上") and hour < 12:
        hour += 12
    if period == "中午" and hour < 11:
        hour += 12
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("invalid clock time")
    return datetime(year, month, day, hour, minute)


def _chinese_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if value == "十":
        return 10
    if value.startswith("十"):
        return 10 + digits.get(value[1:], 0)
    if value.endswith("十"):
        return digits.get(value[0], 0) * 10
    if "十" in value:
        left, right = value.split("十", 1)
        return digits.get(left, 0) * 10 + digits.get(right, 0)
    if len(value) == 1 and value in digits:
        return digits[value]
    raise ValueError("invalid Chinese number")
