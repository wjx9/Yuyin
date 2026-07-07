from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .storage import Attachment


TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".html",
    ".css", ".scss", ".java", ".kt", ".go", ".rs", ".c", ".cc",
    ".cpp", ".h", ".hpp", ".cs", ".php", ".rb", ".sh", ".ps1",
    ".bat", ".sql", ".xml", ".csv", ".log", ".env", ".dockerfile",
}

MAX_TEXT_CHARS = 80_000
MAX_FILE_CONTEXT_CHARS = 160_000


@dataclass(slots=True)
class FileContext:
    label: str
    content: str


def is_image_attachment(attachment: Attachment) -> bool:
    return attachment.mime.startswith("image/")


def resolve_under_workspace(path_text: str, workspace: str | None = None) -> Path | None:
    raw = path_text.strip().strip("\"'")
    if not raw:
        return None
    path = Path(os.path.expandvars(os.path.expanduser(raw)))
    if not path.is_absolute() and workspace:
        path = Path(workspace) / path
    try:
        return path.resolve()
    except OSError:
        return None


def inside_workspace(path: Path, workspace: str | None) -> bool:
    if not workspace:
        return True
    try:
        path.resolve().relative_to(Path(workspace).resolve())
        return True
    except ValueError:
        return False


def _decode_bytes(raw: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "big5", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_text_file(path: Path, limit: int = MAX_TEXT_CHARS) -> str:
    raw = path.read_bytes()
    if b"\x00" in raw[:4096]:
        return "[二进制文件，未直接展开]"
    text = _decode_bytes(raw[: limit + 8192])
    if len(text) > limit:
        text = text[:limit] + "\n\n[内容过长，已截断]"
    return text


def read_pdf(path: Path, limit: int = MAX_TEXT_CHARS) -> str:
    try:
        import fitz  # type: ignore
    except Exception:
        return "[PDF 文本提取需要 PyMuPDF，当前环境不可用]"
    parts: list[str] = []
    doc = fitz.open(path)
    try:
        for index, page in enumerate(doc):
            if sum(len(item) for item in parts) >= limit:
                parts.append("[内容过长，已截断]")
                break
            parts.append(f"\n--- 第 {index + 1} 页 ---\n{page.get_text()}")
    finally:
        doc.close()
    return "".join(parts)[:limit]


def summarize_directory(path: Path, limit: int = 120) -> str:
    rows = []
    try:
        children = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError as exc:
        return f"[无法读取目录：{exc}]"
    for child in children[:limit]:
        kind = "dir " if child.is_dir() else "file"
        try:
            size = "" if child.is_dir() else f" {child.stat().st_size} bytes"
        except OSError:
            size = ""
        rows.append(f"{kind:4} {child.name}{size}")
    if len(children) > limit:
        rows.append(f"... 还有 {len(children) - limit} 项")
    return "\n".join(rows)


def extract_file_content(path: Path) -> str:
    if path.is_dir():
        return summarize_directory(path)
    if not path.exists():
        return "[路径不存在]"
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return read_pdf(path)
    if suffix in TEXT_EXTENSIONS or not suffix:
        return read_text_file(path)
    try:
        import mimetypes
        mime = mimetypes.guess_type(path.name)[0] or ""
    except Exception:
        mime = ""
    if mime.startswith("text/"):
        return read_text_file(path)
    return f"[{path.name} 不是可直接展开的文本文件，大小 {path.stat().st_size} bytes]"


def attachment_context(attachments: list[Attachment]) -> list[FileContext]:
    contexts: list[FileContext] = []
    budget = MAX_FILE_CONTEXT_CHARS
    for attachment in attachments:
        if is_image_attachment(attachment):
            continue
        path = Path(attachment.path)
        if not path.exists():
            continue
        content = extract_file_content(path)
        if len(content) > budget:
            content = content[:budget] + "\n\n[附件内容因上下文长度限制被截断]"
        contexts.append(FileContext(label=f"附件 {attachment.name}", content=content))
        budget -= len(content)
        if budget <= 0:
            break
    return contexts


def referenced_path_context(text: str, workspace: str | None) -> list[FileContext]:
    patterns = [
        r'"([^"\r\n]+)"',
        r"'([^'\r\n]+)'",
        r"([A-Za-z]:\\[^\r\n<>|?*]+)",
        r"((?:\.\.?[\\/])?[A-Za-z0-9_. -]+[\\/][^\r\n<>|?*]+)",
    ]
    candidates: list[str] = []
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            value = match.group(1).strip()
            if value and value not in candidates:
                candidates.append(value)
    contexts: list[FileContext] = []
    budget = MAX_FILE_CONTEXT_CHARS
    for candidate in candidates[:12]:
        path = resolve_under_workspace(candidate, workspace)
        if not path or not path.exists():
            continue
        content = extract_file_content(path)
        if len(content) > budget:
            content = content[:budget] + "\n\n[文件内容因上下文长度限制被截断]"
        contexts.append(FileContext(label=f"本地路径 {path}", content=content))
        budget -= len(content)
        if budget <= 0:
            break
    return contexts


def context_to_prompt(contexts: list[FileContext]) -> str:
    if not contexts:
        return ""
    blocks = []
    for item in contexts:
        blocks.append(f"### {item.label}\n```\n{item.content}\n```")
    return "\n\n".join(blocks)


class WorkspaceToolbox:
    def __init__(self, workspace: str, *, allow_writes: bool = False) -> None:
        self.workspace = Path(workspace).resolve()
        self.allow_writes = allow_writes

    def _path(self, value: str = ".") -> Path:
        path = resolve_under_workspace(value or ".", str(self.workspace))
        if not path:
            raise ValueError("无效路径")
        if not inside_workspace(path, str(self.workspace)):
            raise ValueError("路径必须位于工作文件夹内")
        return path

    def list_dir(self, path: str = ".") -> str:
        return summarize_directory(self._path(path))

    def read_file(self, path: str) -> str:
        return extract_file_content(self._path(path))

    def write_file(self, path: str, content: str) -> str:
        if not self.allow_writes:
            return "写入工具未启用。请在界面勾选允许写入/命令。"
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"已写入 {target}"

    def search_text(self, pattern: str, path: str = ".") -> str:
        root = self._path(path)
        matches: list[str] = []
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"正则表达式无效：{exc}"
        files = [root] if root.is_file() else list(root.rglob("*"))
        for file_path in files:
            if len(matches) >= 200:
                matches.append("[结果过多，已截断]")
                break
            if not file_path.is_file() or file_path.suffix.lower() not in TEXT_EXTENSIONS:
                continue
            try:
                for line_no, line in enumerate(read_text_file(file_path, 40_000).splitlines(), start=1):
                    if regex.search(line):
                        rel = file_path.relative_to(self.workspace)
                        matches.append(f"{rel}:{line_no}: {line[:240]}")
                        if len(matches) >= 200:
                            break
            except OSError:
                continue
        return "\n".join(matches) or "没有匹配结果"

    def run_command(self, command: str, timeout_seconds: int = 60) -> str:
        if not self.allow_writes:
            return "命令工具未启用。请在界面勾选允许写入/命令。"
        completed = subprocess.run(
            command,
            cwd=self.workspace,
            shell=True,
            text=True,
            capture_output=True,
            timeout=max(1, min(timeout_seconds, 180)),
        )
        output = completed.stdout + completed.stderr
        if len(output) > 20_000:
            output = output[:20_000] + "\n[输出过长，已截断]"
        return f"exit={completed.returncode}\n{output}"

    def execute(self, tool: str, args: dict[str, Any]) -> str:
        try:
            if tool == "list_dir":
                return self.list_dir(str(args.get("path") or "."))
            if tool == "read_file":
                return self.read_file(str(args.get("path") or ""))
            if tool == "write_file":
                return self.write_file(str(args.get("path") or ""), str(args.get("content") or ""))
            if tool == "search_text":
                return self.search_text(str(args.get("pattern") or ""), str(args.get("path") or "."))
            if tool == "run_command":
                return self.run_command(str(args.get("command") or ""), int(args.get("timeout_seconds") or 60))
        except subprocess.TimeoutExpired:
            return "命令超时"
        except Exception as exc:
            return f"工具执行失败：{exc}"
        return f"未知工具：{tool}"
