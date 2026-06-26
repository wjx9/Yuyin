"""高德 REST 业务实现：MapService 的默认后端。

直接调 Web 服务 REST（rest_client）做 POI 检索。REST 不像 A2A agent 能理解整句，
所以这里靠注入的 QueryParser 先把自然语言拆成 关键词 + 地点：
    1. 解析出 keywords / near(地点) / city；
    2. 若指定了 near（如"深圳万科云城"），先用关键字搜把它定位成坐标，再据此做周边搜；
    3. 否则退回显式 GPS 坐标 / 默认坐标。
不注入 parser 时用 NaiveQueryParser（整句当关键词、仅用默认坐标），即旧的弱行为。
"""

from __future__ import annotations

from .errors import AmapError
from .models import MapQuery, MapResult
from .parser import NaiveQueryParser, QueryParser
from .rest_client import AmapRestClient
from .service import MapService

_PAGE_SIZE = 10


class RestMapService(MapService):
    def __init__(
        self,
        client: AmapRestClient,
        default_location: str | None = None,
        parser: QueryParser | None = None,
    ):
        self._client = client
        self._default_location = default_location
        self._parser = parser or NaiveQueryParser()

    def ask(self, query: str, *, location: str | None = None) -> MapResult:
        mq = self._parser.parse(query)
        keywords = mq.keywords or query
        loc = self._resolve_location(mq, explicit=location)
        if loc:
            data = self._client.around(location=loc, keywords=keywords, offset=_PAGE_SIZE)
        else:
            data = self._client.text(keywords=keywords, city=mq.city or "", offset=_PAGE_SIZE)
        return MapResult.from_rest(data)

    def _resolve_location(self, mq: MapQuery, *, explicit: str | None) -> str | None:
        """定位优先级：查询里点名的地点 > 调用方显式坐标(GPS) > 默认坐标。"""
        if mq.near:
            located = self._locate(mq.near, city=mq.city or "")
            if located:
                return located
            # 地点没定位到，退回显式/默认坐标（仍按 keywords 搜，总比 0 结果强）
        return explicit or self._default_location

    def _locate(self, name: str, *, city: str) -> str | None:
        """把地名/地标定位成 "经度,纬度"：用关键字搜取第一个命中 POI 的坐标。

        比 geocode/geo 更稳——后者偏门牌地址，对"万科云城"这类地标常定位不到。
        """
        try:
            data = self._client.text(keywords=name, city=city, offset=1)
        except AmapError:
            return None
        for poi in data.get("pois") or []:
            loc = poi.get("location")
            if isinstance(loc, str) and loc.strip():
                return loc
        return None
