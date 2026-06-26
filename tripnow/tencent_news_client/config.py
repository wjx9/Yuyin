"""腾讯新闻配置：从环境变量读取 API Key 与 CLI 命令。"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from .client import TencentNewsCli
from .errors import TencentNewsError
from .service import NewsService

_DEFAULT_CLI = "tencent-news-cli"
_DEFAULT_ADCODE = "440300"  # 深圳
# 官方原生二进制名（Windows 带 .exe）；把它丢到程序旁边即可被自动发现。
_BINARY_NAMES = ("tencent-news-cli.exe", "tencent-news-cli")


def _bundle_dirs() -> list[str]:
    """优先在"程序旁边"找官方二进制，避免依赖 PATH。

    - PyInstaller 打包后：onefile 解包目录(_MEIPASS) + exe 所在目录；
    - 源码运行：仓库根目录（本包的上一级）。
    """
    if getattr(sys, "frozen", False):
        dirs = [getattr(sys, "_MEIPASS", ""), os.path.dirname(sys.executable)]
        return [d for d in dirs if d]
    return [os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]


def _resolve_cli_command() -> str:
    """决定调哪个 CLI：显式 env 覆盖 > 程序旁边的二进制 > PATH 上的官方安装。"""
    explicit = os.getenv("TENCENT_NEWS_CLI", "").strip()
    if explicit:
        return explicit
    for d in _bundle_dirs():
        for name in _BINARY_NAMES:
            path = os.path.join(d, name)
            if os.path.isfile(path):
                return path
    return _DEFAULT_CLI


@dataclass
class TencentNewsSettings:
    api_key: str
    cli_command: str = _DEFAULT_CLI
    default_adcode: str = _DEFAULT_ADCODE

    @classmethod
    def from_env(cls) -> "TencentNewsSettings":
        api_key = os.getenv("TENCENT_NEWS_API_KEY", "").strip()
        if not api_key:
            raise TencentNewsError("缺少 TENCENT_NEWS_API_KEY 环境变量")
        return cls(
            api_key=api_key,
            cli_command=_resolve_cli_command(),
            default_adcode=(os.getenv("TENCENT_NEWS_DEFAULT_ADCODE", "").strip() or _DEFAULT_ADCODE),
        )


def build_service(settings: TencentNewsSettings) -> NewsService:
    cli = TencentNewsCli(settings.api_key, command=settings.cli_command)
    return NewsService(cli, default_adcode=settings.default_adcode)
