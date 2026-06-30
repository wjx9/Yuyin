"""终端 Presenter：聊天气泡风格——用户输入靠左、AI 输出靠右，中间夹变暗的日志区。

颜色用 ANSI；非 TTY（重定向到文件/管道）自动关闭。Windows 上尝试按官方文档启用
虚拟终端处理（ENABLE_VIRTUAL_TERMINAL_PROCESSING），失败则降级为无颜色（框线仍在）。
"""

from __future__ import annotations

import logging
import os
import shutil
import sys

from .layout import display_width, render_box
from .presenter import CHITCHAT_INTENT, Presenter, _plain

_RESET = "\033[0m"
_DIM = "\033[2m"
_CYAN = "\033[36m"  # 用户输入框
_GREEN = "\033[32m"  # AI 输出框
_GRAY = "\033[90m"  # 横幅/提示


def _enable_windows_ansi() -> bool:
    """在 Windows 控制台启用 ANSI 转义（官方 SetConsoleMode 文档机制）。"""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        return bool(kernel32.SetConsoleMode(handle, mode.value | 0x0004))
    except Exception:
        return False


class TerminalPresenter(Presenter):
    def __init__(self, *, color: bool | None = None, stream=None):
        self._out = stream or sys.stdout
        if color is None:
            color = bool(getattr(self._out, "isatty", lambda: False)()) and _enable_windows_ansi()
        self._color = color

    # ---- 公开接口 ----

    def banner(self, intents: list[str]) -> None:
        self._line(self._paint(f"● 已启用意图：{', '.join(intents)}", _GRAY))

    def intro(self, specs) -> None:
        tasks = [s for s in specs if s.id != CHITCHAT_INTENT]
        chitchat = next((s for s in specs if s.id == CHITCHAT_INTENT), None)
        lines: list[str] = ["直接用自然语言提问即可，我会自动判断该用哪个能力。", ""]
        if tasks:
            lines.append("已接入的能力：")
            for s in tasks:
                lines.append(f"  • {_plain(s.description)}")
        else:
            lines.append("当前仅启用了闲聊（其它能力的 key 未配置，未接入第三方能力）。")
        if chitchat:
            lines.append("")
            lines.append(f"其余对话兜底闲聊：{_plain(chitchat.description)}")
        lines.append("")
        lines.append("输入 exit / quit 退出；--debug 看路由细节。")

        term = shutil.get_terminal_size((80, 24)).columns
        inner_cap = max(20, min(term - 2, 76))
        box = render_box("使用说明", "\n".join(lines), inner_cap)
        self._line("")
        for ln in box:
            self._line(self._paint(ln, _GRAY))

    def info(self, message: str) -> None:
        self._line(self._paint(f"● {message}", _GRAY))

    def show_input(self, text: str) -> None:
        self._bubble("你", text, color=_CYAN, align="left", cap_ratio=0.6)
        self._out.flush()  # 确保输入框先于 dispatch 期间的日志落屏

    def show_output(self, text: str, *, intent: str | None = None) -> None:
        label = "助手" + (f" · {intent}" if intent else "")
        self._bubble(label, text, color=_GREEN, align="right", cap_ratio=0.82)

    def log_formatter(self) -> logging.Formatter:
        # 中间日志区：缩进 + 变暗 + 前缀 ·，与左右气泡一眼区分
        fmt = "    · %(levelname)s %(name)s: %(message)s"
        if self._color:
            fmt = f"{_DIM}{fmt}{_RESET}"
        return logging.Formatter(fmt)

    # ---- 内部 ----

    def _bubble(self, label: str, text: str, *, color: str, align: str, cap_ratio: float) -> None:
        term = shutil.get_terminal_size((80, 24)).columns
        inner_cap = max(12, min(int(term * cap_ratio), term - 6))
        lines = render_box(label, text or "（空）", inner_cap)
        box_w = display_width(lines[0])
        pad = " " * max(0, term - box_w) if align == "right" else ""
        self._line("")  # 气泡间留白
        for ln in lines:
            self._line(pad + self._paint(ln, color))

    def _paint(self, text: str, color: str) -> str:
        return f"{color}{text}{_RESET}" if self._color else text

    def _line(self, text: str) -> None:
        print(text, file=self._out)
