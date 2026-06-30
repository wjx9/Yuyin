# client_py · Python 客户端（client-server 客户端）

把 `chat_app.py` 的"本地直连 Dispatcher"换成"HTTP 调远端 `serve.py`"，其余体验尽量保持一致。
是 Flutter 端的"参照实现"：先用 Python 把 CS 链路跑通、把 HTTP 契约固定下来。

```
你的输入 → POST /chat 给 serve.py → 服务端跑同一个 Dispatcher（大脑）
        → 返回 { text, intent } → 本地用同一套聊天气泡渲染
```

## 跑起来

先在 PC 上启动服务端（工程根目录）：

```bash
python serve.py            # 监听 0.0.0.0:8000
```

再开客户端（默认连 `127.0.0.1:8000`）：

```bash
python -m client_py                         # 交互模式（多轮）
python -m client_py "深圳到北京怎么最舒服?"   # 单轮
python -m client_py --show-intent "附近咖啡"  # 回复前打印命中意图
python -m client_py --server http://192.168.1.5:8000   # 指向局域网服务端
python -m client_py --token <密钥> "你好"     # 服务端开了 Bearer 鉴权时带上
```

批量回归（对标根目录 `run_cases.py`，逐条跑全部 demo 用例）：

```bash
python -m client_py.run_cases
python -m client_py.run_cases --server http://192.168.1.5:8000
```

## 与单机版（chat_app.py / run_cases.py）的差别

只有两点，都是 CS 架构的必然：

1. **多轮历史在服务端**按 `session_id` 维护，客户端只固定带同一个 `session_id`；
   `run_cases` 全程共用一个 session，从而复现"闲聊记忆"多轮用例。
2. **路由调试日志在服务端打**，客户端中间不再有"夹在输入输出之间的日志区"。

判定标准、用例集与单机版完全一致（命中意图匹配 + 可选 `expect_contains` 内容校验 +
期望意图未启用记 SKIP）。

## 配置（CLI 优先，其次 .env，再次内置默认）

| 项 | CLI | 环境变量 | 默认 |
|---|---|---|---|
| 服务端地址 | `--server` | `SERVER_URL` | `http://127.0.0.1:8000` |
| 鉴权密钥 | `--token` | `SERVER_AUTH_TOKEN` | 无（不鉴权） |
| 位置坐标 | `--location` | `DEMO_LOCATION` | `113.92,22.53`（深圳南山） |
| 会话 id | `--session` | `CLIENT_SESSION_ID` | 随机生成 |
| 平台账号 | — | `CLIENT_USER_ID` | `mock-user` |

## 分层（与 server/ 对称）

```
client_py/
  config.py     客户端配置（地址/鉴权/位置/session_id）
  client.py     ServerClient：唯一懂 HTTP 契约的地方（health / chat）
  app.py        交互式 / 单轮 CLI，复用 ui.TerminalPresenter（同款聊天气泡）
  run_cases.py  批量回归，对标根目录 run_cases.py
```
