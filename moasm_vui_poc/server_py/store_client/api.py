"""StoreClient：商店后端 HTTP 客户端（标准库 urllib，零新依赖）。

server_py 是标准库 HTTP 栈，商店地址由 .env 的 SKILL_STORE_URL 提供。
超时 5s：商店不可达时快速抛 StoreUnavailable，别让聊天线程等太久。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request


class StoreUnavailable(RuntimeError):
    """商店不可达或返回异常。调用方应退回"内置技能"。"""


class StoreClient:
    def __init__(self, base_url: str, timeout: float = 5.0):
        self._base = base_url.rstrip("/")
        self._timeout = timeout

    def sync(self, user_id: str) -> dict:
        """GET {base}/me/skills/sync?user_id=... → {"version": N, "skills": [manifest...]}"""
        url = f"{self._base}/me/skills/sync?user_id={urllib.parse.quote(user_id)}"
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise StoreUnavailable(f"商店不可达: {e}") from e
        except json.JSONDecodeError as e:
            raise StoreUnavailable(f"商店响应非 JSON: {e}") from e

    def sync_builtin_skills(self, manifests: list[dict]) -> dict:
        """把主服务当前实际注册的内置能力同步到商店目录。"""
        url = f"{self._base}/internal/builtin-skills/sync"
        body = json.dumps({"skills": manifests}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST", headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise StoreUnavailable(f"商店不可达: {e}") from e
        except json.JSONDecodeError as e:
            raise StoreUnavailable(f"商店响应非 JSON: {e}") from e

    def get_credentials_plain(self, user_id: str, skill_id: str) -> dict:
        """GET {base}/me/credentials/plain → {configured, values}（明文，MCP 连接注入用）。

        POC 无鉴权（商用收紧见 完整方案 §13）；5s 超时 → StoreUnavailable。
        """
        url = (
            f"{self._base}/me/credentials/plain?user_id={urllib.parse.quote(user_id)}"
            f"&skill_id={urllib.parse.quote(skill_id)}"
        )
        try:
            with urllib.request.urlopen(url, timeout=self._timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise StoreUnavailable(f"商店不可达: {e}") from e
        except json.JSONDecodeError as e:
            raise StoreUnavailable(f"商店响应非 JSON: {e}") from e
