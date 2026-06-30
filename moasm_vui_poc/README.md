# TripNow Engine Python 接入客户端

对 [TripNow Engine](https://tripnowengine.133.cn)（航班管家行程引擎）的 Python 封装。
把"**两种接入方式**"与"**公开 / 个人信息操作**"拆成正交的两层，命令行优先，
但分层设计使其易于迁移到 GUI、服务端或其他语言。

---

## 1. 本质功能

TripNow Engine 对外只有一个核心能力：**OpenAI 兼容的对话补全**
（`chat/completions`）。所有出行场景都通过自然语言 query 触发，引擎内部自行选择
工具（查火车票 / 机票 / 余票 / 动态 / 车站大屏 / 个人行程…），并可选返回结构化数据。

围绕这个核心，存在两个正交的维度：

| 维度 | 取值 | 区别 |
|------|------|------|
| **接入方式**（传输） | OpenAPI / MCP | 协议封装不同，能力等价 |
| **信息归属**（业务） | 公开 / 个人 | 是否携带 `union_id` |

- **公开信息**：上海到北京的机票、某车次余票、航班动态等。无需身份，纯读。
- **个人信息**：我购买/关注的行程、订阅提醒等。需 `union_id`（OAuth 获取）。
- `include_data=true` 时，结构化数据放在响应的 `choices[].model_data`。

---

## 2. 架构设计

### 2.1 分层

```
┌─────────────────────────────────────────────┐
│ 表现层   cli.py                               │  解析参数 → 装配 → 调用 → 打印
├─────────────────────────────────────────────┤
│ 业务层   services/                            │  公开 vs 个人（是否带 union_id）
│   ├ PublicTravelService    （无 union_id，读）│
│   └ PersonalTravelService  （带 union_id，增/查）│
├─────────────────────────────────────────────┤
│ 传输层   transport/                           │  接入方式可插拔
│   ├ TripNowTransport  (抽象接口)              │
│   ├ OpenApiClient     (REST，支持流式)         │
│   └ McpClient         (JSON-RPC，含 prompts)   │
├─────────────────────────────────────────────┤
│ 模型层   models.py                            │  ChatRequest / ChatResponse（协议契约）
├─────────────────────────────────────────────┤
│ 配置     config.py    Settings + build_transport()
└─────────────────────────────────────────────┘
```

### 2.2 关键设计点

- **依赖倒置**：业务层只依赖抽象 `TripNowTransport`，不知道底层是 REST 还是
  JSON-RPC。切换接入方式只改 `config.build_transport()` 一处。
  （类比 Android：`TripNowTransport` ≈ Retrofit `interface`，
  `OpenApiClient`/`McpClient` ≈ 两个实现，`build_transport` ≈ DI 注入点。）
- **正交分解**：接入方式（下层）与信息归属（上层）互不耦合。
  4 种组合（openapi/mcp × public/personal）零额外代码自然成立。
- **能力探测**：流式、prompts 管理是传输方言。流式用
  `transport.supports_stream` + `UnsupportedFeatureError` 表达；prompts 用
  `PromptsCapable` Protocol（仅 MCP 实现），避免污染通用接口。
- **协议契约集中在 `models.py`**：迁移到其他语言时，照搬这层的数据结构即可。
- **边界防御**：HTTP 状态、JSON-RPC error、MCP 结果结构未定等，全部在传输层
  转成统一的 `TripNowError` 子类；业务/表现层只 catch `TripNowError`。

### 2.3 接入方式对照

| | OpenAPI | MCP |
|---|---|---|
| 端点(prod) | `/tripnow/v1/chat/completions` | `/tripnow/v1/mcp` |
| 端点(test) | `/test/tripnow/v1/chat/completions` | `/test/tripnow/v1/mcp` |
| 协议 | REST，OpenAI 兼容 | JSON-RPC 2.0，`tools/call` 包裹 |
| 鉴权 | `Authorization: Bearer sk-xxxx`（两者复用同一套 API Key） | |
| 流式 | ✅ `stream=true` | ❌ 强制非流式 |
| prompts 管理 | ❌ | ✅ `get/update_agent_intents_prompts` |

---

## 3. 环境准备（PyCharm + venv）

```bash
# 1. 创建虚拟环境
python -m venv .venv

# 2. 激活
#   Windows (PowerShell): .venv\Scripts\Activate.ps1
#   Windows (bash/Git Bash): source .venv/Scripts/activate
#   macOS/Linux:           source .venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置密钥
cp .env.example .env   # 然后编辑 .env 填入 TRIPNOW_API_KEY
```

> PyCharm：`File → Settings → Project → Python Interpreter → Add → Existing → .venv`，
> 会自动加载 `.env`（也由代码内的 python-dotenv 兜底加载）。

---

## 4. 使用方法

### 4.1 命令行

```bash
# 公开信息（无需 union_id）
python server_py/main.py ask "查询明天北京到上海的火车票"
python server_py/main.py ask "CZ3427航班今天的预计到达时间"
python server_py/main.py ask "查询明天北京到上海的机票" --stream      # 流式，仅 openapi

# 个人信息（需 union_id）
python server_py/main.py trips --union-id 0cQnX8ZTcizSwT15AqQY2rqe8
python server_py/main.py me "查一下我的行程有没有更新状态" --union-id xxxx
python server_py/main.py subscribe "关注今天D7561次广州到深圳北的一等座" --union-id xxxx

# prompts 管理（仅 mcp）
python server_py/main.py --transport mcp prompts get
python server_py/main.py --transport mcp prompts set '[{"scenario":1,"prompt":"..."}]'

# 全局开关
python server_py/main.py --transport mcp --env prod ask "..."
python server_py/main.py ask "..." --no-data         # 不返回结构化数据
```

### 4.2 作为库调用

```python
from tripnow_client import Settings, build_transport, PublicTravelService

settings = Settings.from_env()              # 或 Settings(api_key="sk-...", transport="mcp")
transport = build_transport(settings)
try:
    public = PublicTravelService(transport, model=settings.model)
    resp = public.ask("查询明天北京到上海的机票")
    print(resp.content)                     # 自然语言回复
    print(resp.model_data)                  # 结构化数据（include_data 默认开）
finally:
    transport.close()
```

切换接入方式只需 `settings.transport = "mcp"`，业务代码一行不改。

### 4.3 获取 union_id（OAuth）

文档流程：访问航班管家侧配置好的授权 URL → 登录 → 重定向回我方页面，
URL 中带 `union_id`。CLI 场景下把最终重定向 URL 粘贴给辅助函数解析：

```python
from tripnow_client import extract_union_id
union_id = extract_union_id("https://官网?union_id=xxxx&...")
```

测试账号（郑炜雄）union_id：见 `init_docs` 文档。

---

## 5. 目录结构

```
moasm_vui_poc/                  # 仓库根（.git 在此）
├── README.md / .gitignore
├── requirements.txt / requirements-dev.txt
├── pytest.ini                  # testpaths=server_py/tests；pythonpath=. server_py
├── .env.example                # 配置模板（复制为 .env）
├── init_docs/                  # 官方接入文档（PDF/DOCX/PNG）
│
├── ui/                         # 共享呈现层（server_py 与 client_py 复用，故置于根，见 §8.9）
│   ├── presenter.py            # Presenter 抽象 + PlainPresenter 兜底
│   ├── terminal.py             # TerminalPresenter（聊天气泡风格）
│   └── layout.py               # CJK 宽度/折行/画框（无副作用纯函数）
│
├── server_py/                  # 后端引擎：多能力分流 + HTTP 服务端（内部用扁平绝对导入）
│   ├── main.py                 # TripNow 单 provider CLI 入口
│   ├── chat_app.py             # 入口①：本地多能力 CLI（交互/单轮，见 §8）
│   ├── serve.py                # 入口②：HTTP 服务端（复用同一 Dispatcher，见 §8.10）
│   ├── run_cases.py            # 批量回归 demo（真实网络调用）
│   ├── tripnow_client/         # provider：出行（OpenAPI / MCP 双传输）
│   │   ├── config.py           # Settings + build_transport（接入方式开关）
│   │   ├── models.py           # ChatRequest / ChatResponse 等协议契约
│   │   ├── errors.py           # 统一异常体系
│   │   ├── cli.py              # 命令行表现层
│   │   ├── transport/          # 传输层：base(抽象+PromptsCapable) / openapi(REST+SSE) / mcp(JSON-RPC)
│   │   └── services/           # 业务层：public(无 union_id) / personal(带 union_id) / oauth
│   ├── kuaidi100_client/       # provider：快递查询（MD5 签名 REST）
│   ├── amap_client/            # provider：高德地图（REST 默认 / A2A 可切，见 §8.8）
│   ├── tencent_news_client/    # provider：腾讯新闻（官方 Skill/CLI 子进程封装）
│   ├── music163/               # provider：网易云音乐
│   ├── routing/                # 顶层编排（分流）层，依赖各 provider
│   │   ├── handler.py          # Handler(ABC) / RouteContext / RouteResult / IntentSpec
│   │   ├── classifier.py       # GeminiClassifier + KeywordClassifier 兜底
│   │   ├── dispatcher.py       # 分类 → 选 Handler → 执行
│   │   ├── gemini.py           # Gemini REST 客户端（分类 + 闲聊）
│   │   ├── factory.py          # build_dispatcher：按 env 装配可用能力
│   │   └── handlers/           # 各 provider 的薄适配器（tripnow/kuaidi100/amap/tencent_news/chitchat）
│   ├── server/                 # client-server 服务端适配层（见 §8.10）
│   │   ├── service.py / session.py / auth.py(mock凭证) / schemas.py / http_server.py
│   └── tests/                  # pytest（129 用例，网络/子进程全 mock）
│
├── client_py/                  # Python 终端客户端（HTTP 连 server_py，复用根级 ui/）
└── client_flutter/             # Flutter 客户端（手机端）
```

---

## 6. 迁移指引

- **改 GUI**：替换 `cli.py`，复用 `services/` 及以下所有层。
- **换语言/平台**：照搬 `models.py` 的协议契约 + `transport` 的两种封装规则。
- **加新接入方式**：实现 `TripNowTransport`，在 `build_transport` 注册即可。

---

## 7. 已知注意点

- **`union_id` 字段名不一致**：官方参数表与 MCP 文档用 `union_id`，
  个人行程示例 JSON 用 `unionId`。本库默认发 `union_id`，
  如后端只认 `unionId`，改 `models.py` 顶部的 `UNION_ID_KEY` 一处即可。
- **MCP 不支持流式**：对 MCP 调用 `--stream` 会抛 `UnsupportedFeatureError`。
- **MCP 结果结构**：官方文档未给出 `tools/call` 返回体细节，
  `mcp.py` 对三种可能形态做了兼容解析；若实际格式不同，调整 `_extract_completion`。

---

## 8. 多能力分流（闲聊 / TripNow / 快递100 / 高德）

`tripnow_client` 只是其中一个 provider。当要把多个能力（出行、快递、地图、闲聊）
组合成一个对话入口时，需要在它们**之上**再加一层"分流"。这层独立成顶层包
`routing/`，**不**塞进任何一个 provider —— 因为 provider 之间必须互不依赖。

### 8.1 整体结构

```
┌───────────────────────────────────────────────┐
│ chat_app.py                 总流程 demo 入口     │
├───────────────────────────────────────────────┤
│ routing/                    顶层编排（分流）层    │
│   ├ Dispatcher              分类 → 选 Handler → 执行
│   ├ IntentClassifier        Gemini 分类，关键词兜底
│   ├ Handler (ABC)           每个能力自带 intent+description
│   ├ handlers/               各 provider 的薄适配器
│   └ factory.build_dispatcher()  按 env 装配可用能力
├───────────────────────────────────────────────┤
│ provider 层（互不依赖，各自独立文件夹）            │
│   ├ tripnow_client/      出行（OpenAPI / MCP 双传输）│
│   ├ kuaidi100_client/    快递（MD5 签名 REST）       │
│   ├ amap_client/         高德地图（Google A2A 协议）  │
│   └ tencent_news_client/ 腾讯新闻（官方 Skill/CLI 封装）│
└───────────────────────────────────────────────┘
```

### 8.2 一个核心判断：每个 provider 算几个"意图"？

| Provider | 意图数 | 原因 |
|---|---|---|
| 高德 | 1（`amap`） | 对外单一入口；后端可切（默认 REST，见 §8.8），`MapService` 接口屏蔽差异 |
| 快递100 | 1（`express_tracking`） | 查物流是单一动作，快递公司识别在 service 内部完成 |
| TripNow | 2（`tripnow_public` / `tripnow_personal`） | 引擎虽也做内部路由，但**是否带 `union_id`** 是身份分叉，下游模型无法自判，必须在路由层显式拆开 |
| 腾讯新闻 | 2（`tencent_hot_news` / `tencent_weather`） | 仅保留结构化、联网检索难替代的两项：全国热点榜 + 多天天气预报。主题新闻搜索/流言核查本身偏弱，已下线，交给闲聊联网检索（见 §8.5） |
| 闲聊 | 1（`chitchat`） | 兜底意图，走 Gemini；并开启 Google Search grounding，可联网回答实时/最新类问题（股价、汇率、最新消息等），由模型自行判断是否检索 |

> 结论：分流层只在"下游 agent 无法自行决定"的地方切分意图；能交给 provider
> 内部判断的，统统合成一个意图，避免分类器越权。能由闲聊联网检索覆盖且本身较弱的
> 第三方能力，也不必单列意图。

### 8.3 "灵活增加能力"如何做到

每个 `Handler` 自带 `intent`（唯一 id）和 `description`（自然语言）。
分类器的提示词是**从已注册 handlers 动态拼出来的**，自身不写死任何业务意图。
所以新增一个能力 = 写一个 `Handler` + 注册，**分类器和分发器零改动**：

```python
from routing import build_dispatcher, RouteContext, Handler, RouteResult

class WeatherHandler(Handler):
    intent = "weather"
    description = "查询天气预报"
    def handle(self, query, context) -> RouteResult:
        return RouteResult(text="晴，25℃", intent=self.intent)

dispatcher = build_dispatcher(extra_handlers=[WeatherHandler()])
```

（类比 Android：`Handler` ≈ 实现某 `interface` 的策略对象，`Dispatcher` ≈ 持有
策略表的 `ViewModel`，新增策略不动分发逻辑，就是开闭原则。）

### 8.4 运行总流程 demo

```bash
# .env 里按需配置（缺哪个 key 就自动不启用哪个能力；GEMINI_API_KEY 必需）
#   GEMINI_API_KEY                       —— 意图分类 + 闲聊兜底（硬依赖）
#   TRIPNOW_API_KEY                      —— 启用出行能力
#   KUAIDI100_KEY / KUAIDI100_CUSTOMER   —— 启用快递查询
#   AMAP_KEY                             —— 启用高德地图
#   TENCENT_NEWS_API_KEY                 —— 启用腾讯新闻（需先装 tencent-news-cli，见 §8.7）

python server_py/chat_app.py                          # 交互模式
python server_py/chat_app.py "深圳北到广州的高铁"        # 单轮：命中 tripnow_public
python server_py/chat_app.py --show-intent "附近的咖啡"  # 打印命中意图：amap
python server_py/chat_app.py "查下 SF1234567890 到哪了"  # 命中 express_tracking
python server_py/chat_app.py --union-id xxxx "我的行程"  # 命中 tripnow_personal
python server_py/chat_app.py "今天有什么大新闻"          # 命中 tencent_hot_news
python server_py/chat_app.py "深圳明天下雨吗"            # 命中 tencent_weather
python server_py/chat_app.py "看下 apple 公司的股价"     # 命中 chitchat，自动联网检索后作答
```

链路：`用户输入 → Dispatcher.classify（Gemini 分类，失败/非法回退关键词）
→ 选中 Handler → 调对应 provider（各自内部再做场景/工具路由）→ 统一 RouteResult`。

### 8.5 分类器的两级兜底

- **GeminiClassifier**：用 Gemini 按 description 选意图，鲁棒、能理解口语。
- **KeywordClassifier**：零依赖关键词规则；当 Gemini 不可用或输出非法 id 时回退，
  保证离线/降级场景仍可用。

闲聊兜底（`ChitchatHandler`）开启了 **Google Search grounding**：请求里挂上
`tools:[{"google_search":{}}]`，**是否真去联网由模型自行判断**——"1+1等于几"不会触发，
"apple 股价 / 黄金价格 / 最新消息"等时效性问题才会检索，搜后基于网页作答并回传来源
（在回复末尾以"来源（联网检索）"列出）。这也是上面把腾讯新闻搜索/流言核查下线的底气：
它们的活由闲聊联网检索更新、更广地覆盖。实现见 `GeminiClient.answer(grounded=True)`。
- 二者都拿不准 → 落到 `default_intent="chitchat"`。

### 8.6 各 provider 接入要点

- **快递100**：实时查询签名 `sign = MD5(param + key + customer).upper()`，
  form 表单 POST；单号所属快递公司可先 `autodetect` 自动识别。
- **高德**：两种后端共用一个 `MapService` 接口、同一把 `AMAP_KEY`，由 `AMAP_BACKEND` 选择（见 §8.8）：
  - **REST（默认）**：Web 服务 REST API（`restapi.amap.com/v3/place/around|text`），GET + query 参数，
    返回结构化 JSON 自行解析，约定 `status=="1"` 为成功；`extensions=all` 取评分/营业时间等富字段。
  - **A2A（保留对比）**：Google A2A 协议，JSON-RPC 2.0，header `key: <AMAP_KEY>`，
    `method=message/send`，消息体是 A2A `Message`(role+parts[])，
    返回可能是 `Message` / `Task(status.message)` / `artifacts`，已做兼容提取。
- **腾讯新闻**：官方**不提供直连 REST**，唯一接入面是 Skill/CLI（`tencent-news-cli`）。
  本库把 CLI 当作"外部能力的传输层"：`subprocess` 调它、收 stdout，API Key 通过
  子进程环境变量 `TENCENT_NEWS_API_KEY` 注入。安装与三端运行见 §8.7。

### 8.7 腾讯新闻：安装 CLI 与三端运行

接入文档：<https://news.qq.com/exchange?scene=appkey>（在该页生成 API Key）。

**第一步：安装 CLI**（官方提供三端安装脚本，任选其一）

```bash
# macOS / Linux
curl -fsSL https://mat1.gtimg.com/qqcdn/qqnews/cli/hub/tencent-news/setup.sh | sh

# Windows (PowerShell)
irm https://mat1.gtimg.com/qqcdn/qqnews/cli/hub/tencent-news/setup.ps1 | iex

# 任意平台（需 Node）
npm i @tencentnews/cli@latest -g
```

**第二步：配置 API Key**（在文档页生成后执行；本库另会用 env 注入，二者不冲突）

```bash
tencent-news-cli apikey-set <你的API_Key>
```

**第三步：在 `.env` 里启用**

```ini
TENCENT_NEWS_API_KEY=<你的API_Key>     # 必填，缺失则该能力不启用
TENCENT_NEWS_CLI=                       # 可选，默认 tencent-news-cli；也可填启动器
TENCENT_NEWS_DEFAULT_ADCODE=            # 可选，天气默认行政区划码（默认 440300 深圳）
```

当前启用两个意图：`hot`（全国热点榜，无参）/ `weather --adcode <码>`（多天预报）。CLI 另有
`search "<词>"`（主题搜索）与 `jiaozhen --query`（流言核查）两个子命令，因能力偏弱已不接入
（对应 Handler 类仍在 `tencent_news.py`，将来需要时在 `factory._try_add_tencent_news` 里重新注册即可）。

**三端通跑说明**：本库的 Python 层是纯 `subprocess`（强制 UTF-8、不走 shell、无硬编码路径），
本身 mac/windows/linux 全平台一致。唯一与平台相关的是"装哪份 CLI 可执行"——官方上面三条
脚本已覆盖三端。**一个 Windows 坑**：用 `npm` 装时全局命令是 `tencent-news-cli.cmd` 批处理
垫片，Windows 的 `CreateProcess` 不能直接执行 `.cmd`（而把用户 query 经 `cmd /c` 转发又会引入
命令注入面，故本库刻意不这么做）。因此 **Windows 建议用上面的原生 `setup.ps1`**（落地真实
可执行，`subprocess` 可直接拉起）；若坚持走 npm，则把启动器指到 node 脚本本体即可避开 `.cmd`：

```ini
TENCENT_NEWS_CLI=node C:\Users\<you>\AppData\Roaming\npm\node_modules\@tencentnews\cli\bin\cli.js
```

### 8.8 高德后端切换（REST / A2A）

高德对上层只暴露 `MapService.ask(query, location) -> MapResult` 一个接口，`AmapHandler` 只依赖它。
两种实现可经 `AMAP_BACKEND` 自由切换、对比，无需改 handler/分流层：

| 取值 | 实现 | 特点 |
|---|---|---|
| `rest`（**默认**） | `RestMapService` + `AmapRestClient` | 直连 Web 服务 REST（`/v3/place/around\|text`），结构化、可控；由 `QueryParser` 把自然语言拆成 关键词+地点，指定地点先定位成坐标再周边搜 |
| `a2a` | `A2aMapService` + `AmapClient` | 旧的 ai_native 智能体，云端 agent 自做场景路由；NL 理解更强，但黑盒、返回结构松散 |

```ini
AMAP_BACKEND=       # 留空=rest（默认）；填 a2a 切回旧实现做对比
```

切换只动这一个 env，两套实现都在 `amap_client/` 里保留，`build_service` 按配置装配。

REST 后端的自然语言理解靠注入的 `QueryParser`（接口在 `amap_client/parser.py`）：
默认 `NaiveQueryParser`（整句当关键词、仅默认坐标）；分流层注入的
`GeminiMapQueryParser`（`routing/handlers/amap.py`）用 Gemini 把"深圳万科云城附近好吃的推荐"
拆成 `keywords=美食 / near=深圳万科云城 / city=深圳`，先把地标定位成坐标，再据此周边搜——
这样 REST 后端也能正确处理"给定地址"，而非只会用默认坐标。`amap_client` 不依赖 Gemini，
解析能力经接口注入。

### 8.9 呈现层（UI）与分流层解耦

输出样式独立成 `ui/` 包，与 routing/业务层解耦：routing 只产出 `RouteResult`，"长什么样"
由呈现层决定。换 UI（更花哨的 TUI、未来的 GUI/Web）= 新增一个实现 `Presenter` 接口的类，
分流与业务代码零改动。

- `ui/presenter.py`：`Presenter` 抽象接口（`banner` / `info` / `show_input` / `show_output`
  / `log_formatter`）；含一个朴素的 `PlainPresenter` 兜底实现。
- `ui/terminal.py`：`TerminalPresenter`，聊天气泡风格（左/右对齐、ANSI 上色、Windows 自动启用 VT）。
- `ui/layout.py`：CJK 宽度、按显示宽度折行、画框，均为无副作用纯函数（已单测）。
- 入口 `chat_app.py` 只依赖 `Presenter` 接口，不关心具体实现。
- **日志区**：路由调试日志由 `logging` 在 dispatch() 内实时打印，时间上正好落在 `show_input`
  与 `show_output` 之间；`Presenter.log_formatter()` 决定其样式（缩进+变暗），`setup_logging`
  接收该 formatter——"日志打不打"是 routing 的事，"长什么样"是 UI 的事。

### 8.10 client-server 模式（PC 当服务端，手机当客户端）

在**不改动现有 demo**（routing / ui / 各 provider / chat_app）的前提下新增的运行模式：
给同一个 `Dispatcher`（业务"大脑"）套一层服务端适配器。`chat_app.py` 与 `serve.py`
是两个平级入口，复用同一套 `build_dispatcher()`。

```bash
python server_py/serve.py                 # 监听 0.0.0.0:8000，同一 WiFi 下手机可访问
python server_py/serve.py --port 9000 --debug
python server_py/serve.py --token <密钥>   # 开启 Bearer 鉴权（公网/阿里云建议开）
```

启动后控制台会打印**局域网地址**（如 `http://192.168.x.x:8000`），手机填这个即可。

**HTTP 契约**

```
GET  /health  ->  { "status": "ok", "capabilities": ["chitchat", "amap", ...] }
POST /chat
  请求体: { "query": "深圳万科云城附近好吃的", "session_id": "<客户端生成并固定>",
           "user_id": "可选，我方平台账号", "location": "经度,纬度 可选" }
  响应  : { "text": "...", "intent": "amap", "session_id": "..." }
  鉴权(可选): 请求头 Authorization: Bearer <SERVER_AUTH_TOKEN>
```

phase 1 只下发 `text + intent`，结构化 `RouteResult.data`（POI/轨迹等）暂不序列化。

**分层（`server/` 包，全部是加法）**

| 文件 | 职责 |
|---|---|
| `server/service.py` | `ChatService`：框架无关核心，复用 `build_dispatcher()`；取凭证 → 注入会话历史 → dispatch → 记历史 |
| `server/session.py` | `SessionStore`：每个 `session_id` 一份独立历史（纯内存、互不干扰），配 per-session 锁串行化同会话并发 |
| `server/auth.py` | 三方个人数据凭证的获取（见下） |
| `server/schemas.py` | 请求/响应数据契约 + 校验 |
| `server/http_server.py` | 标准库 `ThreadingHTTPServer` 适配器；迁阿里云若要异步/流式可整体换 FastAPI，core 不动 |
| `serve.py` | 启动入口 |

**鉴权（当前 mock，已预留接真鉴权的接口）**

抽象：客户端引导用户去三方 OAuth 登录 → 三方回 key/token → 我方按"平台用户账号"把 token
存云端 → 需要时按账号查出来 → 用它访问该用户的三方个人数据。这套对几乎所有三方通用，
当前整体 mock：

- `CredentialProvider`（接口）→ `MockCredentialProvider`（假装已授权，复用 CLI 同款测试账号
  `TRIPNOW_UNION_ID` 作为"拿到的 key"）。mock 执行时打日志 `[我们mock了鉴权过程, 假装拿到了key]`。
- 将来接真鉴权 = 新增 `CloudCredentialProvider`（按 `user_id` 去存储查真实 token），
  `ChatService` 只依赖 `CredentialProvider` 接口，无需改动。

**迁阿里云的后续项**（你给地址后）：强制开 `SERVER_AUTH_TOKEN` + nginx/HTTPS；
provider 的 `requests.Session` 在高并发下的连接池；dispatch 阻塞较久（单轮数秒），
可评估流式输出。

---

## 9. 测试（pytest）

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # 全量 129 个用例，全部 mock 掉网络/子进程
```

覆盖：模型解析、公开/个人业务层、两种传输、配置；快递签名/识别、高德 A2A 与
REST 两后端（含查询解析/地点定位）；分流层的关键词/Gemini 分类、分发器、各 Handler（含降级路径）；
UI 布局纯函数（宽度/折行/画框）；会话记忆滑动窗口/落盘往返/容错；
服务端 ChatService/会话隔离/schema 校验/HTTP 适配器（真起本地 server，含鉴权）。
- **API Key 安全**：放 `.env`，不要提交到版本库（已建议加入 `.gitignore`）。

**批量回归 demo**（会发起真实网络调用，需 `.env` 配好各 key）：

```bash
python server_py/run_cases.py          # 逐条跑全部 demo 用例，打印 输入/命中意图/输出，末尾给逐条与汇总 pass
```

---

## 10. 打包成 exe 分发给同事

把整个 Python 程序打成单个 `.exe`，同事无需装 Python/Node，拿到 exe + 自己的 `.env` 即可运行。

### 10.1 打包步骤

```bash
pip install pyinstaller

# 1) 准备打进包的配置（避免污染开发用的根目录 .env）
mkdir -p _build_env && cp .env _build_env/.env

# 2) 在项目根目录执行（Windows）
python -m PyInstaller --onefile --name tripnow-chat \
  --add-binary "tencent-news-cli.exe;." \
  --add-data "_build_env/.env;." \
  --clean -y chat_app.py
```

- `--onefile`：打成单文件，方便分发
- `--add-binary "tencent-news-cli.exe;."`：把腾讯官方原生二进制打进包内（`;` 左边是源文件、
  右边 `.` 是包内目标目录）。运行时 `tencent_news_client/config.py` 会自动从解包目录
  (`_MEIPASS`) 或 exe 同级目录找到它，无需 PATH 或额外安装
- `--add-data "_build_env/.env;."`：把全部配置（含各 key、`ROUTING_LOG_LEVEL` 等）打进包内，
  **同事零配置直接双击运行即可启用全部能力**。`chat_app._load_env` 启动时先读包内 `.env`，
  再读 exe 同级目录的 `.env`（若存在）覆盖之——所以同事仍可放一份外部 `.env` 改某项，无需重新打包
- 产物在 `dist/tripnow-chat.exe`（约 20 MB）

> **安全提醒**：把 `.env` 打进 exe = key 随包分发，拿到 exe 的人可从包里提取出明文 key。
> 仅适合内部同事试用；对外/正式发布时不要内置 key，改回"外部 `.env` 随包"模式。

> macOS/Linux 上 `--add-binary` / `--add-data` 的分隔符是 `:`（不是 `;`），且要换成对应平台的
> `tencent-news-cli` 原生二进制。

### 10.2 exe 用法

和源码版 `chat_app.py` 完全一致：

```bash
tripnow-chat.exe                         # 连续对话循环（默认；多轮，记忆最近 30 轮）
tripnow-chat.exe "看一下深圳的天气"        # 把这句作为第一轮，回答后仍留在循环里
tripnow-chat.exe --show-intent "附近的川菜馆"
tripnow-chat.exe --union-id <id> "我的行程"
tripnow-chat.exe --once "看一下深圳的天气"  # 只回答一轮即退出（脚本/管道用）
tripnow-chat.exe --no-memory "..."        # 本次不读写历史
tripnow-chat.exe --reset-memory           # 清空已存历史
tripnow-chat.exe --debug "..."            # 打开路由调试日志
tripnow-chat.exe --no-color "..."         # 关闭彩色（仅保留框线）
```

**默认进入连续对话循环**：无论是否在命令行带了初始提问，回答后都停留在 `你>` 提示符
继续对话，输入 `exit` / `quit` 退出（与 exe 双击运行的体验一致）。只有显式加 `--once`
才是"答一轮就退"，供脚本/管道调用。

**启动用法说明**：进入循环时会先打印一段"使用说明"框，列出当前已接入的各项能力及其
用途（内容由各能力的真实描述自动生成，新增/移除能力会自动同步），并说明其余对话由
闲聊兜底。

输出采用聊天气泡风格：**用户输入靠左、AI 回复靠右**，各自用框线圈出；`--debug` 时
路由日志以变暗、缩进的形式夹在两者中间（一眼可与输入/输出区分），便于在纯终端里
也有较好的交互观感。框线只用 GBK 也含的单线制表符，Windows 中文控制台不会乱码。

### 10.3 配置文件注意事项（重点）

1. **配置加载顺序（打包后）**：先读包内 `.env`（打包时一并打进去的默认配置），再读 exe
   同级目录的 `.env`（若存在）覆盖之。所以：
   - 内部试用：按 §10.1 把 `.env` 打进包，同事**零配置直接运行**即可用全部能力；
   - 想临时改某项（如换 key、关日志）：在 exe 旁放一份 `.env` 覆盖，**无需重新打包**。
   ```
   随便哪个文件夹/
     ├─ tripnow-chat.exe   ← 已内置一份默认 .env
     └─ .env               ← 可选；放了就覆盖内置值
   ```
2. **内置 key 的安全边界**：把 `.env` 打进 exe 后，key 会随包分发、可被从包内提取明文。
   仅适合内部同事试用；对外/正式发布请勿内置 key，改用"外部 `.env` 随包"。
3. **key 缺哪个就少哪个能力**：`GEMINI_API_KEY` 必填（否则无法分类/闲聊）；其余 key 缺失
   只是对应能力不启用，程序仍能跑。启动"使用说明"框会如实反映当前实际启用的能力。
4. **会话历史落在使用者机器**：`~/.tripnow/history.json`，记忆最近 30 轮、自动滚动；与 key
   无关，无需配置。`--no-memory` 关闭、`--reset-memory` 清空。
5. **中文控制台**：程序已对输出做 `errors="replace"` 处理，遇到天气里的 emoji 等非 GBK 字符
   不会崩溃（显示为占位符）；想完整显示可在 Windows Terminal 或 `chcp 65001` 的 UTF-8
   控制台运行。
