from __future__ import annotations

import json
import mimetypes
import shutil
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from PIL import Image

from .config import app_data_dir


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


@dataclass(slots=True)
class Attachment:
    id: str
    name: str
    path: str
    mime: str
    size: int
    kind: str = "file"

    @classmethod
    def from_path(cls, path: Path, *, kind: str = "file") -> "Attachment":
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return cls(
            id=uuid.uuid4().hex,
            name=path.name,
            path=str(path),
            mime=mime,
            size=path.stat().st_size if path.exists() else 0,
            kind=kind,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Attachment":
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex),
            name=str(data.get("name") or "attachment"),
            path=str(data.get("path") or ""),
            mime=str(data.get("mime") or "application/octet-stream"),
            size=int(data.get("size") or 0),
            kind=str(data.get("kind") or "file"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Message:
    role: str
    content: str
    created_at: str = field(default_factory=now_iso)
    attachments: list[Attachment] = field(default_factory=list)
    reasoning: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        return cls(
            role=str(data.get("role") or "user"),
            content=str(data.get("content") or ""),
            created_at=str(data.get("created_at") or now_iso()),
            attachments=[
                Attachment.from_dict(item)
                for item in data.get("attachments", [])
                if isinstance(item, dict)
            ],
            reasoning=str(data.get("reasoning") or ""),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "content": self.content,
            "created_at": self.created_at,
            "attachments": [item.to_dict() for item in self.attachments],
            "reasoning": self.reasoning,
        }


@dataclass(slots=True)
class Conversation:
    id: str
    title: str
    created_at: str
    updated_at: str
    workspace: str = ""
    messages: list[Message] = field(default_factory=list)

    @classmethod
    def new(cls, workspace: str = "") -> "Conversation":
        stamp = now_iso()
        return cls(
            id=uuid.uuid4().hex,
            title="新对话",
            created_at=stamp,
            updated_at=stamp,
            workspace=workspace,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Conversation":
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex),
            title=str(data.get("title") or "新对话"),
            created_at=str(data.get("created_at") or now_iso()),
            updated_at=str(data.get("updated_at") or now_iso()),
            workspace=str(data.get("workspace") or ""),
            messages=[
                Message.from_dict(item)
                for item in data.get("messages", [])
                if isinstance(item, dict)
            ],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "workspace": self.workspace,
            "messages": [item.to_dict() for item in self.messages],
        }

    def add_message(self, message: Message) -> None:
        self.messages.append(message)
        self.updated_at = now_iso()
        if self.title == "新对话" and message.role == "user":
            title = " ".join(message.content.strip().split())
            if not title and message.attachments:
                title = f"附件：{message.attachments[0].name}"
            self.title = title[:36] or self.title


class ConversationStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or app_data_dir()
        self.conversations_dir = self.data_dir / "conversations"
        self.attachments_dir = self.data_dir / "attachments"
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        self.attachments_dir.mkdir(parents=True, exist_ok=True)

    def list_conversations(self) -> list[Conversation]:
        items: list[Conversation] = []
        for path in self.conversations_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                items.append(Conversation.from_dict(data))
            except (OSError, json.JSONDecodeError):
                continue
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items

    def load(self, conversation_id: str) -> Conversation | None:
        path = self.conversations_dir / f"{conversation_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return Conversation.from_dict(data)

    def save(self, conversation: Conversation) -> None:
        self.conversations_dir.mkdir(parents=True, exist_ok=True)
        path = self.conversations_dir / f"{conversation.id}.json"
        path.write_text(
            json.dumps(conversation.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def delete(self, conversation_id: str) -> None:
        path = self.conversations_dir / f"{conversation_id}.json"
        if path.exists():
            path.unlink()

    def copy_attachment(self, source: Path, conversation_id: str) -> Attachment:
        target_dir = self.attachments_dir / conversation_id
        target_dir.mkdir(parents=True, exist_ok=True)
        suffix = source.suffix
        target = target_dir / f"{uuid.uuid4().hex}{suffix}"
        shutil.copy2(source, target)
        attachment = Attachment.from_path(target)
        attachment.name = source.name
        return attachment

    def save_image_attachment(
        self, image: Image.Image, conversation_id: str, name: str | None = None
    ) -> Attachment:
        target_dir = self.attachments_dir / conversation_id
        target_dir.mkdir(parents=True, exist_ok=True)
        file_name = name or f"clipboard-{datetime.now().strftime('%Y%m%d-%H%M%S')}.png"
        target = target_dir / file_name
        if target.exists():
            target = target_dir / f"{target.stem}-{uuid.uuid4().hex[:8]}{target.suffix}"
        image.save(target, format="PNG")
        return Attachment.from_path(target, kind="clipboard-image")
