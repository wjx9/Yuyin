"""client-server 模式的 Python 客户端（与 server/ 对应的另一半）。

定位：把 chat_app.py 的"本地直连 Dispatcher"换成"HTTP 调远端 serve.py"，
其余体验（聊天气泡、多轮记忆、单轮/交互、批量 run_cases）尽量保持一致。

分层（刻意与 server/ 对称，便于对照）：
    config —— 客户端配置（服务端地址 / 鉴权 token / 位置 / session_id），从 env/CLI 读
    client —— ServerClient：唯一懂 HTTP 契约的地方（health / chat），其余层不感知传输
    app    —— 交互式 / 单轮 CLI，复用 ui_py.TerminalPresenter，对标 chat_app.py
    run_cases —— 批量回归，对标根目录 run_cases.py，只是改走 CS 链路

"大脑"（routing.Dispatcher）整体在服务端，客户端只负责采集输入、发请求、渲染输出，
这正是 Flutter 端要做的事——Python 版先把链路跑通、把契约固定下来。
"""

from .client import ServerClient, ServerError
from .config import ClientConfig

__all__ = ["ServerClient", "ServerError", "ClientConfig"]
