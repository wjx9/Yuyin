"""高德地图能力（独立 provider，基于 Google A2A 协议）。"""

from .client import AmapClient
from .config import AmapSettings, build_service
from .errors import AmapError
from .models import MapQuery, MapResult
from .parser import NaiveQueryParser, QueryParser
from .rest_client import AmapRestClient
from .rest_service import RestMapService
from .service import A2aMapService, MapService

__all__ = [
    "AmapClient",
    "AmapRestClient",
    "AmapSettings",
    "build_service",
    "AmapError",
    "MapQuery",
    "MapResult",
    "QueryParser",
    "NaiveQueryParser",
    "MapService",
    "A2aMapService",
    "RestMapService",
]
