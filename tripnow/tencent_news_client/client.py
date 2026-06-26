"""腾讯新闻 CLI 客户端：包一层官方 tencent-news-cli。

为什么是包 CLI 而不是直连 REST？
    腾讯新闻能力开放（news.qq.com/exchange?scene=appkey）的官方接入面是
    "Skill / CLI"：装好 tencent-news-cli、配置 API Key 后，用
        tencent-news-cli hot
        tencent-news-cli weather --adcode 440300
        tencent-news-cli jiaozhen --query=<查询内容>
    这种子命令发起。它没有公开的直连 HTTP 接口文档，所以这里把 CLI 当作
    "外部能力的传输层"，subprocess 调它、收 stdout。这与高德 A2A、快递100
    在我们系统里的地位一致：一个被薄封装的外部 provider。

API Key 注入（实测结论）：
    该 CLI **不读进程环境变量**，只认官方 `apikey-set` 持久化下来的配置
    （Windows 写入 HKCU\\Environment 用户级环境变量）。实测把 key 通过
    进程 env 传入无效，必须先跑一次 `apikey-set <key>`。因此本封装在首次
    调用前自动执行官方 `apikey-set`（幂等，每个进程只做一次），用的是官方
    命令、不是黑客手段。代价：会在用户态持久化一个 TENCENT_NEWS_APIKEY；
    这正是该工具被设计的配置方式。
"""

from __future__ import annotations

import os
import shlex
import subprocess

from .errors import TencentNewsError

_TIMEOUT = 60  # 秒


class TencentNewsCli:
    def __init__(self, api_key: str, command: str = "tencent-news-cli"):
        self._api_key = api_key
        # command 允许带启动器，如 "node C:\\path\\cli.js"，用 shlex 切成 argv 前缀，
        # 子命令与参数再追加在后面。posix 随平台切换：Windows 上 posix=False 才能
        # 正确保留反斜杠路径；mac/linux 用 posix=True 做标准 shell 切词。
        self._base_argv = shlex.split(command, posix=(os.name != "nt"))
        self._configured = False

    def run(self, subcommand: str, args: list[str]) -> str:
        """执行 `<command> <subcommand> <args...>`，返回 stdout。"""
        self._ensure_apikey()
        return self._invoke(subcommand, args)

    def _ensure_apikey(self) -> None:
        """首次调用前用官方 apikey-set 持久化 key（CLI 只认这份持久化配置）。"""
        if self._configured:
            return
        self._invoke("apikey-set", [self._api_key])
        self._configured = True

    def _invoke(self, subcommand: str, args: list[str]) -> str:
        argv = [*self._base_argv, subcommand, *args]
        try:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=_TIMEOUT,
            )
        except FileNotFoundError as e:
            raise TencentNewsError(
                f"未找到腾讯新闻 CLI（{self._base_argv[0]!r}）。"
                "请先安装 tencent-news-cli，或用 TENCENT_NEWS_CLI 指定可执行路径。"
            ) from e
        except subprocess.TimeoutExpired as e:
            raise TencentNewsError(f"腾讯新闻 CLI 执行超时（>{_TIMEOUT}s）") from e

        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()[:300]
            raise TencentNewsError(f"腾讯新闻 CLI 返回非零({proc.returncode})：{detail}")
        return proc.stdout or ""
