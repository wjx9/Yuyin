from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests
from requests import Response

from .config import AppConfig, api_key_env_hint, effective_api_key
from .local_context import (
    WorkspaceToolbox,
    attachment_context,
    context_to_prompt,
    is_image_attachment,
    referenced_path_context,
)
from .storage import Message


DEFAULT_TIMEOUT = 180


@dataclass(slots=True)
class ChatRequest:
    config: AppConfig
    history: list[Message]
    user_message: Message
    workspace: str = ""


def _data_url(attachment) -> str:
    raw = Path(attachment.path).read_bytes()
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{attachment.mime};base64,{encoded}"


def _base64(attachment) -> str:
    return base64.b64encode(Path(attachment.path).read_bytes()).decode("ascii")


def _system_prompt(config: AppConfig, workspace: str = "") -> str:
    lines = [
        "你是一个桌面端中文语音助手，回答风格类似 ChatGPT/Claude。",
        "默认使用中文回答，除非用户明确要求其他语言。",
        "可以使用 Markdown 输出：标题、列表、表格、引用、代码块、mermaid 图、==高亮== 都可以。",
        "当用户提供附件、本地文件内容或截图时，结合这些上下文回答。",
    ]
    if config.use_workspace and workspace:
        lines.append(f"当前工作文件夹：{workspace}")
        lines.append("如果用户询问代码或文件，请优先基于工作文件夹上下文和已读取文件判断。")
    if config.provider.lower() == "aitogit_openai" and config.enable_web_search:
        lines.append("已启用联网搜索工具。遇到最新信息、实时数据、新闻、股价、汇率、天气、版本变化等问题时，应自行决定是否调用 web search 获取最新结果。")
    if config.agent_mode and workspace:
        lines.append(
            "你可以请求本地工具。若需要工具，请只输出一个 ```tool_calls 代码块，"
            "内容为 JSON 数组，例如："
            '[{"tool":"list_dir","args":{"path":"."}},{"tool":"read_file","args":{"path":"README.md"}}]。'
        )
        lines.append(
            "可用工具：list_dir(path)、read_file(path)、search_text(pattern,path)、"
            "write_file(path,content)、run_command(command,timeout_seconds)。"
        )
        if not config.allow_write_tools:
            lines.append("当前未允许写入/命令；只应使用 list_dir/read_file/search_text。")
        lines.append("拿到工具结果后继续完成用户任务，不要把工具协议解释给用户。")
    return "\n".join(lines)


def _extra_context_text(message: Message, workspace: str, config: AppConfig) -> str:
    contexts = []
    contexts.extend(attachment_context(message.attachments))
    if config.use_workspace:
        contexts.extend(referenced_path_context(message.content, workspace))
    prompt = context_to_prompt(contexts)
    if not prompt:
        return message.content
    if message.content.strip():
        return f"{message.content}\n\n以下是应用读取到的本地上下文：\n\n{prompt}"
    return f"以下是应用读取到的本地上下文：\n\n{prompt}"


def _trim_history(messages: list[Message], max_messages: int = 24) -> list[Message]:
    return messages[-max_messages:]


class ProviderError(RuntimeError):
    pass


THINK_BLOCK_RE = re.compile(r"<think(?:ing)?>(.*?)</think(?:ing)?>", re.DOTALL | re.IGNORECASE)
_REASONING_KEYS = {"reasoning", "reasoning_content", "thinking", "thought", "thoughts"}


def _join_text_blocks(parts: list[str]) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if not isinstance(part, str):
            continue
        value = part.strip()
        if not value or value in seen:
            continue
        cleaned.append(value)
        seen.add(value)
    return "\n\n".join(cleaned)


def _content_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    parts.append(item["text"])
                elif isinstance(item.get("content"), str):
                    parts.append(item["content"])
        return "\n".join(parts)
    return str(value)


def _coerce_reasoning_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return _join_text_blocks([_coerce_reasoning_text(item) for item in value])
    if isinstance(value, dict):
        if value.get("type") == "redacted_thinking":
            return ""
        texts: list[str] = []
        for key in (
            "text",
            "content",
            "summary",
            "reasoning",
            "reasoning_content",
            "thinking",
            "thought",
            "thoughts",
        ):
            if key in value:
                texts.append(_coerce_reasoning_text(value[key]))
        return _join_text_blocks(texts)
    return ""


def _extract_reasoning_text(value: Any) -> str:
    if isinstance(value, dict):
        texts: list[str] = []
        block_type = str(value.get("type") or "").lower()
        if block_type in {"reasoning", "thinking"}:
            texts.append(_coerce_reasoning_text(value))
        for key, item in value.items():
            lower = key.lower()
            if lower in _REASONING_KEYS:
                texts.append(_coerce_reasoning_text(item))
            elif isinstance(item, (dict, list)):
                texts.append(_extract_reasoning_text(item))
        return _join_text_blocks(texts)
    if isinstance(value, list):
        return _join_text_blocks([_extract_reasoning_text(item) for item in value])
    return ""


def _split_think_blocks(content: str) -> tuple[str, str]:
    reasoning: list[str] = []

    def collect(match: re.Match[str]) -> str:
        reasoning.append(match.group(1).strip())
        return ""

    cleaned = THINK_BLOCK_RE.sub(collect, content or "").strip()
    return cleaned, _join_text_blocks(reasoning)


def _compose_visible_completion(content: Any, reasoning: str = "") -> str:
    cleaned_content, inline_reasoning = _split_think_blocks(_content_to_text(content))
    reasoning_text = _join_text_blocks([reasoning, inline_reasoning])
    if not reasoning_text:
        return cleaned_content
    quoted = "\n".join(
        ">" if not line.strip() else f"> {line}"
        for line in reasoning_text.splitlines()
    )
    if cleaned_content:
        return f"### \u601d\u8003\u8fc7\u7a0b\n\n{quoted}\n\n---\n\n{cleaned_content}"
    return f"### \u601d\u8003\u8fc7\u7a0b\n\n{quoted}"


class LLMClient:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def complete(self, request: ChatRequest) -> str:
        cfg = request.config
        key = effective_api_key(cfg)
        if not key:
            raise ProviderError(
                "请先在顶部设置 API Key，或配置环境变量："
                f"{api_key_env_hint(cfg.provider)}。"
            )
        provider = cfg.provider.lower()
        if provider == "aitogit_openai":
            return self._complete_aitogit_openai(request, key)
        if provider in {"openai", "openai-compatible"}:
            return self._complete_openai(request, key)
        if provider == "gemini":
            return self._complete_gemini(request, key)
        if provider == "claude":
            return self._complete_claude(request, key)
        raise ProviderError(f"不支持的 provider：{cfg.provider}")

    def _openai_messages(self, request: ChatRequest) -> list[dict[str, Any]]:
        cfg = request.config
        workspace = request.workspace
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _system_prompt(cfg, workspace)}
        ]
        all_messages = _trim_history([*request.history, request.user_message])
        for message in all_messages:
            role = "assistant" if message.role == "assistant" else "user"
            text = message.content
            if message is request.user_message:
                text = _extra_context_text(message, workspace, cfg)
            image_attachments = [
                item for item in message.attachments if is_image_attachment(item) and Path(item.path).exists()
            ]
            if image_attachments:
                content: list[dict[str, Any]] = []
                if text:
                    content.append({"type": "text", "text": text})
                for item in image_attachments:
                    content.append({"type": "image_url", "image_url": {"url": _data_url(item)}})
                messages.append({"role": role, "content": content})
            else:
                messages.append({"role": role, "content": text})
        return messages

    def _complete_openai(self, request: ChatRequest, api_key: str) -> str:
        cfg = request.config
        base = (cfg.base_url or "https://api.openai.com/v1").rstrip("/")
        url = f"{base}/chat/completions"
        body = {
            "model": cfg.model or "gpt-4.1-mini",
            "messages": self._openai_messages(request),
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_output_tokens,
        }
        response = _post_json(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "close",
                "User-Agent": "myChatGPT/0.1",
            },
            body=body,
        )
        if response.status_code >= 400:
            raise ProviderError(_format_http_error(response))
        data = response.json()
        message = data["choices"][0].get("message", {})
        return _compose_visible_completion(
            message.get("content"),
            _extract_reasoning_text(message),
        )

    def _responses_url(self, base_url: str) -> str:
        base = (base_url or "https://api.openai.com/v1").rstrip("/")
        if base.endswith("/responses"):
            return base
        if base.endswith("/v1"):
            return f"{base}/responses"
        return f"{base}/v1/responses"

    def _responses_input(self, request: ChatRequest) -> list[dict[str, Any]]:
        cfg = request.config
        workspace = request.workspace
        items: list[dict[str, Any]] = []
        all_messages = _trim_history([*request.history, request.user_message])
        for message in all_messages:
            role = "assistant" if message.role == "assistant" else "user"
            text = message.content
            if message is request.user_message:
                text = _extra_context_text(message, workspace, cfg)
            image_attachments = [
                item for item in message.attachments if is_image_attachment(item) and Path(item.path).exists()
            ]
            if role == "user" and image_attachments:
                content: list[dict[str, Any]] = []
                if text:
                    content.append({"type": "input_text", "text": text})
                for item in image_attachments:
                    content.append({"type": "input_image", "image_url": _data_url(item)})
                items.append({"role": role, "content": content})
            else:
                items.append({"role": role, "content": text or ""})
        return items

    def _complete_aitogit_openai(self, request: ChatRequest, api_key: str) -> str:
        cfg = request.config
        url = self._responses_url(cfg.base_url or "https://api.aitogit.cc")
        body: dict[str, Any] = {
            "model": cfg.model or "gpt-5.5",
            "instructions": _system_prompt(cfg, request.workspace),
            "input": self._responses_input(request),
            "store": False,
            "max_output_tokens": cfg.max_output_tokens,
            "reasoning": {"effort": "xhigh"},
        }
        if cfg.enable_web_search:
            body["tools"] = [{"type": "web_search"}]
            body["tool_choice"] = "auto"
        response = _post_json(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "close",
                "User-Agent": "myChatGPT/0.1",
            },
            body=body,
        )
        if response.status_code >= 400:
            raise ProviderError(_format_http_error(response))
        return _extract_responses_text(response.json())

    def _gemini_contents(self, request: ChatRequest) -> list[dict[str, Any]]:
        cfg = request.config
        workspace = request.workspace
        contents: list[dict[str, Any]] = []
        all_messages = _trim_history([*request.history, request.user_message])
        for message in all_messages:
            role = "model" if message.role == "assistant" else "user"
            text = message.content
            if message is request.user_message:
                text = _extra_context_text(message, workspace, cfg)
            parts: list[dict[str, Any]] = []
            if text:
                parts.append({"text": text})
            for item in message.attachments:
                if is_image_attachment(item) and Path(item.path).exists():
                    parts.append({"inline_data": {"mime_type": item.mime, "data": _base64(item)}})
            if parts:
                contents.append({"role": role, "parts": parts})
        return contents

    def _complete_gemini(self, request: ChatRequest, api_key: str) -> str:
        cfg = request.config
        base = (cfg.base_url or "https://generativelanguage.googleapis.com/v1beta").rstrip("/")
        model = cfg.model or "gemini-2.5-flash"
        url = f"{base}/models/{model}:generateContent"
        body = {
            "system_instruction": {"parts": [{"text": _system_prompt(cfg, request.workspace)}]},
            "contents": self._gemini_contents(request),
            "generationConfig": {
                "temperature": cfg.temperature,
                "maxOutputTokens": cfg.max_output_tokens,
            },
        }
        response = _post_json(
            url,
            params={"key": api_key},
            headers={"Content-Type": "application/json", "Accept": "application/json", "Connection": "close", "User-Agent": "myChatGPT/0.1"},
            body=body,
        )
        if response.status_code >= 400:
            raise ProviderError(_format_http_error(response))
        data = response.json()
        candidates = data.get("candidates") or []
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        answer_parts: list[str] = []
        reasoning_parts: list[str] = []
        for part in parts:
            if not isinstance(part, dict) or not isinstance(part.get("text"), str):
                continue
            if part.get("thought") or str(part.get("type") or "").lower() in {"thinking", "reasoning"}:
                reasoning_parts.append(part["text"])
            else:
                answer_parts.append(part["text"])
        return _compose_visible_completion(
            "\n".join(answer_parts),
            _join_text_blocks(reasoning_parts),
        )


    def _claude_messages(self, request: ChatRequest) -> list[dict[str, Any]]:
        cfg = request.config
        workspace = request.workspace
        messages: list[dict[str, Any]] = []
        all_messages = _trim_history([*request.history, request.user_message])
        for message in all_messages:
            role = "assistant" if message.role == "assistant" else "user"
            text = message.content
            if message is request.user_message:
                text = _extra_context_text(message, workspace, cfg)
            content: list[dict[str, Any]] = []
            if text:
                content.append({"type": "text", "text": text})
            for item in message.attachments:
                if is_image_attachment(item) and Path(item.path).exists():
                    content.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": item.mime,
                                "data": _base64(item),
                            },
                        }
                    )
            messages.append({"role": role, "content": content or [{"type": "text", "text": ""}]})
        return messages

    def _complete_claude(self, request: ChatRequest, api_key: str) -> str:
        cfg = request.config
        base = (cfg.base_url or "https://api.anthropic.com").rstrip("/")
        url = f"{base}/v1/messages"
        body = {
            "model": cfg.model or "claude-3-5-sonnet-latest",
            "system": _system_prompt(cfg, request.workspace),
            "messages": self._claude_messages(request),
            "temperature": cfg.temperature,
            "max_tokens": cfg.max_output_tokens,
        }
        response = _post_json(
            url,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Connection": "close",
                "User-Agent": "myChatGPT/0.1",
            },
            body=body,
        )
        if response.status_code >= 400:
            raise ProviderError(_format_http_error(response))
        data = response.json()
        parts = data.get("content") or []
        answer_parts: list[str] = []
        reasoning_parts: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "").lower()
            if part_type == "text" and isinstance(part.get("text"), str):
                answer_parts.append(part["text"])
            elif part_type == "thinking":
                reasoning_parts.append(_coerce_reasoning_text(part))
        return _compose_visible_completion(
            "\n".join(answer_parts),
            _join_text_blocks(reasoning_parts),
        )



def _post_json(
    url: str,
    *,
    headers: dict[str, str],
    body: dict[str, Any],
    params: dict[str, str] | None = None,
) -> Response:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            return requests.post(
                url,
                params=params,
                headers=headers,
                json=body,
                timeout=(20, DEFAULT_TIMEOUT),
            )
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt < 3 and _is_retryable_network_error(exc):
                time.sleep(0.8 * attempt)
                continue
            raise ProviderError(_format_network_error(exc)) from exc
    raise ProviderError(_format_network_error(last_error))


def _is_retryable_network_error(exc: requests.exceptions.RequestException) -> bool:
    text = f"{repr(exc)} {exc}".lower()
    return any(
        token in text
        for token in (
            "connection aborted",
            "connection reset",
            "winerror 10053",
            "winerror 10054",
            "10053",
            "10054",
            "timed out",
            "timeout",
            "temporarily unavailable",
        )
    )


def _format_network_error(exc: Exception | None) -> str:
    if exc is None:
        return "网络请求失败。"
    raw = repr(exc)
    hints = []
    lowered = raw.lower()
    if "10053" in lowered:
        hints.append("检测到 WinError 10053：本机网络栈、防火墙、代理或远端服务中止了连接。程序已自动重试 3 次。")
    if "connection aborted" in lowered or "connection reset" in lowered:
        hints.append("连接在请求过程中被中断。请确认代理、VPN、防火墙和 aitogit 服务当前可用。")
    if "timed out" in lowered or "timeout" in lowered:
        hints.append("请求超时。请稍后重试，或检查网络代理。")
    detail = str(exc) or raw
    if hints:
        return "网络连接失败：\n" + "\n".join(f"- {hint}" for hint in hints) + f"\n\n原始错误：{detail}"
    return f"网络连接失败：{detail}"

def _extract_responses_text(data: dict[str, Any]) -> str:
    texts: list[str] = []
    reasoning_texts: list[str] = []
    citations: list[tuple[str, str]] = []
    direct = data.get("output_text")
    if isinstance(direct, str) and direct:
        texts.append(direct)
    for item in data.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").lower()
        if item_type in {"reasoning", "thinking"}:
            reasoning_texts.append(_coerce_reasoning_text(item))
        if isinstance(item.get("content"), list):
            for content in item["content"]:
                if not isinstance(content, dict):
                    continue
                content_type = str(content.get("type") or "").lower()
                if content_type in {"reasoning", "thinking"}:
                    reasoning_texts.append(_coerce_reasoning_text(content))
                    continue
                text = ""
                if content.get("type") in {"output_text", "text"} and isinstance(content.get("text"), str):
                    text = content["text"]
                elif isinstance(content.get("content"), str):
                    text = content["content"]
                if text and text not in texts:
                    texts.append(text)
                for annotation in content.get("annotations", []) or []:
                    if not isinstance(annotation, dict):
                        continue
                    url = annotation.get("url")
                    if not isinstance(url, str) or not url:
                        continue
                    title = annotation.get("title") if isinstance(annotation.get("title"), str) else url
                    item_pair = (title, url)
                    if item_pair not in citations:
                        citations.append(item_pair)
        elif isinstance(item.get("text"), str) and item["text"] not in texts:
            texts.append(item["text"])
    answer = "\n".join(texts)
    if citations:
        sources = "\n".join(f"- [{title}]({url})" for title, url in citations)
        answer = f"{answer}\n\n### \u6765\u6e90\n{sources}" if answer else f"### \u6765\u6e90\n{sources}"
    return _compose_visible_completion(answer, _join_text_blocks(reasoning_texts))


def _format_http_error(response: requests.Response) -> str:
    text = response.text
    try:
        data = response.json()
        text = json.dumps(data, ensure_ascii=False, indent=2)
    except ValueError:
        pass
    if len(text) > 2000:
        text = text[:2000] + "\n[错误内容过长，已截断]"
    return f"HTTP {response.status_code}: {text}"


TOOL_BLOCK_RE = re.compile(r"```tool_calls\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def extract_tool_calls(text: str) -> list[dict[str, Any]]:
    match = TOOL_BLOCK_RE.search(text)
    if not match:
        return []
    raw = match.group(1).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    calls = []
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("tool"), str):
            args = item.get("args")
            calls.append({"tool": item["tool"], "args": args if isinstance(args, dict) else {}})
    return calls


def run_agentic_completion(request: ChatRequest, max_rounds: int = 5) -> str:
    cfg = request.config
    client = LLMClient(cfg)
    if not cfg.agent_mode or not request.workspace:
        return client.complete(request)
    toolbox = WorkspaceToolbox(request.workspace, allow_writes=cfg.allow_write_tools)
    scratch_history = [*request.history]
    current_user = request.user_message
    last_text = ""
    for _ in range(max_rounds):
        step_request = ChatRequest(
            config=cfg,
            history=scratch_history,
            user_message=current_user,
            workspace=request.workspace,
        )
        last_text = client.complete(step_request)
        calls = extract_tool_calls(last_text)
        if not calls:
            return last_text
        scratch_history.append(current_user)
        scratch_history.append(Message(role="assistant", content=last_text))
        results = []
        for call in calls[:8]:
            result = toolbox.execute(call["tool"], call["args"])
            results.append({"tool": call["tool"], "args": call["args"], "result": result})
        current_user = Message(
            role="user",
            content=(
                "以下是刚才本地工具调用的结果。请基于结果继续完成任务；"
                "如果还需要工具，可以再次输出 tool_calls；否则输出最终回答。\n\n"
                f"```json\n{json.dumps(results, ensure_ascii=False, indent=2)}\n```"
            ),
        )
    return last_text + "\n\n[代理模式达到最大工具轮数，已停止。]"






