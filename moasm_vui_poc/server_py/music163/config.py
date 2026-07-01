"""网易云音乐配置：从环境变量读取 appId/privateKey，并解析 CLI 调用方式。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .client import NcmCli
from .errors import Music163Error
from .service import MusicService

_DEFAULT_CLI = "ncm-cli"


def _resolve_cli_command() -> str:
    """决定怎么拉起 ncm-cli：

    显式 MUSIC163_CLI > Windows 下用 `node <dist/index.js>`（绕开 .cmd 垫片）> PATH 上的 ncm-cli。

    Windows 上 npm 全局入口是 ncm-cli.cmd，Python subprocess(不走 shell)执行不了，
    故定位 npm 全局里的 dist/index.js 用 node 直跑。注意：用 shlex(posix=False) 切词，
    路径含空格会被切坏——这种情况请显式设 MUSIC163_CLI。
    """
    explicit = os.getenv("MUSIC163_CLI", "").strip()
    if explicit:
        return explicit
    if os.name == "nt":
        appdata = os.getenv("APPDATA", "")
        entry = os.path.join(
            appdata, "npm", "node_modules", "@music163", "ncm-cli", "dist", "index.js"
        )
        if appdata and os.path.isfile(entry):
            return f"node {entry}"
    return _DEFAULT_CLI


@dataclass
class Music163Settings:
    app_id: str
    private_key: str
    cli_command: str = _DEFAULT_CLI

    @classmethod
    def from_env(cls) -> "Music163Settings":
        app_id = os.getenv("MUSIC163_APPID", "").strip()
        private_key = os.getenv("MUSIC163_PRIVATE_KEY", "").strip()
        if not (app_id and private_key):
            raise Music163Error("缺少 MUSIC163_APPID / MUSIC163_PRIVATE_KEY 环境变量")
        return cls(app_id=app_id, private_key=private_key, cli_command=_resolve_cli_command())


def build_service(settings: Music163Settings) -> MusicService:
    cli = NcmCli(settings.app_id, settings.private_key, command=settings.cli_command)
    return MusicService(cli)
