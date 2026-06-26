"""UI 布局纯函数单测：CJK 宽度、折行、画框（不涉及 ANSI/IO）。"""

from __future__ import annotations

from ui.layout import display_width, render_box, wrap


def test_display_width_counts_cjk_as_two():
    assert display_width("ab") == 2
    assert display_width("你好") == 4
    assert display_width("a你") == 3


def test_wrap_by_display_width():
    # 每个中文 2 列，width=4 → 每行最多 2 个中文
    assert wrap("一二三四五", 4) == ["一二", "三四", "五"]


def test_wrap_preserves_explicit_newlines():
    assert wrap("a\n\nb", 10) == ["a", "", "b"]


def test_render_box_lines_equal_width_and_framed():
    lines = render_box("你", "你好", 40)
    widths = {display_width(ln) for ln in lines}
    assert len(widths) == 1  # 每行显示宽度一致
    assert lines[0].startswith("┌─ 你 ")
    assert lines[0].endswith("┐")
    assert lines[-1].startswith("└") and lines[-1].endswith("┘")
    assert all(ln.startswith("│") and ln.endswith("│") for ln in lines[1:-1])


def test_render_box_wraps_long_text_within_cap():
    lines = render_box("助手", "床前明月光疑是地上霜举头望明月低头思故乡", 16)
    assert display_width(lines[0]) <= 18  # 内宽 cap=16 + 两侧边框
    assert len(lines) >= 4  # 顶 + 多行 + 底


def test_render_box_label_drives_min_width():
    # label 比内容长时，框宽由 label 决定，仍闭合
    lines = render_box("助手 · tencent_weather", "晴", 80)
    assert "助手 · tencent_weather" in lines[0]
    assert display_width(lines[0]) == display_width(lines[-1])
