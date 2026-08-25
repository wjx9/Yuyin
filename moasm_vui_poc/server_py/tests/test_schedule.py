from routing.handler import RouteContext
from routing.handlers.schedule import (
    AlarmCreateHandler,
    ReminderCreateHandler,
    TimerCreateHandler,
)


def test_alarm_handler_returns_mobile_schedule_action():
    result = AlarmCreateHandler().handle(
        "明天早上七点叫我起床",
        RouteContext(platform="mobile", slots={"alarm_time": "2026-08-26T07:00:00", "title": "起床"}),
    )
    assert result.status == "success"
    assert result.data == {
        "kind": "schedule_action",
        "action": "alarm",
        "title": "起床",
        "trigger_time": "2026-08-26T07:00:00",
    }


def test_timer_handler_parses_duration_from_query():
    result = TimerCreateHandler().handle(
        "设置半小时倒计时",
        RouteContext(platform="mobile"),
    )
    assert result.status == "success"
    assert result.data["action"] == "timer"
    assert result.data["duration_seconds"] == 1800


def test_timer_handler_accepts_half_hour():
    result = TimerCreateHandler().handle(
        "设置半小时倒计时",
        RouteContext(platform="mobile"),
    )
    assert result.status == "success"
    assert result.data["duration_seconds"] == 1800


def test_reminder_handler_returns_mobile_schedule_action():
    result = ReminderCreateHandler().handle(
        "提醒我明天下午三点提交报告",
        RouteContext(
            platform="mobile",
            slots={
                "title": "提交报告",
                "reminder_time": "2026-08-26T15:00:00",
            },
        ),
    )
    assert result.status == "success"
    assert result.data["kind"] == "schedule_action"
    assert result.data["action"] == "reminder"
    assert result.data["trigger_time"] == "2026-08-26T15:00:00"


def test_schedule_actions_are_blocked_on_pc():
    result = TimerCreateHandler().handle(
        "五分钟倒计时", RouteContext(platform="pc", slots={"duration_seconds": 300})
    )
    assert result.status == "blocked"


def test_schedule_actions_remain_registered_for_mobile_planning():
    assert AlarmCreateHandler().spec().id == "alarm_create"
    assert TimerCreateHandler().spec().id == "timer_create"
    assert ReminderCreateHandler().spec().id == "reminder_create"
