"""纯布局工具：CJK 宽度计算、按显示宽度折行、画文本框。

全部是无副作用纯函数（不碰 ANSI、不碰 IO），便于单测，也便于其它 Presenter 复用。
画框只用 GBK 也包含的单线制表符（┌┐└┘─│），避免在 Windows 中文控制台变成乱码。
"""

from __future__ import annotations

import unicodedata


def char_width(ch: str) -> int:
    """单字符显示宽度：东亚全角/宽字符算 2 列，其余算 1 列。"""
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def display_width(text: str) -> int:
    """字符串在等宽终端里的显示宽度（列数）。"""
    return sum(char_width(c) for c in text)


def wrap(text: str, width: int) -> list[str]:
    """按显示宽度折行；保留原有换行；超长串按字符切断（对 CJK 友好）。"""
    width = max(1, width)
    out: list[str] = []
    for para in text.split("\n"):
        if not para:
            out.append("")
            continue
        cur = ""
        cur_w = 0
        for ch in para:
            w = char_width(ch)
            if cur_w + w > width and cur:
                out.append(cur)
                cur, cur_w = ch, w
            else:
                cur += ch
                cur_w += w
        out.append(cur)
    return out


def _pad(text: str, width: int) -> str:
    """右侧补空格到指定显示宽度。"""
    return text + " " * max(0, width - display_width(text))


def render_box(label: str, text: str, inner_cap: int) -> list[str]:
    """把 (label, text) 画成一个文本框，返回每行字符串（不含对齐/颜色）。

    返回的每一行显示宽度相同 = 框总宽。inner_cap 是内容区最大列宽，文本超出则折行。
    框形如：
        ┌─ label ───────┐
        │ 行1            │
        │ 行2            │
        └────────────────┘
    """
    inner_cap = max(8, inner_cap)
    usable = inner_cap - 2  # 两侧各留 1 空格
    lines = wrap(text, usable) or [""]
    content_w = max((display_width(ln) for ln in lines), default=0)

    # 内宽需同时容纳内容(+2 padding)与顶部 label("─ label " 段 + 至少 1 个填充横线)
    inner = max(content_w + 2, display_width(label) + 4, 6)
    inner = min(inner, inner_cap)
    usable = inner - 2
    lines = wrap(text, usable) or [""]

    fill = inner - 3 - display_width(label)  # "─ " + label + " " 之后剩余横线数
    top = "┌─ " + label + " " + "─" * max(1, fill) + "┐"
    body = ["│ " + _pad(ln, usable) + " │" for ln in lines]
    bottom = "└" + "─" * inner + "┘"
    return [top, *body, bottom]
