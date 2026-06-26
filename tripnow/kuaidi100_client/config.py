"""快递100 配置：从环境变量读取 key / customer。"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .client import Kuaidi100Client
from .errors import Kuaidi100Error
from .service import ExpressService


@dataclass
class Kuaidi100Settings:
    key: str
    customer: str

    @classmethod
    def from_env(cls) -> "Kuaidi100Settings":
        key = os.getenv("KUAIDI100_KEY", "").strip()
        customer = os.getenv("KUAIDI100_CUSTOMER", "").strip()
        if not key or not customer:
            raise Kuaidi100Error("缺少 KUAIDI100_KEY / KUAIDI100_CUSTOMER 环境变量")
        return cls(key=key, customer=customer)


def build_service(settings: Kuaidi100Settings) -> ExpressService:
    return ExpressService(Kuaidi100Client(settings.key, settings.customer))
