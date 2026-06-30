"""快递100 业务层：查物流（增删改查里的"查"）。"""

from __future__ import annotations

import logging

from .client import Kuaidi100Client, guess_com_by_prefix
from .errors import Kuaidi100Error
from .models import TrackResult

_log = logging.getLogger("kuaidi100_client.service")


class ExpressService:
    def __init__(self, client: Kuaidi100Client):
        self._client = client

    def track(self, num: str, *, com: str | None = None, phone: str | None = None) -> TrackResult:
        """查询单号物流。com 为空时先在线识别快递公司，失败再按前缀本地兜底。"""
        if not com:
            com = self._detect_com(num)
        data = self._client.query(com, num, phone=phone)
        return TrackResult.from_dict(num, data)

    def _detect_com(self, num: str) -> str:
        """识别快递公司：优先在线 autodetect；其不可用（如 key 未授权该产品）时按前缀本地兜底。"""
        try:
            candidates = self._client.autodetect(num)
            if candidates:
                return candidates[0]
        except Kuaidi100Error as e:
            _log.warning("在线识别快递公司失败，改用前缀本地兜底：%s", e)

        guess = guess_com_by_prefix(num)
        if guess:
            return guess
        raise Kuaidi100Error(f"无法识别单号 {num} 所属快递公司，请显式指定 com")
