from routing.handler import RouteContext
from routing.handlers.calendar import CalendarCreateHandler


def test_calendar_handler_returns_mobile_local_action():
    result = CalendarCreateHandler().handle(
        "明天下午三点开项目例会",
        RouteContext(
            platform="mobile",
            slots={
                "title": "项目例会",
                "start_time": "2026-08-26T15:00:00",
                "end_time": "2026-08-26T16:00:00",
                "location": "会议室 A",
            },
        ),
    )

    assert result.intent == "calendar_create"
    assert result.data["kind"] == "calendar_event"
    assert result.data["title"] == "项目例会"
    assert result.data["start_time"] == "2026-08-26T15:00:00"


def test_calendar_handler_defaults_one_hour_end_time():
    result = CalendarCreateHandler().handle(
        "创建一个日程",
        RouteContext(
            platform="mobile",
            slots={"title": "阅读", "start_time": "2026-08-26T15:00:00"},
        ),
    )

    assert result.data["end_time"] == "2026-08-26T16:00:00"


def test_calendar_handler_blocks_missing_required_values():
    result = CalendarCreateHandler().handle(
        "创建日程",
        RouteContext(platform="mobile", slots={"title": "阅读"}),
    )

    assert result.status == "blocked"
    assert result.data is None


def test_calendar_handler_accepts_common_chinese_time():
    result = CalendarCreateHandler().handle(
        "\u4eca\u5929\u665a\u4e0a\u4e03\u70b9\u4e0b\u73ed",
        RouteContext(
            platform="mobile",
            slots={"title": "\u4e0b\u73ed", "start_time": "\u4eca\u5929\u665a\u4e0a\u4e03\u70b9"},
        ),
    )

    assert result.status == "success"
    assert result.data["start_time"].endswith("19:00:00")
