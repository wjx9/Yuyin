"""商店 HTTP 客户端：server_py 侧唯一知道商店地址的模块（设计 §4.1）。

失败抛 StoreUnavailable → 服务端退回"内置技能"路径，商店挂了不能拖垮聊天。
"""

from .api import StoreClient, StoreUnavailable

__all__ = ["StoreClient", "StoreUnavailable"]
