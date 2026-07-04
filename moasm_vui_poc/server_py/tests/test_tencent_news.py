"""腾讯新闻 provider + 路由单测。

CLI 不在本环境，故用 fake subprocess.run 验证：argv 拼装、API Key 注入、
错误映射、以及三个 Handler 各自调对子命令。
"""

from __future__ import annotations

import subprocess

import pytest

from tencent_news_client.client import TencentNewsCli
from tencent_news_client.errors import TencentNewsError
from tencent_news_client.models import NewsResult
from tencent_news_client.service import NewsService

from routing.gemini import GeminiError
from routing.handler import RouteContext
from routing.handlers import (
    TencentFactCheckHandler,
    TencentHotNewsHandler,
    TencentNewsSearchHandler,
    TencentWeatherHandler,
)
from routing.handlers.tencent_news import (
    GeminiNewsQueryParser,
    NewsQuery,
    _extract_count,
    _search_keyword,
)


class FakeCompleted:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


class FakeRunner:
    """记录最近一次 subprocess.run 调用，并返回预设结果。"""

    def __init__(self, completed=None, raises=None):
        self._completed = completed or FakeCompleted(stdout="ok")
        self._raises = raises
        self.calls: list[dict] = []

    def __call__(self, argv, **kwargs):
        self.calls.append({"argv": argv, **kwargs})
        if self._raises:
            raise self._raises
        return self._completed


# ---------- client ----------

def test_run_sets_apikey_then_subcommand(monkeypatch):
    runner = FakeRunner(FakeCompleted(stdout="热点结果"))
    monkeypatch.setattr(subprocess, "run", runner)

    cli = TencentNewsCli("KEY-123", command="tencent-news-cli")
    out = cli.run("hot", [])

    assert out == "热点结果"
    # 首调先 apikey-set 持久化 key，再跑真正的子命令
    assert runner.calls[0]["argv"] == ["tencent-news-cli", "apikey-set", "KEY-123"]
    assert runner.calls[1]["argv"] == ["tencent-news-cli", "hot"]


def test_apikey_set_runs_once_per_instance(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(subprocess, "run", runner)

    cli = TencentNewsCli("K")
    cli.run("hot", [])
    cli.run("weather", ["--adcode", "440300"])

    apikey_calls = [c for c in runner.calls if c["argv"][1] == "apikey-set"]
    assert len(apikey_calls) == 1


def test_run_supports_launcher_command(monkeypatch):
    runner = FakeRunner()
    monkeypatch.setattr(subprocess, "run", runner)

    cli = TencentNewsCli("K", command="python run-cli.py")
    cli.run("weather", ["--adcode", "440300"])

    # calls[0] = apikey-set, calls[1] = 真正子命令
    assert runner.calls[1]["argv"] == [
        "python", "run-cli.py", "weather", "--adcode", "440300",
    ]


def test_run_missing_cli_raises(monkeypatch):
    runner = FakeRunner(raises=FileNotFoundError())
    monkeypatch.setattr(subprocess, "run", runner)

    cli = TencentNewsCli("K")
    with pytest.raises(TencentNewsError):
        cli.run("hot", [])


def test_run_timeout_raises(monkeypatch):
    runner = FakeRunner(raises=subprocess.TimeoutExpired(cmd="x", timeout=60))
    monkeypatch.setattr(subprocess, "run", runner)

    cli = TencentNewsCli("K")
    with pytest.raises(TencentNewsError):
        cli.run("hot", [])


def test_run_nonzero_returncode_raises(monkeypatch):
    runner = FakeRunner(FakeCompleted(stderr="boom", returncode=2))
    monkeypatch.setattr(subprocess, "run", runner)

    cli = TencentNewsCli("K")
    with pytest.raises(TencentNewsError) as ei:
        cli.run("hot", [])
    assert "boom" in str(ei.value)


# ---------- models ----------

def test_newsresult_parses_json_stdout():
    r = NewsResult.from_stdout('{"a": 1}')
    assert r.data == {"a": 1}
    assert r.text == '{"a": 1}'


def test_newsresult_keeps_plain_text():
    r = NewsResult.from_stdout("纯文本 markdown")
    assert r.data is None
    assert r.text == "纯文本 markdown"


# ---------- service / handlers ----------

class FakeCli:
    def __init__(self, stdout="结果"):
        self._stdout = stdout
        self.calls: list[tuple[str, list[str]]] = []

    def run(self, subcommand, args):
        self.calls.append((subcommand, args))
        return self._stdout


def _ctx():
    return RouteContext(union_id=None, location=None)


def test_hot_handler_calls_hot_no_count():
    cli = FakeCli("今日头条")
    h = TencentHotNewsHandler(NewsService(cli))
    res = h.handle("有什么大新闻", _ctx())
    assert cli.calls == [("hot", [])]
    assert res.intent == "tencent_hot_news"
    assert res.text == "今日头条"


def test_hot_handler_passes_count_as_limit():
    cli = FakeCli()
    h = TencentHotNewsHandler(NewsService(cli))
    h.handle("看下今天的新闻top5", _ctx())
    assert cli.calls == [("hot", ["--limit", "5"])]


@pytest.mark.parametrize(
    "query,expected",
    [
        ("看下今天的新闻top5", 5),
        ("来10条热点", 10),
        ("前3个新闻", 3),
        ("有什么大新闻", None),
        ("给我100条", None),  # 超出 1..50 上限
        ("iPhone 17 的新闻", None),  # 裸数字不是条数
        ("9月3日阅兵的新闻", None),
        ("2026年有什么大事", None),  # 年份不因 \d+ 部分匹配被误当条数
    ],
)
def test_extract_count(query, expected):
    assert _extract_count(query) == expected


@pytest.mark.parametrize(
    "query,expected",
    [
        ("看下深圳今天新闻top5", "深圳"),  # 地区新闻：去话术+计数
        ("我想看科技新闻", "科技"),  # 分类新闻
        ("来点美国新闻", "美国"),
        ("关于苹果公司的新闻", "苹果公司"),  # 主题新闻
        ("iPhone 17 的新闻", "iPhone 17"),  # 关键词里的数字不被剥掉
        ("5", "5"),  # 清空后退回原句，避免空关键词
    ],
)
def test_search_keyword_fallback_cleaning(query, expected):
    assert _search_keyword(query) == expected


def test_search_handler_without_parser_uses_regex_cleaning():
    cli = FakeCli()
    h = TencentNewsSearchHandler(NewsService(cli))
    h.handle("看下深圳今天新闻top5", _ctx())
    sub, args = cli.calls[0]
    assert sub == "search"
    assert args == ["深圳", "--limit", "5"]
    assert h.intent == "tencent_news_search"


def test_search_handler_uses_parser_result():
    cli = FakeCli()

    class StubParser:
        def parse(self, query):
            return NewsQuery(keyword="科技", limit=5)

    h = TencentNewsSearchHandler(NewsService(cli), parser=StubParser())
    h.handle("我想看科技新闻，来5条", _ctx())
    assert cli.calls == [("search", ["科技", "--limit", "5"])]


# ---------- GeminiNewsQueryParser ----------

class FakeGemini:
    def __init__(self, raw="", error=None):
        self.raw = raw
        self.error = error

    def generate(self, prompt, **kwargs):
        if self.error:
            raise self.error
        return self.raw


def test_parser_extracts_keyword_and_limit():
    p = GeminiNewsQueryParser(FakeGemini('{"keyword": "科技", "limit": 5}'))
    assert p.parse("我想看科技新闻top5") == NewsQuery("科技", 5)


def test_parser_tolerates_code_fence_and_null_limit():
    p = GeminiNewsQueryParser(FakeGemini('```json\n{"keyword": "深圳", "limit": null}\n```'))
    assert p.parse("看看深圳的新闻") == NewsQuery("深圳", None)


def test_parser_rechecks_bad_limit_with_regex():
    # LLM 给出超范围 limit → 用正则从原句重新抠条数
    p = GeminiNewsQueryParser(FakeGemini('{"keyword": "美国", "limit": 999}'))
    assert p.parse("来5条美国新闻") == NewsQuery("美国", 5)


def test_parser_falls_back_on_garbage_output():
    p = GeminiNewsQueryParser(FakeGemini("抱歉我不明白"))
    assert p.parse("我想看科技新闻") == NewsQuery("科技", None)


def test_parser_falls_back_on_gemini_error():
    p = GeminiNewsQueryParser(FakeGemini(error=GeminiError("down")))
    assert p.parse("来点美国新闻") == NewsQuery("美国", None)


def test_weather_handler_maps_city_to_adcode():
    cli = FakeCli()
    h = TencentWeatherHandler(NewsService(cli, default_adcode="440300"))
    h.handle("看下广州未来5天的天气", _ctx())
    assert cli.calls == [("weather", ["--adcode", "440100"])]  # 广州


def test_weather_handler_falls_back_to_default_when_no_city():
    cli = FakeCli()
    h = TencentWeatherHandler(NewsService(cli, default_adcode="440300"))
    h.handle("今天天气怎么样", _ctx())
    assert cli.calls == [("weather", ["--adcode", "440300"])]  # 默认深圳


def test_fact_check_handler_uses_jiaozhen():
    cli = FakeCli()
    h = TencentFactCheckHandler(NewsService(cli))
    h.handle("某传闻是真的吗", _ctx())
    assert cli.calls == [("jiaozhen", ["--query=某传闻是真的吗"])]


def test_handler_maps_error_to_text():
    class BoomCli:
        def run(self, *a, **k):
            raise TencentNewsError("CLI 挂了")

    h = TencentHotNewsHandler(NewsService(BoomCli()))
    res = h.handle("新闻", _ctx())
    assert "CLI 挂了" in res.text
    assert res.intent == "tencent_hot_news"
