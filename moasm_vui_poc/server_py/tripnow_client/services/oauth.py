"""union_id 获取辅助。

文档里的 OAuth 流程：访问航班管家侧已配置好的授权 URL → 页面登录 →
重定向回我方配置页(官网)，重定向 URL 中带上当前用户的 union_id。

CLI 场景下没有回调服务器，最简做法：让用户在浏览器完成登录，把最终重定向到的
完整 URL 粘贴进来，由本函数解析出 union_id。未来做 GUI/服务端时可换成自动回调。
"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

# 重定向 URL 中可能用到的 union_id 参数名（文档不一致，两个都试）
_CANDIDATE_KEYS = ("union_id", "unionId", "unionid")


def extract_union_id(redirect_url: str) -> str | None:
    """从 OAuth 登录后重定向 URL 的 query 中解析 union_id。"""
    query = parse_qs(urlparse(redirect_url).query)
    for key in _CANDIDATE_KEYS:
        if key in query and query[key]:
            return query[key][0]
    return None
