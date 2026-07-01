"""网易云音乐 ncm-cli 客户端：薄封装官方 @music163/ncm-cli（subprocess + JSON）。

为什么包 CLI？
    网易云音乐技能的官方执行面是本地 CLI（@music163/ncm-cli）：登录(OAuth)、
    搜歌、点歌、播放控制都由它在本机完成（在线播放依赖本地 mpv，仅 mac/win）。
    没有公开的直连 REST，故与腾讯新闻一致——把 CLI 当"外部能力的传输层"，
    subprocess 调它、收 stdout（统一加 `--output json` 拿结构化结果）。

凭证与登录（实测要点，ncm-cli 0.1.6）：
    - appId/privateKey 由 CLI 自己持久化（`config set`），**不读进程 env**。故本封装
      首次调用前自动 `config set appId/privateKey`（幂等，每个进程一次），
      与腾讯封装的 apikey-set 思路一致，用的是官方命令。
    - 真正的"登录"是 OAuth 扫码/链接，交互式、无法自动化。本封装只用
      `login --check` 探测登录态；未登录时由上层提示用户去服务端机器
      执行 `ncm-cli login`。
    - 退出码不可靠：逻辑失败（如未登录）时进程仍可能返回 0，故一律以 JSON 里的
      `success` 字段为准。

Windows 注意：
    npm 全局装出来的入口是 `ncm-cli.cmd` 垫片，Python subprocess(不走 shell)无法
    直接执行 .cmd。故在 Windows 上默认改用 `node <dist/index.js>` 拉起（见
    config._resolve_cli_command）。command 用 shlex 切词，posix 随平台切换：
    Windows 用 posix=False 以保留反斜杠路径。
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from typing import Any

from .errors import Music163Error

_TIMEOUT = 60  # 秒


class NcmCli:
    def __init__(self, app_id: str, private_key: str, command: str = "ncm-cli"):
        self._app_id = app_id
        self._private_key = private_key
        self._base_argv = shlex.split(command, posix=(os.name != "nt"))
        self._configured = False

    def run(self, subcommand: str, args: list[str] | None = None, *, raise_on_failure: bool = True) -> Any:
        """执行 `<cli> <subcommand> <args...> --output json`，返回解析后的 JSON 信封。

        信封有两种成功标记：`success==true`（login/state 等）或 `code==200`（search 等）。
        raise_on_failure=True 时，判定为失败就抛 Music163Error。探测类命令
        （login --check / state）用 raise_on_failure=False 自行读字段。
        """
        self._ensure_credentials()
        data = self._invoke(subcommand, args or [])
        if raise_on_failure and not _envelope_ok(data):
            raise Music163Error(_envelope_msg(data))
        return data

    def _ensure_credentials(self) -> None:
        """首次调用前用官方 `config set` 持久化 appId/privateKey（CLI 只认这份持久化配置）。"""
        if self._configured:
            return
        self._configured = True  # 先置位，避免 config set 内部再次触发递归
        self._invoke("config", ["set", "appId", self._app_id], parse=False)
        self._invoke("config", ["set", "privateKey", self._private_key], parse=False)

    def _invoke(self, subcommand: str, args: list[str], *, parse: bool = True) -> Any:
        argv = [*self._base_argv, subcommand, *args, "--output", "json"]
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=_TIMEOUT,
            )
        except FileNotFoundError as e:
            raise Music163Error(
                f"未找到网易云音乐 CLI（{self._base_argv[0]!r}）。请先 `npm i -g @music163/ncm-cli`，"
                "或用 MUSIC163_CLI 指定可执行；Windows 建议设为 'node <安装路径>/dist/index.js'。"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise Music163Error(f"网易云音乐 CLI 执行超时（>{_TIMEOUT}s）") from e

        if not parse:
            return None

        stdout = (proc.stdout or "").strip()
        if not stdout:
            # 动作类命令（play/pause/resume/next/...）成功时通常无任何输出；rc=0 即视为成功。
            if proc.returncode == 0:
                return {}
            detail = (proc.stderr or "").strip()[:300]
            raise Music163Error(f"网易云音乐 CLI 失败（rc={proc.returncode}）：{detail}")
        try:
            return json.loads(stdout)
        except ValueError as e:
            raise Music163Error(f"网易云音乐 CLI 输出非 JSON：{stdout[:300]}") from e


def _envelope_ok(data: Any) -> bool:
    """信封是否成功：优先看 success，其次 code==200；都没有则视为成功（动作类空信封）。"""
    if not isinstance(data, dict):
        return True
    if "success" in data:
        return bool(data["success"])
    if "code" in data:
        return data.get("code") == 200
    return True


def _envelope_msg(data: Any) -> str:
    if isinstance(data, dict):
        return str(data.get("message") or data.get("subCode") or f"CLI 调用失败({data.get('code')})")
    return "CLI 调用失败"
