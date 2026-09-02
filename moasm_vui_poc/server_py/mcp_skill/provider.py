"""SkillCredentialProvider：按 (user_id, skill_id) 取动态凭证（完整方案 §7）。

注意与 server/auth.py 的 CredentialProvider（tripnow 内置平台凭证）区分：
前者是**技能商店用户自配的 MCP 技能凭证**（AES-GCM 加密存储，明文端点只对 server 侧）；
后者是**内置能力的平台凭证**。名字刻意错开，避免混淆。

**不缓存**（决策）：凭证只在 MCP 连接建立时取一次（每次用户图重建一次，频率极低），
去掉 5min TTL 缓存彻底消除"改了 key 仍取到旧值"的边缘（§13）。
"""

from __future__ import annotations

from store_client import StoreUnavailable

from .client import McpSkillError


class SkillCredentialProvider:
    """连接建立时才调用的凭证取值器。无状态、无缓存。"""

    def __init__(self, store_client):
        self._store = store_client

    def get(self, user_id: str, skill_id: str) -> dict:
        """返回该用户该技能的凭证 dict（明文）。未配置 → {}；商店不可达 → McpSkillError。"""
        try:
            resp = self._store.get_credentials_plain(user_id, skill_id)
        except StoreUnavailable as e:
            raise McpSkillError(f"凭证服务不可用：{e}") from e
        return resp.get("values") or {}
