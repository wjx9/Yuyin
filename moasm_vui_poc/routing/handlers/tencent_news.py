"""腾讯新闻的四个 Handler：热点新闻 / 主题搜索 / 天气预报 / 事实查证。

为什么按子命令拆意图？
    腾讯新闻 CLI 的子命令**参数形态完全不同**：hot（全国热点榜，无地区参数）、
    search（按关键词搜，可搜地区/主题/人物）、weather（要 adcode）、
    jiaozhen（要 --query）。让 Gemini 分类器直接在它们之间选择，比在单一
    handler 里二次分流更稳——契合本项目"一能力一 Handler、新增能力零改
    分类器"的设计。四者共享同一个 NewsService（同一份 CLI 配置）。

    hot vs search 是关键一分：hot 只有全国榜、不认地区；"深圳的新闻"这类
    指定地区/主题的，必须走 search，否则地区信息会被丢弃（两句返回相同）。
"""

from __future__ import annotations

import re

from tencent_news_client.errors import TencentNewsError
from tencent_news_client.service import NewsService

from ..handler import Handler, RouteContext, RouteResult

# 从自然语言里抠出"要几条"：top5 / 5条 / 前3个 / 来10条 等（只认阿拉伯数字）。
# 匹配完整数字串再做范围过滤：超出 1..50 的（如年份 2026、夸张的 100）一律忽略。
_COUNT_RE = re.compile(r"(?:top|前|来|要)?\s*(\d+)\s*(?:条|个|则|news)?", re.IGNORECASE)


def _extract_count(query: str) -> int | None:
    m = _COUNT_RE.search(query)
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 50 else None


def _search_keyword(query: str) -> str:
    """把 query 去掉计数噪声（top5/5条）作为搜索词；清空了就退回原句。"""
    kw = _COUNT_RE.sub("", query).strip()
    return kw or query


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
    description = "查询当前热点新闻/今日头条：有什么大新闻、最近发生了什么"

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
        "搜索**特定**地区/城市/主题/人物/事件的**新闻报道**，"
        "如'深圳的新闻'、'关于苹果公司的新闻'、'高考相关新闻'；"
        "与全国热点榜（tencent_hot_news）区分：点名了具体对象的新闻就走这里。"
        "注意：仅限'新闻/报道/动态/发生了什么'；若用户要的是某个实时数值"
        "（股价、汇率、币价、油价、商品价格等），不要走这里，交给闲聊联网查询"
    )

    def __init__(self, service: NewsService):
        self._service = service

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        keyword = _search_keyword(query)
        limit = _extract_count(query)
        try:
            result = self._service.search(keyword, limit=limit)
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
