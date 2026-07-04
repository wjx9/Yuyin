"""腾讯新闻的四个 Handler：热点新闻 / 新闻搜索 / 天气预报 / 事实查证。

为什么按子命令拆意图？
    腾讯新闻 CLI 的子命令**参数形态完全不同**：hot（全国热点榜，无地区参数）、
    search（按关键词搜，可搜地区/主题/人物）、weather（要 adcode）、
    jiaozhen（要 --query）。让 Gemini 分类器直接在它们之间选择，比在单一
    handler 里二次分流更稳——契合本项目"一能力一 Handler、新增能力零改
    分类器"的设计。四者共享同一个 NewsService（同一份 CLI 配置）。

    hot vs search 是关键一分：hot 只有全国综合榜、不认任何限定词；地区新闻
    （"深圳的新闻"、"美国新闻"）、分类新闻（"科技新闻"、"体育新闻"）、
    主题/人物/事件，都必须走 search，否则限定信息会被丢弃（返回同一份榜单）。

search 的检索词质量决定结果质量：
    CLI 的 search 是全文关键词检索（无频道/分类参数，实测确认），把"我想看
    科技新闻"整句喂进去会命中大量字面噪声。因此 search handler 先用
    GeminiNewsQueryParser 做槽位抽取（检索词 + 条数），LLM 不可用时退回
    确定性正则清洗。与高德 GeminiMapQueryParser 同一模式：解析器放 routing
    层，tencent_news_client 不反向依赖 Gemini。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from tencent_news_client.errors import TencentNewsError
from tencent_news_client.service import NewsService

from ..gemini import GeminiClient, GeminiError, loads_json_loose
from ..handler import Handler, RouteContext, RouteResult

_log = logging.getLogger(__name__)

_MAX_COUNT = 50

# 从自然语言里抠出"要几条"。只认带明确计数标记的表达：top5 / 前3 / 来10条 / 5条；
# 裸数字（"iPhone 17"、"9月3日"）不算条数，避免把关键词里的数字误当 limit。
_COUNT_RE = re.compile(
    r"(?:top|前|来|要)\s*(\d+)\s*(?:条|个|则|篇|news)?|(\d+)\s*(?:条|个|则|篇|news)",
    re.IGNORECASE,
)


def _extract_count(query: str) -> int | None:
    for m in _COUNT_RE.finditer(query):
        n = int(m.group(1) or m.group(2))
        if 1 <= n <= _MAX_COUNT:
            return n
    return None


def _strip_count(query: str) -> str:
    """从 query 里剥掉计数表达；超范围的数字（年份等）原样保留。"""

    def repl(m: re.Match) -> str:
        n = int(m.group(1) or m.group(2))
        return "" if 1 <= n <= _MAX_COUNT else m.group(0)

    return _COUNT_RE.sub(repl, query)


# LLM 不可用时的确定性清洗：去请求类前缀、去"…的新闻"类后缀，留下检索对象本身。
_LEAD_RE = re.compile(
    r"^(?:请|麻烦|帮我|给我|我想|我要|想|要|来点|来|看看|看下|看点|看|听听|听|"
    r"查查|查下|查|搜搜|搜下|搜|播报|说说|讲讲|了解|有什么|有没有|有啥|关于)+"
)
_TAIL_RE = re.compile(
    r"(?:的|最新|今天|今日|相关|方面)*(?:新闻|报道|资讯|消息|动态|头条)+(?:吧|呗|呢|啊|吗)?$"
)


def _search_keyword(query: str) -> str:
    """正则清洗出检索词：去计数、去前后缀话术；清空了就退回原句。"""
    kw = _strip_count(query).strip()
    kw = _LEAD_RE.sub("", kw)
    kw = _TAIL_RE.sub("", kw).strip()
    return kw or query


@dataclass(frozen=True)
class NewsQuery:
    """一次新闻搜索的槽位：检索词 + 可选条数。"""

    keyword: str
    limit: int | None = None


def _fallback_query(query: str) -> NewsQuery:
    return NewsQuery(keyword=_search_keyword(query), limit=_extract_count(query))


_PARSER_SYSTEM = """你是腾讯新闻搜索的查询解析器。用户想看某类新闻，把诉求拆成 JSON，字段：
  keyword: 喂给新闻搜索引擎的检索词，必须简短：
    - 地区新闻取地区名："看看深圳的新闻"→"深圳"，"来点美国新闻"→"美国"
    - 分类新闻取品类核心词："我想看科技新闻"→"科技"，"有什么财经新闻"→"财经"
    - 主题/人物/事件取对象本身："关于苹果公司的新闻"→"苹果公司"
    - 地区+分类同时出现则都保留："美国的科技新闻"→"美国 科技"
    - 不要带"新闻/报道/我想看/来点/top5"这类修饰词。
  limit: 用户要求的条数（整数）；没提就是 null。
只输出一个 JSON 对象，不要解释，不要代码块。"""


class GeminiNewsQueryParser:
    """用 Gemini 把"想看什么新闻"拆成 NewsQuery；失败时退回正则清洗。"""

    def __init__(self, gemini: GeminiClient):
        self._gemini = gemini

    def parse(self, query: str) -> NewsQuery:
        try:
            raw = self._gemini.generate(query, system=_PARSER_SYSTEM, temperature=0.0)
        except GeminiError as e:
            _log.warning("新闻查询解析失败，退回正则清洗: %s", e)
            return _fallback_query(query)
        data = loads_json_loose(raw)
        if not isinstance(data, dict):
            _log.warning("新闻查询解析输出非 JSON(%r)，退回正则清洗", raw[:80])
            return _fallback_query(query)
        keyword = str(data.get("keyword") or "").strip() or _search_keyword(query)
        limit = data.get("limit")
        if not (isinstance(limit, int) and 1 <= limit <= _MAX_COUNT):
            limit = _extract_count(query)  # LLM 没给/给错时用正则兜底
        _log.debug("新闻查询解析: keyword=%r limit=%r", keyword, limit)
        return NewsQuery(keyword=keyword, limit=limit)


# weather 只认 --adcode（无城市名参数），故自然语言城市名要先转 adcode。
# 这里只覆盖直辖市+省会+主要城市；命中不到就走 service 的默认/当前定位。
# 真实产品应接入完整行政区划表或从 GPS 反查。
_CITY_ADCODE: dict[str, str] = {
    "北京": "110000", "上海": "310000", "天津": "120000", "重庆": "500000",
    "广州": "440100", "深圳": "440300", "珠海": "440400", "佛山": "440600",
    "东莞": "441900", "杭州": "330100", "宁波": "330200", "南京": "320100",
    "苏州": "320500", "无锡": "320200", "武汉": "420100", "成都": "510100",
    "西安": "610100", "长沙": "430100", "郑州": "410100", "济南": "370100",
    "青岛": "370200", "沈阳": "210100", "大连": "210200", "哈尔滨": "230100",
    "长春": "220100", "石家庄": "130100", "太原": "140100", "合肥": "340100",
    "福州": "350100", "厦门": "350200", "南昌": "360100", "昆明": "530100",
    "贵阳": "520100", "南宁": "450100", "海口": "460100", "兰州": "620100",
    "西宁": "630100", "银川": "640100", "乌鲁木齐": "650100", "呼和浩特": "150100",
    "拉萨": "540100",
}


def _extract_adcode(query: str) -> str | None:
    """从 query 里识别城市名 → adcode；识别不到返回 None（交给默认/当前定位）。"""
    for city, adcode in _CITY_ADCODE.items():
        if city in query:
            return adcode
    return None


class TencentHotNewsHandler(Handler):
    intent = "tencent_hot_news"
    description = (
        "查询全国综合热点新闻榜/今日头条：'有什么大新闻'、'最近发生了什么'这类"
        "**没有点名任何地区/分类/主题**的泛问；点名了具体对象的新闻走 tencent_news_search"
    )

    def __init__(self, service: NewsService):
        self._service = service

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        try:
            result = self._service.hot(limit=_extract_count(query))
        except TencentNewsError as e:
            return RouteResult(text=f"热点新闻获取失败：{e}", intent=self.intent)
        return RouteResult(text=result.text, data=result, intent=self.intent)


class TencentNewsSearchHandler(Handler):
    intent = "tencent_news_search"
    description = (
        "查询**指定对象**的新闻：地区新闻（'深圳的新闻'、'美国新闻'）、"
        "分类新闻（'科技新闻'、'体育新闻'、'财经新闻'、'国际新闻'）、"
        "主题/人物/事件报道（'关于苹果公司的新闻'、'高考相关新闻'）；"
        "与全国热点榜（tencent_hot_news）区分：点名了地区/分类/主题的新闻就走这里。"
        "注意：仅限'新闻/报道/动态/发生了什么'；若用户要的是某个实时数值"
        "（股价、汇率、币价、油价、商品价格等），不要走这里，交给闲聊联网查询"
    )

    def __init__(self, service: NewsService, parser: GeminiNewsQueryParser | None = None):
        self._service = service
        self._parser = parser  # None 时用正则清洗（测试/降级路径）

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        q = self._parser.parse(query) if self._parser else _fallback_query(query)
        _log.info("新闻搜索: %r -> keyword=%r limit=%r", query, q.keyword, q.limit)
        try:
            result = self._service.search(q.keyword, limit=q.limit)
        except TencentNewsError as e:
            return RouteResult(text=f"新闻搜索失败：{e}", intent=self.intent)
        return RouteResult(text=result.text, data=result, intent=self.intent)


class TencentWeatherHandler(Handler):
    intent = "tencent_weather"
    description = "查询天气预报：今天/未来几天某地是否下雨、气温、风力、空气质量、预警"

    def __init__(self, service: NewsService):
        self._service = service

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        # 识别 query 里的城市 → adcode；识别不到则 None，由 service 用默认兜底。
        try:
            result = self._service.weather(adcode=_extract_adcode(query))
        except TencentNewsError as e:
            return RouteResult(text=f"天气查询失败：{e}", intent=self.intent)
        return RouteResult(text=result.text, data=result, intent=self.intent)


class TencentFactCheckHandler(Handler):
    intent = "tencent_fact_check"
    description = (
        "流言/说法核查：对一条**明确的传闻或说法**判断真假"
        "（多为健康、生活、社会类，如'吃洋葱能降血压是真的吗'、'XX谣言是否属实'）；"
        "不适用于天气/事实问答/常识陈述这类没有'待核查说法'的输入"
    )

    def __init__(self, service: NewsService):
        self._service = service

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        try:
            result = self._service.fact_check(query)
        except TencentNewsError as e:
            return RouteResult(text=f"事实查证失败：{e}", intent=self.intent)
        return RouteResult(text=result.text, data=result, intent=self.intent)
