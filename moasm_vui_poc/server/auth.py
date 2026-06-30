"""三方个人数据访问凭证的获取。

抽象（几乎所有三方 OAuth 都是这套）：
    客户端引导用户去三方登录 → 三方回一个 key/token →
    我方按"平台用户账号"把 token 存云端 → 需要时按账号查出来 → 用它访问该用户的三方个人数据。

这一整套是独立模块，当前先 mock；这里只定义接口与 mock 实现，预留将来接真鉴权的缝：
将来新增 CloudCredentialProvider(resolve 时按 user_id 去存储里查各三方真实 token) 即可，
ChatService 只依赖 CredentialProvider 接口，无需改动。
"""

from __future__ import annotations

import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass

_log = logging.getLogger("server.auth")


@dataclass
class Credentials:
    """某用户访问各三方个人数据所需的凭证集合。

    目前只有 TripNow 个人能力用到身份（union_id）；其余三方（高德/快递）用的是
    应用级 key、与个人账号无关，故暂不在此。将来多三方真实 token 往这里扩字段或
    加一个 tokens: dict[provider, token]。
    mocked 标记本次凭证是否来自 mock（供上层打"假装鉴权"提示）。
    """

    tripnow_union_id: str | None = None
    mocked: bool = False


class CredentialProvider(ABC):
    @abstractmethod
    def resolve(self, user_id: str) -> Credentials:
        """按平台用户账号取出其各三方凭证。"""
        raise NotImplementedError


class MockCredentialProvider(CredentialProvider):
    """mock 鉴权：假装该用户已完成三方授权、我们已拿到 key。

    复用 CLI 同款测试账号（env TRIPNOW_UNION_ID）作为"拿到的 key"，
    这样个人能力在 server 下也能真正取到测试数据；未配置则返回空（个人能力会提示未登录）。
    """

    def __init__(self, tripnow_union_id: str | None = None):
        # 不传则回退到与 CLI 一致的测试账号
        self._tripnow_union_id = tripnow_union_id or os.getenv("TRIPNOW_UNION_ID", "").strip() or None

    def resolve(self, user_id: str) -> Credentials:
        _log.debug("mock 解析用户 %r 的三方凭证", user_id)
        return Credentials(tripnow_union_id=self._tripnow_union_id, mocked=True)
