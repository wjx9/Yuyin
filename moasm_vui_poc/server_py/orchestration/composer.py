"""工具结果的自然语言整理层。"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Protocol

from routing.gemini import GeminiClient, GeminiError
from routing.history import Turn

_log = logging.getLogger("orchestration.composer")

_MAX_TOOL_TEXT = 8_000
_URL_RE = re.compile(r"https?://[^\s]+")


class ResultComposer(Protocol):
    def compose(
        self,
        *,
        query: str,
        intent: str,
        tool_text: str,
        history: list[Turn],
    ) -> str:
        ...


class GeminiResultComposer:
    """只负责表达，不负责查询事实。"""

    _SYSTEM = (
        "你是手机语音助手的最终回答者。请整合用户原话和【已知结果】，回答用户的问题。\n"
        "历史对话是当前会话的上下文；当本轮没有新增工具结果时，可以根据历史和明确记录的事实直接回答。\n"
        "规则：\n"
        "1. 【已知结果】是事实依据；不得编造其中没有的时间、地点、价格、状态或结论。"
        "每段开头的 status 是确定状态：success 表示已成功获取，empty 表示无匹配结果，"
        "blocked 表示缺少输入，failed 表示调用失败；不得改变其含义；\n"
        "2. 不要按结果的原始顺序逐段复述。先给用户最有用的结论，再补充必要细节；\n"
        "3. 多份结果有关联时，要自然合并为一段完整回答；重复信息只说一次；\n"
        "4. 只保留回答当前问题需要的信息。列表很长时，优先保留最相关的少量项目，"
        "不要机械罗列全部内容；\n"
        "5. 可以基于已知事实给出明确、常识性的下一步建议，但不要把建议说成已经查询到的事实；\n"
        "6. 只有【已知结果】明确写出失败、没有找到或不可用时，才能说该项失败或没有结果；"
        "其余情况下必须优先使用其中已有的具体内容，不能擅自否定已查到的信息。\n"
        "7. 只有【待补充信息】明确存在时，才在结尾自然提出其中的一个问题；"
        "不得自行新增追问。\n"
        "8. 只要存在有效结果，就先给出已确认结论；不得用“很抱歉”否定已完成部分。\n"
        "9. 不要提及工具、模型、任务、能力 id、内部流程或“根据工具结果”；\n"
        "10. 用自然、简洁、适合语音播报的中文输出；不要输出分析过程。"
    )

    def __init__(self, gemini: GeminiClient):
        self._gemini = gemini

    def compose(
        self,
        *,
        query: str,
        intent: str,
        tool_text: str,
        history: list[Turn],
    ) -> str:
        source_text = tool_text[:_MAX_TOOL_TEXT]
        prompt = (
            f"当前日期：{date.today().isoformat()}\n"
            f"用户原话：{query}\n"
            f"已知结果与执行记录：\n{source_text}\n\n"
            "请生成最终回答。"
        )

        try:
            answer = self._gemini.answer(
                prompt,
                system=self._SYSTEM,
                temperature=0.2,
                history=[(turn.query, turn.response) for turn in history],
            )
        except GeminiError as error:
            _log.warning("结果总结失败，回退工具原文：%s", error)
            return tool_text

        text = answer.text.strip() or tool_text

        # 防止模型遗漏工具结果中已有的来源链接。
        missing_urls = [
            url for url in dict.fromkeys(_URL_RE.findall(tool_text))
            if url not in text
        ]
        if missing_urls:
            text += "\n\n来源：\n" + "\n".join(f"- {url}" for url in missing_urls)

        return text
