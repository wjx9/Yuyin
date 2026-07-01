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

    @property
    def deeplink(self) -> str:
        """网易云音乐 app 的 URL scheme，用 originalId（明文数字）。客户端用它拉起 app。"""
        return f"orpheus://song/{self.original_id}" if self.original_id else ""

    @property
    def web_url(self) -> str:
        """网页兜底（app 未安装时）。"""
        return f"https://music.163.com/#/song?id={self.original_id}" if self.original_id else ""

    def to_client_dict(self) -> dict:
        """回传给客户端（CS 模式）的可序列化结构：含 app 深链与网页兜底，供端侧拉起播放。"""
        return {
            "kind": "music",
            "name": self.name,
            "artist": self.artist_str,
            "originalId": self.original_id,
            "encryptedId": self.encrypted_id,
            "deeplink": self.deeplink,
            "webUrl": self.web_url,
        }


def parse_songs(payload: Any) -> list[Song]:
    """从 search 的 JSON 信封里取出歌曲列表，构造 Song（保持出现顺序）。

    实测 ncm-cli 0.1.6（已登录）：
      - `search song` → {code:200, data:{records:[...songs]}}
      - `search all`  → {code:200, data:{songs:[...], artists:[...], albums:[...], ...}}
    注意 `search all` 同时含歌手/专辑/歌单（它们也带 id/name，但**没有 duration**），
    故只取 data.records / data.songs，且用 duration 把"真歌曲"和歌手/专辑区分开——
    避免拿歌手 id 当歌去 play。
    """
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        for key in ("records", "songs"):
            lst = data.get(key)
            if isinstance(lst, list):
                return [_to_song(s) for s in lst if _looks_like_song(s)]
    # 兜底：结构有变时全局递归捞（同样要求 duration，排除歌手/专辑/歌单）
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


def _looks_like_song(d: Any) -> bool:
    # 歌曲对象特有 duration（毫秒）；歌手/专辑/歌单条目没有，借此排除。
    return (
        isinstance(d, dict)
        and "name" in d
        and ("id" in d or "encryptedId" in d)
        and "duration" in d
    )


def _to_song(d: dict) -> Song:
    # 单曲对象里 id=加密ID(32hex)、originalId=明文数字；少数旧结构用 encryptedId。
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
