"""统一异常体系。业务层只需 catch TripNowError 即可覆盖所有可预期错误。"""


class TripNowError(Exception):
    """所有 TripNow 相关错误的基类。"""


class ConfigError(TripNowError):
    """配置缺失或非法（如未提供 api_key）。"""


class AuthError(TripNowError):
    """鉴权失败（401/403）。"""


class TransportError(TripNowError):
    """传输层错误：HTTP 非 2xx、网络异常、JSON-RPC error 等。"""

    def __init__(self, message: str, *, status: int | None = None, payload=None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class UnsupportedFeatureError(TripNowError):
    """当前传输方式不支持该能力（如 MCP 不支持流式）。"""
