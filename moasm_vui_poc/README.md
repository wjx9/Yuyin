# moasm_vui_poc — 多能力语音对话助手（client-server PoC）

> **一句话**：把"出行 / 快递 / 地图 / 新闻 / 闲聊…"多个第三方能力，用一层
> **Gemini 意图分流**编排成**单一对话入口**；再拆成 **PC 服务端（大脑）+ 客户端**的
> client-server 架构，客户端含 **Python 终端版**与 **Flutter 语音版**
> （VUI：按麦克风说话 → 端侧识别 → 发请求 → 朗读回复）。
>
> 本仓库是 **PoC**（`moasm_vui` = 把第三方能力接入下一代语音助手的可行性验证）。
> **TripNow（航班管家行程引擎）只是接入的第一个 provider，并非项目本身。**

---

## 项目结构：3 个部署单元 + 1 个共享层

| 顶层目录 | 角色 | 详细文档 |
|---|---|---|
| **`server_py/`** | 后端引擎（大脑）：多能力分流 + HTTP 服务端 | [`server_py/README.md`](server_py/README.md) |
| **`client_py/`** | Python 终端客户端（HTTP 连 `serve.py` 的参照实现） | [`client_py/README.md`](client_py/README.md) |
| **`client_flutter/`** | Flutter 手机客户端（语音版：ASR → `/chat` → TTS） | [`client_flutter/README.md`](client_flutter/README.md) |
| **`ui_py/`** | 共享呈现层（Python）：`server_py`(chat_app) 与 `client_py` 共用的终端聊天气泡 | 见 server_py/README §8.9 |

> **命名约定**：Python 单元统一带 `_py` 后缀（`server_py` / `client_py` / `ui_py`），
> 与 `client_flutter` 在多语言、多端部署的仓库里一眼区分语言/平台。

```
moasm_vui_poc/                  # 仓库根（.git 在此）
├── README.md                   # ← 本文：项目总览
├── .gitignore / pytest.ini
├── requirements.txt / requirements-dev.txt
├── .env.example                # 配置模板（复制为 .env；各 key 见 server_py/README）
├── server_py/                  # 后端引擎（多能力分流 + 各 provider + 服务端）  → 详见其 README
├── client_py/                  # Python 终端客户端                            → 详见其 README
├── client_flutter/             # Flutter 语音客户端                           → 详见其 README
└── ui_py/                      # 共享呈现层（server_py 与 client_py 复用）
    ├── presenter.py            # Presenter 抽象 + PlainPresenter 兜底
    ├── terminal.py             # TerminalPresenter（聊天气泡风格）
    └── layout.py               # CJK 宽度/折行/画框（无副作用纯函数）
```

---

## 快速开始

```bash
# 1) 环境（仓库根目录）
python -m venv .venv
#   激活：Windows PowerShell .venv\Scripts\Activate.ps1 ；Git Bash source .venv/Scripts/activate ；*nix source .venv/bin/activate
pip install -r requirements.txt          # 跑测试再加 -r requirements-dev.txt

# 2) 配置密钥（缺哪个 key 就自动不启用哪个能力；GEMINI_API_KEY 必需）
cp .env.example .env                      # 然后编辑 .env，各能力 key 说明见 server_py/README §3 / §8.4
```

两种运行形态（命令都在仓库根目录执行）：

```bash
# A. 单机直连（无网络、最快上手）：进程内直接调 Dispatcher
python server_py/chat_app.py

# B. client-server：PC 起服务端，再用 Python 或 Flutter 客户端连
python server_py/serve.py                 # 监听 0.0.0.0:8000，控制台打印局域网地址
python -m client_py                       # Python 终端客户端（默认连 127.0.0.1:8000）
#   Flutter 客户端见 client_flutter/README.md
```

- 后端引擎设计（多能力分流、各 provider 接入、测试、打包）：[`server_py/README.md`](server_py/README.md)
- HTTP 契约、CS 架构与鉴权：server_py/README §8.10
