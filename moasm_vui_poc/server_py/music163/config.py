"""网易云音乐配置：从环境变量读取 appId/privateKey，并解析 CLI 调用方式。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .client import NcmCli
from .errors import Music163Error
from .service import MusicService

_DEFAULT_CLI = "ncm-cli"


def _win_node_entry() -> str:
    """Windows: 定位 npm 全局里 @music163/ncm-cli 的 dist/index.js（用 node 直跑，绕开 .cmd 垫片）。"""
    appdata = os.getenv("APPDATA", "")
    if not appdata:
        return ""
    entry = os.path.join(
        appdata, "npm", "node_modules", "@music163", "ncm-cli", "dist", "index.js"
    )
    return entry if os.path.isfile(entry) else ""


def _resolve_cli_command() -> str:
    """决定怎么拉起 ncm-cli：

    显式 MUSIC163_CLI > Windows 下用 `node <dist/index.js>`（绕开 .cmd 垫片）> PATH 上的 ncm-cli。

    Windows 上 npm 全局入口是 `ncm-cli`(sh 垫片) / `ncm-cli.cmd`，Python subprocess(不走 shell)
    直接执行会 WinError 193/2。故：留空时自动定位 dist/index.js 用 node 跑；即便用户误填了
    这个 shim 路径，也识别出来改用 node（见下）。注意 shlex(posix=False) 切词，路径含空格
    需自己保证不被切坏（本仓库路径无空格）。
    """
    explicit = os.getenv("MUSIC163_CLI", "").strip()
    if explicit:
        # Windows 下用户可能误填 ncm-cli 的 shim 路径（无 .js、非 "node ..."）——subprocess 执行不了。
        # 识别到就改用 node 直跑 dist/index.js。
        low = explicit.lower()
        if os.name == "nt" and "index.js" not in low and not low.startswith("node "):
            if os.path.basename(explicit.replace("\\", "/")).lower().startswith("ncm-cli"):
                entry = _win_node_entry()
                if entry:
                    return f"node {entry}"
        return explicit
    if os.name == "nt":
        entry = _win_node_entry()
        if entry:
            return f"node {entry}"
    return _DEFAULT_CLI


@dataclass
class Music163Settings:
    app_id: str
    private_key: str
    cli_command: str = _DEFAULT_CLI
    mpv_path: str = ""  # 非空则注入子进程 PATH，供 ncm-cli 找到 mpv 播放

    @classmethod
    def from_env(cls) -> "Music163Settings":
        app_id = os.getenv("MUSIC163_APPID", "").strip()
        private_key = os.getenv("MUSIC163_PRIVATE_KEY", "").strip()
        if not (app_id and private_key):
            raise Music163Error("缺少 MUSIC163_APPID / MUSIC163_PRIVATE_KEY 环境变量")
        return cls(
            app_id=app_id,
            private_key=private_key,
            cli_command=_resolve_cli_command(),
            # mpv 路径统一放 .env（Windows 上 ncm-cli 需要，且常不在 PATH）；空=依赖系统 PATH
            mpv_path=os.getenv("MUSIC163_MPV", "").strip(),
        )


def build_service(settings: Music163Settings) -> MusicService:
    cli = NcmCli(
        settings.app_id, settings.private_key,
        command=settings.cli_command, mpv_path=settings.mpv_path,
    )
    return MusicService(cli)
