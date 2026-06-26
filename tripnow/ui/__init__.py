"""presentation 层：把分流结果渲染给用户。

与 routing/业务层解耦——routing 只产出 RouteResult，"长什么样"由本层决定。
未来要换样式（更花哨的 TUI）或换形态（GUI/Web），只需新增一个实现了 Presenter
接口的类，分流与业务代码无需改动。
"""

from .presenter import PlainPresenter, Presenter
from .terminal import TerminalPresenter

__all__ = ["Presenter", "PlainPresenter", "TerminalPresenter"]
