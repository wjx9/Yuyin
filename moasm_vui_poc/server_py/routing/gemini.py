"""Gemini REST 客户端（仅用 requests，零额外 SDK 依赖）。

在分流层有两个用途：① GeminiClassifier 做意图分类；② ChitchatHandler 做闲聊兜底。
闲聊兜底可开启 Google Search grounding：是否真去联网由模型自行判断（简单问题不触发），
搜后基于网页作答并回传来源。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import requests

_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
_TIMEOUT = (10, 60)


class GeminiError(Exception):
    pass


@dataclass
class Source:
    """grounding 引用的网页来源。"""

    title: str
    uri: str


@dataclass
class GeminiAnswer:
    """一次生成的结果：正文 + 可选的联网来源。"""

    text: str
    sources: list[Source] = field(default_factory=list)


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str = "gemini-2.5-flash",
        session: requests.Session | None = None,
    ):
        self._key = api_key
        self._model = model
        self._session = session or requests.Session()

    def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        history: list[tuple[str, str]] | None = None,
    ) -> str:
        """纯文本生成（分类器/无需联网的场景用），返回正文字符串。"""
        return self.answer(
            prompt, system=system, temperature=temperature, history=history
        ).text

    def answer(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.0,
        history: list[tuple[str, str]] | None = None,
        grounded: bool = False,
    ) -> GeminiAnswer:
        """生成并返回 GeminiAnswer。grounded=True 时挂上 Google Search 工具，
        模型按需联网（简单问题不会真搜），并回传来源。"""
        contents: list[dict] = []
        # history 为 (用户输入, 模型回复) 的时间正序列表，展开成 Gemini 的多轮 contents
        for user_text, model_text in history or []:
            contents.append({"role": "user", "parts": [{"text": user_text}]})
            contents.append({"role": "model", "parts": [{"text": model_text}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        body: dict = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if grounded:
            body["tools"] = [{"google_search": {}}]  # Gemini 2.x 内置联网搜索工具

        candidate = self._post(body)
        return GeminiAnswer(text=_extract_text(candidate), sources=_extract_sources(candidate))

    def _post(self, body: dict) -> dict:
        """发请求并返回首个 candidate（dict）；网络/HTTP 错误抛 GeminiError。"""
        url = f"{_BASE}/{self._model}:generateContent"
        try:
            resp = self._session.post(
                url,
                headers={"x-goog-api-key": self._key, "Content-Type": "application/json"},
                json=body,
                timeout=_TIMEOUT,
            )
        except requests.RequestException as e:
            raise GeminiError(f"请求 Gemini 失败: {e}") from e

        if not resp.ok:
            raise GeminiError(f"Gemini 返回 {resp.status_code}: {resp.text[:300]}")

        try:
            return resp.json()["candidates"][0]
        except (KeyError, IndexError, ValueError):
            return {}


def loads_json_loose(text: str):
    """容错解析 LLM 输出的 JSON：剥掉可能的 ```json 代码块，取第一个 {...}。

    供各"用 Gemini 做结构化抽取"的解析器共用（高德查询解析、新闻查询解析等）。
    解析不出返回 None，由调用方自行兜底。
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    start, end = t.find("{"), t.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        return json.loads(t[start : end + 1])
    except ValueError:
        return None


def _extract_text(candidate: dict) -> str:
    try:
        parts = candidate["content"]["parts"]
        return "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError):
        return ""


def _extract_sources(candidate: dict) -> list[Source]:
    chunks = candidate.get("groundingMetadata", {}).get("groundingChunks", []) or []
    sources: list[Source] = []
    seen: set[str] = set()
    for c in chunks:
        web = c.get("web") or {}
        uri = web.get("uri", "")
        if not uri or uri in seen:
            continue
        seen.add(uri)
        sources.append(Source(title=web.get("title", "") or uri, uri=uri))
    return sources
