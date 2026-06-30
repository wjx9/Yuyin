"""查询解析器接口：把自然语言诉求拆成结构化的 MapQuery。

REST 后端需要这一步（A2A 后端不需要，agent 自己会拆）。这里只定义接口与一个
零依赖的朴素实现；真正能拆解语义的实现（基于 LLM）放在 routing 层注入，
以免 amap_client 反向依赖 Gemini。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from .models import MapQuery


class QueryParser(ABC):
    @abstractmethod
    def parse(self, query: str) -> MapQuery:
        raise NotImplementedError


class NaiveQueryParser(QueryParser):
    """兜底实现：整句当关键词，不识别地点。amap_client 单独使用时的默认行为。"""

    def parse(self, query: str) -> MapQuery:
        return MapQuery(keywords=query)
