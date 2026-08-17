from __future__ import annotations

import re
import tkinter as tk
from itertools import count
from tkinter import font as tkfont

from pygments import highlight
from pygments.formatter import Formatter
from pygments.lexers import TextLexer, get_lexer_by_name
from pygments.token import Token


class TkPygmentsFormatter(Formatter):
    def __init__(self, text: tk.Text, base_tag: str) -> None:
        super().__init__()
        self.text = text
        self.base_tag = base_tag
        self.styles = {
            Token.Keyword: "#9b4dca",
            Token.Name.Function: "#0f766e",
            Token.Name.Class: "#0f766e",
            Token.String: "#b45309",
            Token.Number: "#2563eb",
            Token.Comment: "#64748b",
            Token.Operator: "#475569",
            Token.Error: "#b91c1c",
        }

    def format(self, tokensource, outfile) -> None:  # type: ignore[override]
        for token_type, value in tokensource:
            tags = [self.base_tag]
            color = self._color_for(token_type)
            if color:
                tag = f"syntax_{color.strip('#')}"
                if tag not in self.text.tag_names():
                    self.text.tag_configure(tag, foreground=color)
                tags.append(tag)
            self.text.insert(tk.END, value, tuple(tags))

    def _color_for(self, token_type) -> str | None:
        current = token_type
        while current is not Token:
            if current in self.styles:
                return self.styles[current]
            current = current.parent
        return None


class MarkdownRenderer:
    def __init__(self, text: tk.Text) -> None:
        self.text = text
        self._fold_ids = count(1)
        base = tkfont.nametofont("TkDefaultFont")
        mono = tkfont.nametofont("TkFixedFont")
        self.fonts = {
            "body": base.copy(),
            "h1": base.copy(),
            "h2": base.copy(),
            "h3": base.copy(),
            "bold": base.copy(),
            "italic": base.copy(),
            "code": mono.copy(),
            "small": base.copy(),
        }
        for name in ("body", "h1", "h2", "h3", "bold", "italic", "small"):
            self.fonts[name].configure(family="Segoe UI")
        self.fonts["body"].configure(size=11)
        self.fonts["code"].configure(family="Cascadia Mono", size=10)
        self.fonts["h1"].configure(size=18, weight="bold")
        self.fonts["h2"].configure(size=15, weight="bold")
        self.fonts["h3"].configure(size=12, weight="bold")
        self.fonts["bold"].configure(weight="bold")
        self.fonts["italic"].configure(slant="italic")
        body_size = int(base.cget("size")) if str(base.cget("size")).lstrip("-").isdigit() else 10
        self.fonts["small"].configure(size=max(8, body_size - 1))
        self._configure_tags()

    def _configure_tags(self) -> None:
        t = self.text
        t.tag_configure("body", font=self.fonts["body"], foreground="#2f2a24", lmargin1=64, lmargin2=64, rmargin=96, spacing1=1, spacing3=7)
        t.tag_configure("user_name", foreground="#7a6a58", font=self.fonts["small"], justify="right", lmargin1=120, lmargin2=120, rmargin=64, spacing1=14, spacing3=4)
        t.tag_configure("assistant_name", foreground="#8b6f4e", font=self.fonts["bold"], lmargin1=64, lmargin2=64, rmargin=96, spacing1=14, spacing3=4)
        t.tag_configure("meta", foreground="#8c8275", font=self.fonts["small"])
        t.tag_configure("h1", font=self.fonts["h1"], foreground="#2f2a24", lmargin1=64, lmargin2=64, rmargin=96, spacing1=10, spacing3=8)
        t.tag_configure("h2", font=self.fonts["h2"], foreground="#2f2a24", lmargin1=64, lmargin2=64, rmargin=96, spacing1=10, spacing3=7)
        t.tag_configure("h3", font=self.fonts["h3"], foreground="#5f4b36", lmargin1=64, lmargin2=64, rmargin=96, spacing1=8, spacing3=6)
        t.tag_configure("bold", font=self.fonts["bold"])
        t.tag_configure("italic", font=self.fonts["italic"])
        t.tag_configure("inline_code", font=self.fonts["code"], background="#eee7dc", foreground="#2f2a24")
        t.tag_configure("code_block", font=self.fonts["code"], background="#f0ebe2", foreground="#2c2721", lmargin1=78, lmargin2=78, rmargin=92, spacing1=8, spacing3=8)
        t.tag_configure("quote", foreground="#6d6256", background="#f1ede5", lmargin1=78, lmargin2=78, rmargin=96, spacing1=5, spacing3=5)
        t.tag_configure("list", foreground="#2f2a24", lmargin1=82, lmargin2=104, rmargin=96, spacing3=4)
        t.tag_configure("highlight", background="#f6e7a9", foreground="#2f2a24")
        t.tag_configure("link", foreground="#6f5a35", underline=True)
        t.tag_configure("rule", foreground="#d8d0c2", lmargin1=64, lmargin2=64, rmargin=96)
        t.tag_configure("error", foreground="#9f2d20", background="#f7ddd7", lmargin1=64, lmargin2=64, rmargin=96)
        t.tag_configure("mermaid", font=self.fonts["code"], background="#e8f1ed", foreground="#315c50", lmargin1=78, lmargin2=78, rmargin=92, spacing1=8, spacing3=8)
        t.tag_configure("user_bubble", font=self.fonts["body"], background="#e9e1d3", foreground="#2f2a24", justify="right", lmargin1=170, lmargin2=170, rmargin=64, spacing1=4, spacing3=4)
        t.tag_configure("loading", foreground="#8b6f4e", font=self.fonts["italic"], lmargin1=64, lmargin2=64, rmargin=96, spacing1=4, spacing3=8)
        t.tag_configure("reasoning_header", foreground="#7a6a58", font=self.fonts["small"], lmargin1=64, lmargin2=64, rmargin=96, spacing1=8, spacing3=4)
        t.tag_configure("reasoning_body", foreground="#6d6256", background="#f1ede5", lmargin1=78, lmargin2=78, rmargin=96, spacing1=5, spacing3=5)
        t.tag_configure(tk.SEL, background="#b88a55", foreground="#fffdf8")
        t.tag_raise(tk.SEL)

    def append_role_header(self, role: str, created_at: str = "") -> None:
        if self.text.index(tk.END) != "1.0":
            self.text.insert(tk.END, "\n")
        label = "\u4f60" if role == "user" else "myChatGPT"
        tag = "user_name" if role == "user" else "assistant_name"
        self.text.insert(tk.END, label, (tag,))
        if created_at:
            stamp = created_at[11:16] if len(created_at) >= 16 else created_at
            self.text.insert(tk.END, f"  {stamp}", (tag, "meta"))
        self.text.insert(tk.END, "\n")

    def append_user_message(self, markdown: str, created_at: str = "") -> None:
        self.append_role_header("user", created_at)
        lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n") if markdown else [""]
        for line in lines:
            if line.strip():
                self._insert_inline(line, base_tag="user_bubble")
            else:
                self.text.insert(tk.END, " ", ("user_bubble",))
            self.text.insert(tk.END, "\n", ("user_bubble",))
        self.text.insert(tk.END, "\n")
        self.text.see(tk.END)

    def append_markdown(self, markdown: str) -> None:
        lines = markdown.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        in_code = False
        code_lang = ""
        code_lines: list[str] = []
        for line in lines:
            fence = re.match(r"^\s*```([A-Za-z0-9_+.-]*)\s*$", line)
            if fence:
                if in_code:
                    self._insert_code_block("\n".join(code_lines), code_lang)
                    in_code = False
                    code_lang = ""
                    code_lines = []
                else:
                    in_code = True
                    code_lang = fence.group(1).strip().lower()
                    code_lines = []
                continue
            if in_code:
                code_lines.append(line)
                continue
            self._insert_markdown_line(line)
        if in_code:
            self._insert_code_block("\n".join(code_lines), code_lang)
        self.text.insert(tk.END, "\n")
        self.text.see(tk.END)

    def append_reasoning(self, markdown: str, *, collapsed: bool = True) -> None:
        content = markdown.strip()
        if not content:
            return
        fold_id = next(self._fold_ids)
        header_tag = f"reasoning_header_{fold_id}"
        body_tag = f"reasoning_body_{fold_id}"
        header_start = f"reasoning_header_start_{fold_id}"
        header_end = f"reasoning_header_end_{fold_id}"
        state = {"collapsed": collapsed}

        self.text.tag_configure(body_tag, elide=collapsed)
        self.text.mark_set(header_start, tk.END)
        self.text.mark_gravity(header_start, tk.LEFT)
        self.text.insert(tk.END, self._reasoning_header_text(collapsed), ("reasoning_header", header_tag))
        self.text.mark_set(header_end, tk.END)
        self.text.mark_gravity(header_end, tk.RIGHT)
        self.text.insert(tk.END, "\n", ("reasoning_header", header_tag))

        for line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            self.text.insert(tk.END, line, ("reasoning_body", body_tag))
            self.text.insert(tk.END, "\n", ("reasoning_body", body_tag))
        self.text.insert(tk.END, "\n", (body_tag,))

        def toggle(_event=None) -> str:
            state["collapsed"] = not state["collapsed"]
            self.text.tag_configure(body_tag, elide=state["collapsed"])
            self.text.delete(header_start, header_end)
            self.text.insert(header_start, self._reasoning_header_text(state["collapsed"]), ("reasoning_header", header_tag))
            return "break"

        self.text.tag_bind(header_tag, "<Button-1>", toggle)
        self.text.tag_bind(header_tag, "<Enter>", lambda _event: self.text.configure(cursor="hand2"))
        self.text.tag_bind(header_tag, "<Leave>", lambda _event: self.text.configure(cursor=""))
        self.text.see(tk.END)

    def _reasoning_header_text(self, collapsed: bool) -> str:
        arrow = "\u25b8" if collapsed else "\u25be"
        label = "\u5df2\u5904\u7406\uff0c\u70b9\u51fb\u67e5\u770b\u8fc7\u7a0b" if collapsed else "\u5904\u7406\u8fc7\u7a0b"
        return f"{arrow} {label}"

    def append_plain(self, text: str, tag: str = "body") -> None:
        self.text.insert(tk.END, text, (tag,))
        self.text.see(tk.END)

    def _insert_markdown_line(self, line: str) -> None:
        if not line.strip():
            self.text.insert(tk.END, "\n")
            return
        if re.match(r"^\s*---+\s*$", line):
            self.text.insert(tk.END, "-" * 80 + "\n", ("rule",))
            return
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        if heading:
            level = len(heading.group(1))
            tag = "h1" if level == 1 else "h2" if level == 2 else "h3"
            self._insert_inline(heading.group(2), base_tag=tag)
            self.text.insert(tk.END, "\n")
            return
        if line.startswith(">"):
            content = line.lstrip("> ")
            self._insert_inline(content, base_tag="quote")
            self.text.insert(tk.END, "\n")
            return
        list_match = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", line)
        if list_match:
            indent = len(list_match.group(1)) // 2
            prefix = "  " * indent + list_match.group(2) + " "
            self.text.insert(tk.END, prefix, ("list",))
            self._insert_inline(list_match.group(3), base_tag="list")
            self.text.insert(tk.END, "\n")
            return
        self._insert_inline(line, base_tag="body")
        self.text.insert(tk.END, "\n")

    def _insert_inline(self, text: str, base_tag: str = "body") -> None:
        pattern = re.compile(
            r"(`[^`]+`|\*\*[^*]+\*\*|__[^_]+__|\*[^*]+\*|_[^_]+_|==[^=]+==|\[[^\]]+\]\([^)]+\))"
        )
        pos = 0
        for match in pattern.finditer(text):
            if match.start() > pos:
                self.text.insert(tk.END, text[pos : match.start()], (base_tag,))
            token = match.group(0)
            if token.startswith("`"):
                self.text.insert(tk.END, token[1:-1], (base_tag, "inline_code"))
            elif token.startswith("**") or token.startswith("__"):
                self.text.insert(tk.END, token[2:-2], (base_tag, "bold"))
            elif token.startswith("=="):
                self.text.insert(tk.END, token[2:-2], (base_tag, "highlight"))
            elif token.startswith("["):
                label = token[1 : token.find("]")]
                self.text.insert(tk.END, label, (base_tag, "link"))
            elif token.startswith("*") or token.startswith("_"):
                self.text.insert(tk.END, token[1:-1], (base_tag, "italic"))
            pos = match.end()
        if pos < len(text):
            self.text.insert(tk.END, text[pos:], (base_tag,))

    def _insert_code_block(self, code: str, lang: str) -> None:
        if lang == "mermaid":
            self.text.insert(tk.END, "Mermaid\n", ("mermaid", "bold"))
            self.text.insert(tk.END, code.rstrip() + "\n", ("mermaid",))
            self.text.insert(tk.END, "\n")
            return
        label = f"{lang}\n" if lang else ""
        if label:
            self.text.insert(tk.END, label, ("code_block", "meta"))
        try:
            lexer = get_lexer_by_name(lang or "text")
        except Exception:
            lexer = TextLexer()
        formatter = TkPygmentsFormatter(self.text, "code_block")
        try:
            highlight(code.rstrip() + "\n", lexer, formatter)
        except Exception:
            self.text.insert(tk.END, code.rstrip() + "\n", ("code_block",))
        self.text.insert(tk.END, "\n")
