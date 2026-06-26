"""腾讯新闻能力（独立 provider）：热点新闻 / 天气 / 事实查证。

官方接入面是 Skill/CLI（tencent-news-cli），本包把该 CLI 薄封装成
与其他 provider 一致的 service 形态供分流层调用。
"""

from .client import TencentNewsCli
from .config import TencentNewsSettings, build_service
from .errors import TencentNewsError
from .models import NewsResult
from .service import NewsService

__all__ = [
    "TencentNewsCli",
    "TencentNewsSettings",
    "build_service",
    "TencentNewsError",
    "NewsResult",
    "NewsService",
]
