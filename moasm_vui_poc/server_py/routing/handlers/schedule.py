"""手机端闹钟、倒计时和提醒动作。"""

from __future__ import annotations

from datetime import datetime, timedelta
import re

from ..handler import Handler, RouteContext, RouteResult, SlotSpec


class AlarmCreateHandler(Handler):
    intent = "alarm_create"
    description = (
        "在用户手机时钟中准备设置一个闹钟。适用于用户明确要求设置闹钟或在某个时刻提醒；"
        "需要提取时间，时间可使用 ISO 8601 或中文日期时间。"
    )
    slots = (
        SlotSpec("alarm_time", "string", "闹钟时间，必填；可用 ISO 8601 或中文日期时间", required=True),
        SlotSpec("title", "string", "闹钟标签，没有则使用默认标签"),
    )

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        return _handle_alarm_like(
            query=query,
            context=context,
            intent=self.intent,
            action="alarm",
            time_slot="alarm_time",
            default_title="闹钟",
        )


class TimerCreateHandler(Handler):
    intent = "timer_create"
    description = (
        "在用户手机时钟中准备设置一个倒计时。适用于用户要求倒计时、几分钟后提醒或计时；"
        "需要提取持续时长，单位可以是秒、分钟或小时。"
    )
    slots = (
        SlotSpec("duration_seconds", "integer", "倒计时持续秒数，必填"),
        SlotSpec("title", "string", "倒计时标签，没有则使用默认标签"),
    )

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        _log_request(self.intent, context)
        if context.platform != "mobile":
            return _blocked(self.intent, "设置倒计时需要在手机端打开系统时钟。")

        seconds = _integer(context.slots.get("duration_seconds"))
        if seconds is None:
            seconds = _parse_duration_seconds(query)
        if seconds is None or seconds <= 0:
            return _blocked(self.intent, "设置倒计时还缺少有效的持续时间。")

        title = _text(context.slots.get("title")) or "倒计时"
        return RouteResult(
            text=f"已准备设置{_duration_text(seconds)}的倒计时“{title}”，请在手机时钟页面确认。",
            data={
                "kind": "schedule_action",
                "action": "timer",
                "title": title,
                "duration_seconds": seconds,
            },
            intent=self.intent,
        )


class ReminderCreateHandler(Handler):
    intent = "reminder_create"
    description = (
        "在用户手机日历中准备创建一个提醒事项。适用于用户要求在某个时间提醒自己做某件事；"
        "需要提取提醒内容和时间，时间可使用 ISO 8601 或中文日期时间。"
    )
    slots = (
        SlotSpec("title", "string", "提醒内容或标题，必填"),
        SlotSpec("reminder_time", "string", "提醒时间，必填；可用 ISO 8601 或中文日期时间", required=True),
        SlotSpec("description", "string", "提醒备注，没有则留空"),
    )

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        _log_request(self.intent, context)
        if context.platform != "mobile":
            return _blocked(self.intent, "创建提醒需要在手机端打开系统日历。")

        title = _text(context.slots.get("title")) or _extract_reminder_title(query)
        time_text = _text(context.slots.get("reminder_time"))
        if not time_text:
            time_text = query
        try:
            start = _parse_schedule_datetime(time_text)
        except ValueError:
            return _blocked(self.intent, "创建提醒还缺少有效的提醒时间。")

        end = start + timedelta(minutes=5)
        return RouteResult(
            text=f"已准备创建提醒“{title}”，时间是{start.strftime('%Y年%m月%d日 %H:%M')}。请在手机日历页面确认保存。",
            data={
                "kind": "schedule_action",
                "action": "reminder",
                "title": title,
                "trigger_time": start.isoformat(),
                "end_time": end.isoformat(),
                "description": _text(context.slots.get("description")),
            },
            intent=self.intent,
        )


def _handle_alarm_like(
    *, query: str, context: RouteContext, intent: str, action: str,
    time_slot: str, default_title: str,
) -> RouteResult:
    _log_request(intent, context)
    if context.platform != "mobile":
        return _blocked(intent, "设置闹钟需要在手机端打开系统时钟。")

    time_text = _text(context.slots.get(time_slot)) or query
    try:
        target = _parse_schedule_datetime(time_text)
    except ValueError:
        return _blocked(intent, "设置闹钟还缺少有效的时间。")
    title = _text(context.slots.get("title")) or default_title
    return RouteResult(
        text=f"已准备设置闹钟“{title}”，时间是{target.strftime('%Y年%m月%d日 %H:%M')}。请在手机时钟页面确认。",
        data={
            "kind": "schedule_action",
            "action": action,
            "title": title,
            "trigger_time": target.isoformat(),
        },
        intent=intent,
    )


def _log_request(intent: str, context: RouteContext) -> None:
    import logging

    logging.getLogger(f"routing.handlers.{intent}").info(
        "手机时间动作请求：platform=%s，slots=%s", context.platform, context.slots
    )


def _blocked(intent: str, text: str) -> RouteResult:
    return RouteResult(text=text, intent=intent, status="blocked")


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _integer(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return None


def _parse_schedule_datetime(value: str) -> datetime:
    value = value.strip()
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        pass

    now = datetime.now()
    relative = re.search(r"([0-9一二两三四五六七八九十]+)\s*(秒|分钟|分|小时|时)后", value)
    if relative:
        amount = _chinese_number(relative.group(1))
        unit = relative.group(2)
        seconds = amount if unit == "秒" else amount * (3600 if unit in ("小时", "时") else 60)
        return now + timedelta(seconds=seconds)

    date_match = re.search(r"(?:(\d{4})年)?(\d{1,2})月(\d{1,2})日", value)
    if date_match:
        year = int(date_match.group(1) or now.year)
        month, day = int(date_match.group(2)), int(date_match.group(3))
    elif "明天" in value:
        target = now.date() + timedelta(days=1)
        year, month, day = target.year, target.month, target.day
    elif "后天" in value:
        target = now.date() + timedelta(days=2)
        year, month, day = target.year, target.month, target.day
    else:
        year, month, day = now.year, now.month, now.day

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
    return datetime(year, month, day, hour, minute)


def _parse_duration_seconds(value: str) -> int | None:
    matches = re.findall(r"([0-9一二两三四五六七八九十半]+)\s*(小时|时|分钟|分|秒)", value)
    if not matches:
        return None
    total = 0.0
    for number, unit in matches:
        amount = 0.5 if number == "半" else _chinese_number(number)
        total += amount * (3600 if unit in ("小时", "时") else 60 if unit in ("分钟", "分") else 1)
    return int(total) if total > 0 else None


def _duration_text(seconds: int) -> str:
    if seconds % 3600 == 0:
        return f"{seconds // 3600}小时"
    if seconds % 60 == 0:
        return f"{seconds // 60}分钟"
    return f"{seconds}秒"


def _extract_reminder_title(query: str) -> str:
    cleaned = re.sub(r"^\s*(请)?提醒我\s*", "", query).strip()
    return cleaned or "提醒事项"


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
