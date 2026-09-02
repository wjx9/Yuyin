# server_py — 多能力分流后端引擎

> 本目录是 moasm_vui_poc 的**后端引擎（大脑）**：把多个第三方能力用一层 **Gemini 意图分流**
> 编排成单一对话入口，并以 `serve.py` 暴露 HTTP 给 `client_py` / `client_flutter`。
> 项目总览与各部署单元见 [`../README.md`](../README.md)；本文聚焦后端本身。
>
> **命令默认在仓库根目录执行**（`pytest.ini` / `.env` / `requirements.txt` 都在根，
> `server_py` 内部用扁平绝对导入，运行时把仓库根加入 `sys.path`）。
> 历史原因下文 §1–§7 以 **TripNow 这一个 provider** 为最完整的接入样板讲解，
> **§8 才是后端核心（多能力分流）**；§9 测试、§10 打包。

---

## 1. TripNow provider · 本质功能（接入样板）

> 注：本节及 §2–§7 讲的是 **TripNow 这一个 provider** 的接入细节——它是仓库里最完整的
> provider 实现，可作"如何接一个第三方能力"的参考样板。能力分流的全局视角请直接看 §8。

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

## 2. TripNow provider · 架构设计

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

测试账号（郑炜雄）union_id：见 `server_py/tripnow_client/init_docs/` 文档。

---

## 5. 目录结构（server_py 内部）

> 仓库整体结构（3 个部署单元 + 共享 `ui_py`）见 [`../README.md`](../README.md)。这里只列后端引擎内部。

```
server_py/                      # 后端引擎：多能力分流 + HTTP 服务端（内部用扁平绝对导入）
├── main.py                     # TripNow 单 provider CLI 入口
├── chat_app.py                 # 入口①：本地多能力 CLI（交互/单轮，见 §8）
├── serve.py                    # 入口②：HTTP 服务端（复用同一 Dispatcher，见 §8.10）
├── run_cases.py                # 批量回归 demo（真实网络调用）
├── tripnow_client/             # provider：出行（OpenAPI / MCP 双传输）
│   ├── config.py / models.py / errors.py / cli.py
│   ├── transport/              # base(抽象+PromptsCapable) / openapi(REST+SSE) / mcp(JSON-RPC)
│   ├── services/               # public(无 union_id) / personal(带 union_id) / oauth
│   └── init_docs/              # TripNow 官方接入文档（PDF/DOCX/PNG）——随其 provider
├── kuaidi100_client/           # provider：快递查询（MD5 签名 REST）
├── amap_client/                # provider：高德地图（REST 默认 / A2A 可切，见 §8.8）
├── tencent_news_client/        # provider：腾讯新闻（官方 Skill/CLI 子进程封装）
├── music163/                   # provider：网易云音乐（@music163/ncm-cli 封装，见 §8.11）
├── tools/                      # 统一工具调用层（ToolSpec/Registry/Runtime/Adapter）
├── routing/                    # 兼容路由层与现有 Handler 实现
│   ├── handler.py / classifier.py / dispatcher.py / gemini.py / factory.py
│   └── handlers/               # 薄适配器：tripnow / kuaidi100 / amap / tencent_news / chitchat
├── server/                     # client-server 服务端适配层（见 §8.10）
│   └── service.py / session.py / auth.py / schemas.py / http_server.py
└── tests/                      # pytest（165 用例，网络/子进程全 mock）

# 注：呈现层 ui_py/ 在仓库根（server_py 与 client_py 共享），见 ../README.md 及 §8.9。
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

## 8. 多能力分流（闲聊 / TripNow / 快递100 / 高德 / 腾讯新闻 / 网易云音乐）

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
| 腾讯新闻 | 3（`tencent_hot_news` / `tencent_news_search` / `tencent_weather`） | 全国热点榜、指定对象新闻（地区/分类/主题，检索词+条数由分类器随槽位一次抽出）、多天天气预报。流言核查本身偏弱，不单列，交给闲聊联网检索（见 §8.5） |
| 网易云音乐 | 2（`music_play` / `music_control`） | 点歌(搜+播)与播放控制(暂停/切歌/音量)触发语与参数形态完全不同，拆两意图比单 handler 二次分流更稳（见 §8.11） |
| 闲聊 | 1（`chitchat`） | 兜底意图，走 Gemini；并开启 Google Search grounding，可联网回答实时/最新类问题（股价、汇率、最新消息等），由模型自行判断是否检索 |

> 结论：分流层只在"下游 agent 无法自行决定"的地方切分意图；能交给 provider
> 内部判断的，统统合成一个意图，避免分类器越权。能由闲聊联网检索覆盖且本身较弱的
> 第三方能力，也不必单列意图。

### 8.3 "灵活增加能力"如何做到

每个 `Handler` 自带 `intent`（唯一 id）、`description`（自然语言），还可声明
`slots`（希望分类器顺带抽取的参数，见 §8.5）。分类器把已注册 handlers 动态编译成
function calling 的函数声明，自身不写死任何业务意图。所以新增一个能力 = 写一个
`Handler` + 注册，**分类器和分发器零改动**：

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

链路：`用户输入 → Dispatcher.classify（Gemini function calling 一次出 意图+槽位，
失败/非法回退关键词）→ 选中 Handler（槽位经 context.slots 传入）→ 调对应 provider
（各自内部再做场景/工具路由）→ 统一 RouteResult`。

### 8.5 分类即抽槽：function calling 一次调用出 意图+槽位

- **GeminiClassifier**：把每个意图编译成一个 function 声明（`description` 即函数
  说明、handler 声明的 `SlotSpec` 即参数 schema），用 Gemini function calling
  （`mode=ANY`，强制选一个函数）**一次调用**同时得到意图与槽位——相比"先分类、
  命中后再单独调一次 LLM 抽槽位"的两段式，延迟与调用成本各省一半（实测稳态
  分类+抽槽 ~1s，两段式 ~2.5s）。分类器只保证槽位**类型**正确，业务范围
  （如条数 1..50）由 handler 校验。
- **KeywordClassifier**：零依赖关键词规则；当 Gemini 不可用或输出非法 id 时回退，
  保证离线/降级场景仍可用。它只出意图不出槽位——所以**槽位契约是尽力而为**：
  handler 拿到的 `context.slots` 可能为空，必须能只凭 query 用自己的确定性解析
  （正则清洗等）兜底。这条契约写在 `routing/handler.py` 的模块 docstring。

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

高德对上层只暴露 `MapService.ask(query, location, preparsed) -> MapResult` 一个接口，`AmapHandler` 只依赖它
（`preparsed`：意图分类随槽位抽出的 `MapQuery`，REST 后端直接用、跳过内部解析；a2a 忽略）。
两种实现可经 `AMAP_BACKEND` 自由切换、对比，无需改 handler/分流层：

| 取值 | 实现 | 特点 |
|---|---|---|
| `rest`（**默认**） | `RestMapService` + `AmapRestClient` | 直连 Web 服务 REST（`/v3/place/around\|text`），结构化、可控；由 `QueryParser` 把自然语言拆成 关键词+地点，指定地点先定位成坐标再周边搜 |
| `a2a` | `A2aMapService` + `AmapClient` | 旧的 ai_native 智能体，云端 agent 自做场景路由；NL 理解更强，但黑盒、返回结构松散 |

```ini
AMAP_BACKEND=       # 留空=rest（默认）；填 a2a 切回旧实现做对比
```

切换只动这一个 env，两套实现都在 `amap_client/` 里保留，`build_service` 按配置装配。

REST 后端需要把"深圳万科云城附近好吃的推荐"拆成 `keywords=美食 / near=深圳万科云城 /
city=深圳`（先把地标定位成坐标，再据此周边搜）。主路径：这三个槽位由 `AmapHandler.slots`
声明，意图分类的 function calling **一次**顺带抽出（零额外 LLM 调用），经 `preparsed`
直通 REST 实现。降级路径（槽位为空，如关键词兜底分类）：走注入的 `QueryParser`
（接口在 `amap_client/parser.py`）——分流层注入 `GeminiMapQueryParser`
（`routing/handlers/amap.py`，提示词由同一份 SlotSpec 生成），单独用时默认
`NaiveQueryParser`（整句当关键词）。`amap_client` 不依赖 Gemini，解析能力经接口注入。

### 8.9 呈现层（UI）与分流层解耦

输出样式独立成根级 `ui_py/` 包（Python 共享层，`server_py` 的 chat_app 与 `client_py` 都复用它），
与 routing/业务层解耦：routing 只产出 `RouteResult`，"长什么样"由呈现层决定。换 UI（更花哨的
TUI、未来的 GUI/Web）= 新增一个实现 `Presenter` 接口的类，分流与业务代码零改动。

- `ui_py/presenter.py`：`Presenter` 抽象接口（`banner` / `info` / `show_input` / `show_output`
  / `log_formatter`）；含一个朴素的 `PlainPresenter` 兜底实现。
- `ui_py/terminal.py`：`TerminalPresenter`，聊天气泡风格（左/右对齐、ANSI 上色、Windows 自动启用 VT）。
- `ui_py/layout.py`：CJK 宽度、按显示宽度折行、画框，均为无副作用纯函数（已单测）。
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
GET  /health[?platform=pc|mobile]
              ->  { "status": "ok", "capabilities": ["chitchat", "amap", ...] }
POST /chat
  请求体: { "query": "深圳万科云城附近好吃的", "session_id": "<客户端生成并固定>",
           "user_id": "可选，我方平台账号", "location": "经度,纬度 可选",
           "platform": "pc|mobile 可选，缺省 pc" }
  响应  : { "text": "...", "intent": "amap", "session_id": "...",
           "data": { 可选，如音乐深链 }, "a2ui": [ 可选，A2UI v0.9 消息，见 a2ui/ ] }
  鉴权(可选): 请求头 Authorization: Bearer <SERVER_AUTH_TOKEN>
```

`platform` 用于按端过滤能力：标了 `pc_only` 的 Handler（当前只有 `music_control`——它控的是**服务端本机 mpv**，对"点歌后用深链在手机上放"的移动端无意义）对 `mobile` 隐藏，既不进 `/health` 能力清单，`/chat` 也不会路由到它。`chat_app`（进程内）与 `client_py` 走默认 `pc`、能力不变；`client_flutter` 固定上报 `mobile`。细节见 `music163/docs/introduce.md`。

phase 1 只下发 `text + intent`，结构化 `RouteResult.data`（POI/轨迹等）暂不序列化。

**A2UI 卡片（`a2ui/` 包，服务端呈现层）**：命中可卡片化意图（新闻/天气/行程）且
`platform=mobile` 时，把技能文本结果转成 A2UI v0.9 消息（`createSurface` +
`updateComponents`，根组件恒为 `id="root"` 的 `Card`）随响应 `a2ui` 字段下发，
由 client_flutter 的 genui 渲染成穿戴风格卡片（单绿/灰度/黑底，样式在客户端主题）。
本层只产语义组件不带样式；新增卡片 = 在 `a2ui/cards.py` 注册 builder，routing 零改动。
`text` 始终完整下发（TTS 与纯文本端不受影响）。

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

### 8.11 网易云音乐（@music163/ncm-cli 封装）

与腾讯新闻同构：官方执行面是本地 **CLI**（`@music163/ncm-cli`），登录(OAuth)、搜歌、
点歌、播放控制都由它在本机完成；**在线播放依赖本机 `mpv`，仅 mac/windows**。本库把它
薄封装成 `music163` provider（`subprocess` 调用，统一 `--output json`），暴露两个意图：

| 意图 | 触发示例 | 动作 |
|---|---|---|
| `music_play` | "我想听方大同的歌"、"放一首晴天" | `search song --keyword`（只搜歌曲，`data.records`）→ 取首个可播放(`visible:true`)单曲 → `play --song --encrypted-id <32hex> --original-id <num>` |
| `music_control` | "暂停"、"下一首"、"声音大一点" | 映射到 `pause/resume/stop/next/prev/volume` 子命令 |

**启用步骤（step 1：纯 PC 跑通）**

```bash
# 1) 装 CLI（Node）与播放器
npm i -g @music163/ncm-cli
#   mpv：Windows 用 scoop/choco（choco install mpv），mac 用 brew install mpv

# 2) 拿凭证：music.163.com/st/developer 实名登录 → 取 appId / privateKey，填进 .env：
#   MUSIC163_APPID=...    MUSIC163_PRIVATE_KEY=...

# 3) 在【服务端这台机器】扫码登录（OAuth，交互式，只需一次）
ncm-cli login            # 跟随二维码/链接完成授权；ncm-cli login --check 可验证
```

之后 `python server_py/chat_app.py` 里说"放首七里香"即会命中 `music_play`。

**几个实现/接入要点**

- **凭证持久化**：`appId/privateKey` 由 CLI 自己 `config set` 持久化（不读进程 env），故封装
  首次调用前自动 `config set`（幂等）；与腾讯 `apikey-set` 同思路。
- **登录无法自动化**：`ncm-cli login` 是 OAuth 扫码/链接的交互流程，必须人工在服务端机器完成。
  未登录时 `music_play` 不报错，而是提示去登录（`is_logged_in()` 用 `login --check` 探测）。
- **退出码不可靠**：CLI 逻辑失败时进程仍可能返回 0，故一律以 JSON 的 `success` 字段判定。
- **Windows 坑**：npm 全局入口是 `ncm-cli.cmd` 垫片，Python `subprocess`(不走 shell)执行不了，
  故默认改用 `node <npm全局>/@music163/ncm-cli/dist/index.js` 拉起（自动定位，见 `music163/config.py`）。
- **mpv 找不到就静默不放**：ncm-cli 在线播放依赖 mpv，且 Windows 上常不在 PATH；此时 `play`
  仍返回 rc=0 空输出（我方按成功处理）→ 报了"正在播放"却没声。故在 `.env` 配 `MUSIC163_MPV`
  指到 mpv.exe，封装会把其目录**并入本进程 `os.environ["PATH"]`**（不能只给 subprocess 传 `env=`——
  Windows 下 node 再 spawn 的 mpv 仍按本进程 PATH 查找）。真伪以 `state.status=='playing'` 为准。
- **search 需先登录**：未登录时 `search` 命令根本不在 CLI 的命令树里（登录后由服务端动态下发），
  这也是为何把"登录"作为运行期前提单列。
- **`search all` 是综合搜索**（混入歌手/专辑/歌单，它们也带 id/name 但无 `duration`），故改用
  `search song`（`data.records` 纯歌曲）并用 `duration` 区分真歌曲——否则会把"歌手周杰伦(id=6452)"
  当成歌去 `play` 而静默失败。
- **版权/可播放性**：很多热门歌 `visible:false`（版权受限/需会员），点播会落到可播放的翻唱/其它版本；
  全不可播时 `music_play` 提示"当前都不可播放"。这是网易内容侧限制，非本封装问题。
- **`play` 无回显**：动作类命令成功时 stdout 为空（rc=0），故空输出按成功处理；是否真在放以
  `state.status=='playing'` 为准（已实测真机出声）。
- **字段来源**：单曲对象字段（`encryptedId`/`originalId`/`name`/`artists`/`visible`）取自 ncm-cli 0.1.6
  实测；解析在 `music163/models.py` 一处，CLI 升级若有变只改该层。

**分阶段计划**（详见 `music163/docs/introduce.md`）：① 纯 PC（chat_app）跑通 ← 当前；
② client_py（CS）跑通；③ client_flutter(Android)，其中播放有两条路——3.1 跳转网易云音乐
app/网页、3.2 嵌入语音助手客户端内播放。CS 架构下"注册技能/搜歌"在云端、"实际播放"在客户端，
当前 step 1 的本机 mpv 播放不适用于手机端，留待 ②③。

---

## 9. 测试（pytest）

```bash
pip install -r requirements-dev.txt
python -m pytest -q          # 全量 165 个用例，全部 mock 掉网络/子进程
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
#    tencent-news-cli.exe 现为 .gitignore 的构建产物（不在仓库内），打包前需自行把官方
#    原生二进制放到项目根（安装见 §8.7）；产物 dist/ 与 *.spec 同样不入库。
python -m PyInstaller --onefile --name tripnow-chat \
  --paths . --paths server_py \
  --add-binary "tencent-news-cli.exe;." \
  --add-data "_build_env/.env;." \
  --clean -y server_py/chat_app.py
```

- `--onefile`：打成单文件，方便分发
- `--paths . --paths server_py`：目录重构后，根级 `ui_py` 与 `server_py/` 下各包需显式加入
  PyInstaller 的分析路径（运行时 `chat_app.py` 会自行把根目录加进 `sys.path`，但**打包期的
  依赖收集是静态分析**，跟不进运行时的 path 注入，故必须在此显式给出）。
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

和源码版 `server_py/chat_app.py` 完全一致：

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
