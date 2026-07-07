from __future__ import annotations

import os
import sys


def _hide_console_window() -> None:
    if os.name != "nt" or os.environ.get("MYCHATGPT_SHOW_CONSOLE") == "1":
        return
    try:
        import ctypes

        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


_hide_console_window()

from mychatgpt.app import main  # noqa: E402


if __name__ == "__main__":
    main()
