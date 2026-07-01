"""网易云音乐领域模型。

ncm-cli 默认 `--output json`，外层信封统一是：
    {"success": true,  ...data}        # 成功
    {"success": false, "message": ...} # 逻辑失败（注意：进程退出码仍可能是 0）

搜索(search all)结果里的单曲对象（由 ncm-cli 0.1.6 内部映射后）含这些字段：
    encryptedId  资源加密 ID（32 位 hex，用于 API 请求 / 播放）
    originalId   原始 ID（明文数字，用于唤起客户端）
    name         歌名
    artists      歌手（数组：字符串或 {name} 对象）
    visible      是否可播放（false 多为版权受限/需会员）
字段名取自 ncm-cli dist 内的映射；若 CLI 升级字段有变，只改本层。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Song:
    name: str
    artists: list[str]
    encrypted_id: str
    original_id: str
    visible: bool = True

    @property
    def artist_str(self) -> str:
        return " / ".join(self.artists) if self.artists else "未知歌手"

    def label(self) -> str:
        return f"{self.name} - {self.artist_str}"


def parse_songs(payload: Any) -> list[Song]:
    """从 search 的 JSON 信封里递归捞出"像单曲"的对象，构造 Song 列表（保持出现顺序）。

    不写死外层 key（songs / data.songs / result.songs …），只认对象是否同时带
    (encryptedId 或 originalId) + name —— 对 CLI 输出结构的小幅变化更稳。
    """
    out: list[Song] = []
    _collect(payload, out)
    return out


def _collect(node: Any, out: list[Song]) -> None:
    if isinstance(node, dict):
        if _looks_like_song(node):
            out.append(_to_song(node))
            return  # 命中即不再深入该对象，避免把嵌套字段误当成另一首
        for value in node.values():
            _collect(value, out)
    elif isinstance(node, list):
        for item in node:
            _collect(item, out)


def _looks_like_song(d: dict) -> bool:
    return ("encryptedId" in d or "originalId" in d) and "name" in d


def _to_song(d: dict) -> Song:
    return Song(
        name=str(d.get("name") or "").strip() or "未知歌曲",
        artists=_artist_names(d.get("artists")),
        encrypted_id=str(d.get("encryptedId") or d.get("id") or "").strip(),
        original_id=str(d.get("originalId") or "").strip(),
        visible=bool(d.get("visible", True)),
    )


def _artist_names(raw: Any) -> list[str]:
    """artists 可能是 ['周杰伦', ...] 或 [{'name': '周杰伦'}, ...]，都收。"""
    if not isinstance(raw, list):
        return []
    names: list[str] = []
    for a in raw:
        if isinstance(a, str) and a.strip():
            names.append(a.strip())
        elif isinstance(a, dict):
            n = a.get("name") or a.get("artistName")
            if n:
                names.append(str(n).strip())
    return names
