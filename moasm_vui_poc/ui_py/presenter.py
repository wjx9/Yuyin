"""Presenter 接口：分流结果如何呈现给用户的抽象。

chat_app 只依赖这个接口，不关心具体是终端气泡、富文本 TUI 还是未来的 GUI。
换 UI = 换一个实现，入口与 routing/业务层零改动。

日志区的特殊处理：路由调试日志是通过 logging 在 dispatch() 内部实时打印的，时间上
正好落在 show_input 与 show_output 之间。Presenter 通过 log_formatter() 决定这些日志
长什么样（缩进、变暗），从而成为"夹在输入输出中间、又一眼能区分"的中间区。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

# 兜底闲聊的意图 id；介绍时与任务能力分开展示
CHITCHAT_INTENT = "chitchat"


def _plain(text: str) -> str:
    """把面向分类器的描述里残留的 markdown 强调去掉，用于人类可读的介绍。"""
    return text.replace("**", "")


class Presenter(ABC):
    """呈现层抽象。"""

    @abstractmethod
    def banner(self, intents: list[str]) -> None:
        """会话开始时的能力清单等横幅信息。"""

    @abstractmethod
    def intro(self, specs) -> None:
        """启动用法介绍：列出接入的三方能力及其用途，并说明兜底闲聊。

        specs 为 list[IntentSpec]（含 id 与 description），由 Dispatcher 提供，
        因此新增/移除能力时介绍自动同步，无需手维护文案。
        """

    @abstractmethod
    def info(self, message: str) -> None:
        """普通提示信息（如进入交互模式、退出）。"""

    @abstractmethod
    def show_input(self, text: str) -> None:
        """渲染一轮用户输入。"""

    @abstractmethod
    def show_output(self, text: str, *, intent: str | None = None) -> None:
        """渲染一轮 AI 输出；intent 非空时可在标签上标注命中意图。"""

    def log_formatter(self) -> logging.Formatter | None:
        """中间日志区的样式；返回 None 表示用 routing 的默认格式。"""
        return None


class PlainPresenter(Presenter):
    """最朴素实现：纯文本直接打印（等价于改造前的行为，用作兜底/非交互管道）。"""

    def banner(self, intents: list[str]) -> None:
        print(f"已启用意图：{', '.join(intents)}")

    def intro(self, specs) -> None:
        tasks = [s for s in specs if s.id != CHITCHAT_INTENT]
        chitchat = next((s for s in specs if s.id == CHITCHAT_INTENT), None)
        if tasks:
            print("我能做什么：")
            for s in tasks:
                print(f"  - [{s.id}] {_plain(s.description)}")
        else:
            print("当前仅启用了闲聊（其它能力的 key 未配置，故未接入第三方能力）。")
        if chitchat:
            print(f"其余情况兜底闲聊：{_plain(chitchat.description)}")

    def info(self, message: str) -> None:
        print(message)

    def show_input(self, text: str) -> None:
        print(f"你> {text}")

    def show_output(self, text: str, *, intent: str | None = None) -> None:
        if intent:
            print(f"[意图: {intent}]")
        print(text)
