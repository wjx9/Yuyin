"""Exa provider 的统一异常。"""


class ExaError(RuntimeError):
    """Exa API 调用或响应解析失败。"""