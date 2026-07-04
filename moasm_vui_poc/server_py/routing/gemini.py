"""Gemini REST 客户端（仅用 requests，零额外 SDK 依赖）。

在分流层有两个用途：① GeminiClassifier 做意图分类+槽位抽取（function calling，
choose_function）；② ChitchatHandler 做闲聊兜底（answer/generate）。
闲聊兜底可开启 Google Search grounding：是否真去联网由模型自行判断（简单问题不触发），
搜后基于网页作答并回传来源。

本模块只做传输与解析，不含任何业务语义：function 声明由调用方（分类器）拼好传入。
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


@dataclass(frozen=True)
class FunctionCall:
    """模型选择调用的一个函数：名字 + 参数（原样透传，语义校验由调用方负责）。"""

    name: str
    args: dict = field(default_factory=dict)


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
        body: dict = {
            "contents": _build_contents(prompt, history),
            "generationConfig": {"temperature": temperature},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if grounded:
            body["tools"] = [{"google_search": {}}]  # Gemini 2.x 内置联网搜索工具

        candidate = self._post(body)
        return GeminiAnswer(text=_extract_text(candidate), sources=_extract_sources(candidate))

    def choose_function(
        self,
        prompt: str,
        *,
        declarations: list[dict],
        system: str | None = None,
        temperature: float = 0.0,
        history: list[tuple[str, str]] | None = None,
    ) -> FunctionCall | None:
        """Function calling：让模型从 declarations 中强制选一个函数并填参数。

        declarations 是 Gemini functionDeclarations 原始格式的 dict 列表
        （{"name", "description", 可选 "parameters"}），由调用方拼装。
        history 同 answer()：(用户输入, 模型回复) 时间正序列表，模型可据此理解
        跟进式输入（"再来3条呢"）；要不要带、带多少由调用方裁剪。
        mode=ANY 强制模型必须调用其中一个函数（而非输出自由文本），因此
        "一次调用同时得到意图(函数名)+槽位(参数)"。极少数情况下模型仍可能
        不回 functionCall，此时返回 None，由调用方兜底。
        """
        body: dict = {
            "contents": _build_contents(prompt, history),
            "generationConfig": {"temperature": temperature},
            "tools": [{"functionDeclarations": declarations}],
            "toolConfig": {"functionCallingConfig": {"mode": "ANY"}},
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        return _extract_function_call(self._post(body))

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


def _build_contents(prompt: str, history: list[tuple[str, str]] | None) -> list[dict]:
    """把 (用户输入, 模型回复) 时间正序的 history 展开成多轮 contents，本轮 prompt 收尾。"""
    contents: list[dict] = []
    for user_text, model_text in history or []:
        contents.append({"role": "user", "parts": [{"text": user_text}]})
        contents.append({"role": "model", "parts": [{"text": model_text}]})
    contents.append({"role": "user", "parts": [{"text": prompt}]})
    return contents


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


def _extract_function_call(candidate: dict) -> FunctionCall | None:
    try:
        parts = candidate["content"]["parts"]
    except (KeyError, TypeError):
        return None
    for p in parts:
        fc = p.get("functionCall")
        if isinstance(fc, dict) and fc.get("name"):
            args = fc.get("args")
            return FunctionCall(name=fc["name"], args=args if isinstance(args, dict) else {})
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
