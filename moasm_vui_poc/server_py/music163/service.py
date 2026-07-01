"""网易云音乐业务层：把 ncm-cli 子命令包成点歌/控制方法。

step 1（纯 PC）核心链路：search all → 取首个可播放(visible)单曲 → play --song。
播放控制（暂停/继续/停止/上一首/下一首/音量）直接映射到对应子命令。

子命令与参数名已用本机 `ncm-cli <cmd> --help` 校验（0.1.6）。CLI 升级若有变，
改这一层即可，client / 上层均不受影响。
"""

from __future__ import annotations

from .client import NcmCli
from .errors import Music163Error
from .models import Song, parse_songs


class MusicService:
    def __init__(self, cli: NcmCli):
        self._cli = cli

    # ---------- 登录态 ----------

    def is_logged_in(self) -> bool:
        """login --check：未登录时 CLI 返回 {success:false}，故不抛错、只读 success。"""
        data = self._cli.run("login", ["--check"], raise_on_failure=False)
        return bool(isinstance(data, dict) and data.get("success"))

    # ---------- 搜索 / 播放 ----------

    def search(self, keyword: str, *, user_input: str | None = None) -> list[Song]:
        # search 需先登录；all=综合搜索。--userInput 传完整原话作为意图上下文（官方建议）。
        args = ["all", "--keyword", keyword]
        if user_input:
            args += ["--userInput", user_input]
        return parse_songs(self._cli.run("search", args))

    def play_song(self, song: Song) -> None:
        if not (song.encrypted_id and song.original_id):
            raise Music163Error(f"歌曲缺少可播放 ID：{song.label()}")
        self._cli.run(
            "play",
            ["--song", "--encrypted-id", song.encrypted_id, "--original-id", song.original_id],
        )

    def play_first(self, keyword: str, *, user_input: str | None = None) -> Song:
        """搜索并播放首个可播放(visible)单曲，返回被播放的 Song。无结果/全不可播放则抛错。"""
        songs = self.search(keyword, user_input=user_input)
        if not songs:
            raise Music163Error(f"没搜到“{keyword}”相关的歌")
        playable = next((s for s in songs if s.visible), None)
        if playable is None:
            raise Music163Error(f"“{keyword}”的结果当前都不可播放（多为版权受限或需会员）")
        self.play_song(playable)
        return playable

    # ---------- 播放控制 ----------

    def pause(self) -> None:
        self._cli.run("pause")

    def resume(self) -> None:
        self._cli.run("resume")

    def stop(self) -> None:
        self._cli.run("stop")

    def next(self) -> None:
        self._cli.run("next")

    def prev(self) -> None:
        self._cli.run("prev")

    def set_volume(self, level: int) -> None:
        # volume <0-100>，作为位置参数。
        self._cli.run("volume", [str(max(0, min(100, level)))])
