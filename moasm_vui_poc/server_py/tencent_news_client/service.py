"""腾讯新闻业务层：三个能力对应 CLI 的三个子命令。

    hot          —— 热点新闻（无参数，--limit 可选）
    weather      —— 天气预报（--adcode 行政区划码）
    jiaozhen     —— 较真查证/事实核查（--query=<查询内容>）

子命令名与参数名已用本机 `tencent-news-cli --help` 校验。
若你的 CLI 版本不同，改这一层即可，client/上层均不受影响。
"""

from __future__ import annotations

from .client import TencentNewsCli
from .models import NewsResult


class NewsService:
    def __init__(self, cli: TencentNewsCli, default_adcode: str = "440300"):
        self._cli = cli
        # 天气需要行政区划码；自然语言里通常没有，无显式 adcode 时用默认（深圳 440300）。
        self._default_adcode = default_adcode

    def hot(self, *, limit: int | None = None) -> NewsResult:
        args = ["--limit", str(limit)] if limit else []
        return NewsResult.from_stdout(self._cli.run("hot", args))

    def weather(self, adcode: str | None = None) -> NewsResult:
        code = adcode or self._default_adcode
        return NewsResult.from_stdout(self._cli.run("weather", ["--adcode", code]))

    def search(self, query: str, *, limit: int | None = None) -> NewsResult:
        args = [query] + (["--limit", str(limit)] if limit else [])
        return NewsResult.from_stdout(self._cli.run("search", args))

    def fact_check(self, query: str) -> NewsResult:
        # jiaozhen 用 --query=<内容> 形式传参（单参数选项）。
        return NewsResult.from_stdout(
            self._cli.run("jiaozhen", [f"--query={query}"])
        )
