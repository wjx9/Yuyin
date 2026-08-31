# 语音助手主意图理解与任务编排技术选型报告

> 研究时间：2026-08-28  | 研究对象：LangGraph 及其替代方案  |  应用场景：手机端语音助手

> 参考说明：报告的“Workflow 与 Agent”问题意识参考了你提供的文章，技术事实以各项目官方文档、官方博客和代码仓库为准。文章只提供问题入口，不把其中的阶段性评价直接当作结论。

## 一、结论先行：我们真正要选的是哪一层

这次选型不能只问“LangGraph 好不好”。语音助手至少有四层，每层解决的问题不同：

```text
用户语音
  ↓
主意图理解（用户到底想做什么、参数是什么、哪些信息缺失）
  ↓
任务编排（先做什么、哪些可以并行、结果出来后是否继续）
  ↓
能力适配（HTTP API、MCP、CLI、手机端 Action）
  ↓
可靠运行（超时、重试、持久化、恢复、审计、监控）
```

我的结论分成三句：

1. **主意图理解不应由 LangGraph 单独承担。** 它需要结构化输出、类型校验、领域词典和评测集；模型负责理解语言，代码负责检查结果是否可用。
2. **任务编排可以继续采用 LangGraph，但原因不是“它最先进”，而是它在控制力、循环、状态和工具解耦之间比较适合当前项目。** OpenAI Agents SDK、Google ADK、Microsoft Agent Framework、AutoGen、CrewAI、PydanticAI 都有合理场景，不能用一个总分替代场景判断。
3. **当前项目离商用级还有一段工程距离。** 现有图已经能运行“分析 → 决策 → 批量调用 → 观察 → 再决策 → 总结”，但还要补齐结构化意图、工具元数据、结果校验、恢复机制、权限和离线评测。长时间任务再考虑叠加 Temporal，而不是现在就整体迁移。

### 选型问题的最短答案

| 问题 | 建议答案 |
|---|---|
| 主意图识别用什么 | 模型结构化输出 + Pydantic/JSON Schema 校验 + 领域评测集 |
| 普通一次查询用什么 | 受控的短路径，减少不必要的模型往返 |
| 多工具、依赖和循环用什么 | LangGraph（保留现有 Dispatcher/Handler） |
| MCP 要不要替换 API | 不替换。API、MCP、CLI、手机 Action 都收敛到统一 Tool 接口 |
| 跨进程、跨天、必须恢复的任务 | LangGraph 负责决策，Temporal 或等价工作流引擎负责耐久执行 |
| 低代码快速试验 | Dify；但它不是代码级编排框架的同层替代 |

## 二、先把 Workflow、Tool Calling 和 Agent 分清楚

### 2.1 三个词分别在说什么

| 概念 | 谁决定下一步 | 一次请求的典型形态 | 适合的例子 |
|---|---|---|---|
| Workflow | 主要由代码预先规定 | A → B → C，少量条件分支 | 登录、查订单、生成固定格式报表 |
| Tool Calling | 模型选一个工具并填参数，代码执行 | 模型 → 工具 → 回复 | “查深圳天气” |
| Agent | 模型根据当前状态动态选择下一步 | 模型 → 工具 → 观察 → 再决策，可能循环 | “综合交通、天气和开放时间安排出行” |

Workflow 并不低级。只要路径稳定、约束明确，Workflow 往往比 Agent 更快、更容易测试。问题在于，当意图、系统状态、用户等级、时间和地区组合起来，分支数量开始快速膨胀，固定脚本会越来越难维护。

Agent 也不等于“让模型无限自由行动”。一个可交付的 Agent 仍然需要工具白名单、参数校验、预算、步数上限、超时、权限确认和失败出口。模型可以选择下一步，但不能越过系统设定的边界。

### 2.2 语音助手里的两条路径

```text
短请求：语音 → 意图/槽位 → 一个工具 → 简短回复
        例如： “深圳现在多少度？”

复杂请求：语音 → 目标分析 → 动作规划 → 并行或串行调用
          → 检查结果 → 再规划 → 生成可执行建议
        例如： “我周末去杭州，结合交通和天气帮我安排”
```

同一个 LangGraph 可以承载这两类请求，但不代表每句话都要走很多轮。图负责给出统一的边界和状态；具体请求是否需要循环，应由任务状态和工具依赖决定，而不是靠针对某个句子的 `if/else`。

## 三、纵轴：LangGraph 为什么出现，又为什么演变成现在这样

这条技术线最好不要背版本号，而要看“工程问题 → 设计决策 → 新能力”。

### 3.1 2022：固定链条解决了“接入太麻烦”

大模型应用刚开始普及时，常见流程是：Prompt → LLM → 解析 → 检索或 API → 下一个 LLM。LangChain 早期的 Chain、Loader 和 LCEL 让开发者可以把模型、提示词、检索器和工具接起来，解决了供应商接口不统一、组件难复用的问题。

这类链路接近 DAG（有向无环图）：从开始走到结束，通常不会回到已经执行过的节点。它容易读、容易测，适合固定流程，但不适合描述“拿到工具结果后，模型突然决定再查一次”的情况。

### 3.2 2023：ReAct Agent 把“回来再想”带进系统

ReAct 式 Agent 的基本循环是：

```text
模型思考 → 选择工具 → 工具返回 Observation → 模型再次思考
```

早期 AgentExecutor 把这段循环封装在一个较高层的执行器里。做 Demo 很快，但当开发者想在工具前增加人工审批、让两个工具并行、为不同错误使用不同重试策略，或者限制某一类工具只能在手机端执行时，所有逻辑都容易堆到一个大类和一段长 Prompt 中。状态藏在执行器内部，调试时很难回答“为什么走到了这里”。

### 3.3 2023 年夏至 2024 年初：把隐式循环拆成显式图

LangChain 团队在 2023 年开始设计 LangGraph，并在 2024-01-17 的官方文章中公开介绍。它没有把 Agent 当成一条更长的 Chain，而是承认 Agent 有环：模型、工具和观察结果会反复交互。

因此 LangGraph 采用四个低层抽象：

```text
State：所有节点共享的任务状态
Node：一个可执行步骤，例如 analyze、decide、execute
Edge：节点之间的连接
Conditional Edge：根据状态选择不同路径
```

在当前项目中，`decide → execute_batch → observe → decide` 就是显式的 Agent 循环。模型在 `decide` 节点提出动作，代码在图和 Dispatcher 层限制动作是否合法。

2024-05 的 LangChain 0.2 官方说明把 LangGraph 称为面向 Agent 的低层控制层，并指出单一 AgentExecutor 不容易组合和扩展。这是一个重要转折：LangChain 继续提供高层组件，LangGraph 则把“如何运行 Agent”交给开发者控制。

### 3.4 2024：从“能循环”走向“出错也能继续”

Agent 进入真实应用后，循环本身还不够。大模型调用可能很慢，第三方 API 可能超时，进程可能崩溃，手机可能临时断网；如果每次都从头开始，前面成功的调用和用户等待时间都会浪费。

因此 LangGraph 逐步强化：

- **Checkpointer**：把状态和中间结果保存下来，支持恢复、记忆和 time-travel；
- **Interrupt/HITL**：暂停流程，等待用户或人工审核后再继续；
- **Streaming**：把节点或模型输出逐步发送，降低语音助手的感知等待；
- **Parallel/Batch**：把互不依赖的动作并行执行，减少总耗时；
- **LangGraph Cloud**：把队列、持久化、扩缩容和长任务部署交给托管运行时（后续平台名称转为 LangSmith Deployment）。

2024-06 的 v0.1 stable、2024-08 的 v0.2 checkpointer 拆分，反映的是同一个事实：Agent 不再只是一次 HTTP 请求，而开始接近一个需要恢复和观测的运行时。

### 3.5 2025：降低“图很强但写起来重”的门槛

显式图控制力强，但初学者需要理解节点、边和状态。2025-01 的 Functional API 用 `entrypoint` 和 `task` 提供更接近普通函数的写法，同时保留持久化、流式和人工介入能力。2025 年的预构建 Agent、子图、缓存和远程 MCP 支持，则是在低层运行时之上提供可复用部件。

这不是回到“黑盒 AgentExecutor”，而是把常用模式做成可替换的积木：需要深度定制时下沉到 StateGraph，需要快速起步时使用预构建组件。

### 3.6 2025 年以后：高层 Agent 与低层 Runtime 分层

LangChain 1.0 的方向是：高层 `create_agent` 负责快速创建常见 Agent，底层由 LangGraph runtime 提供 durable execution、短期记忆、流式和人工介入。LangGraph 1.0 则继续定位为低层 Agent orchestration。

这解释了“为什么现在是这个样子”：

```text
固定 DAG 链
  ↓ 需要工具循环
隐式 AgentExecutor
  ↓ 状态、审批、并行和重试难维护
显式 StateGraph
  ↓ 需要恢复、长任务和生产运维
带 Checkpoint/HITL/Streaming 的 Runtime + 平台
  ↓ 需要降低上手门槛
高层 Agent API 与低层 Runtime 分层
```

### 3.7 这些设计在内部解决了什么问题

LangGraph 官方对其运行时设计的解释提到，它受到 Pregel、Apache Beam 等批处理/并行计算思想影响，公共接口也借鉴了 NetworkX 的图模型。可以用一个简化模型理解：

1. 每个节点读取一份状态快照，完成自己的任务；
2. 节点产生状态更新，运行时按规则合并，而不是让多个线程直接抢写同一个对象；
3. 每轮结束时保存 channel 值和版本，形成 checkpoint；
4. 进程中断后，从最近 checkpoint 恢复，而不是重新调用所有工具。

它解决的是“概率性模型如何放进确定性的程序骨架”，而不是替模型完成思考。模型决定内容，图决定合法路径，运行时决定状态如何保存和恢复。

### 3.8 LangGraph 的边界

LangGraph 核心代码是开源 MIT License，但“开源运行时”和“托管平台”不是一回事。它不是大模型、不是地图或天气数据源，也不是开箱即用的语音产品。以下工作仍属于应用方：

- 识别用户真实目标和槽位；
- 判断工具返回是否可信、是否过期、是否满足用户问题；
- 设计权限、敏感动作确认和用户隔离；
- 为 API 设置超时、有限重试、降级和幂等；
- 做压测、回归评测、指标和告警。

## 四、横轴：把替代方案放在同一套问题上比较

为了避免“每个框架各说一套优点”，统一回答八个问题：谁决定下一步？状态放在哪里？循环和并行怎么表达？失败能否恢复？工具/MCP 怎么接？模型是否绑定？观测和部署谁负责？对短语音请求的成本和延迟如何？下表是定性选型参考，不是性能 Benchmark。

| 方案 | 核心抽象 | 控制与循环 | 状态/恢复 | 工具与模型 | 更适合的场景 | 主要代价 |
|---|---|---|---|---|---|---|
| LangGraph | StateGraph、节点、边 | 很强，循环和条件边显式 | Checkpointer/平台可实现 | Provider-neutral，生态可接 MCP | 需要可控、多步骤、可审计的 Agent | 学习成本和工程配置较高 |
| OpenAI Agents SDK | Agent、Runner、handoff | Runner 驱动回合，复杂拓扑需自建 | Session 等；长流程需外接 | OpenAI 工具体验最佳，也可适配其他模型 | OpenAI 栈内的单/多 Agent | 平台倾向明显，深度自定义要补层 |
| Google ADK | Agent + Sequential/Parallel/Loop | 工作流节点和多 Agent 都较完整 | Sessions、Memory、部署服务 | Gemini/Vertex 集成自然 | Google Cloud/Gemini 企业项目 | Google 生态依赖、迁移成本 |
| Microsoft Agent Framework | Agent、WorkflowBuilder、Executor | 顺序、并行、分支、handoff、HITL | Checkpoint、事件和部署能力 | Python/.NET，Azure 集成 | 微软企业系统和 .NET 团队 | 项目较新，API 仍在演进 |
| AutoGen | AgentChat、Team、GraphFlow | 多 Agent 对话和事件驱动较强 | 团队状态可保存；生产耐久需补 | MCP/模型适配较丰富 | 多角色协作和研究型系统 | 不需要多 Agent 时偏重，调试复杂 |
| CrewAI | Agent、Crew、Flow | 角色协作直观，Flow 有分支循环 | 持久化、记忆、Guardrail/观测 | 连接器多，模型较中立 | 快速搭建角色化业务 Agent | 底层细节控制不如低层图 |
| PydanticAI | 类型安全 Agent、工具、结构化输出 | Agent 可组合，复杂图用 pydantic-graph | 可与 Temporal/DBOS 等集成 | Python 类型校验强，模型较中立 | 意图和槽位结构化、轻量 Agent | 完整运行时和复杂拓扑需自行组合 |
| Dify | 可视化画布、Workflow、Agent 节点 | 配置化分支、循环、并行 | 平台负责版本、日志和部署 | HTTP、插件、MCP，模型选择广 | 低代码原型和运营配置 | 代码级控制有限，平台依赖 |
| Temporal | Workflow、Activity、Worker | 确定性流程、重试、定时器、信号 | 事件历史和恢复很强 | 不负责模型和工具选择 | 跨天、跨服务、强可靠业务流程 | 需另接 Agent 层，运维成本高 |

下面逐一说明这些差异不是宣传语，而是由内部运行模型决定的。

### 4.1 OpenAI Agents SDK：把“回合和工具”做得很顺

它的核心是 `Agent` 描述行为和工具，`Runner` 驱动一轮轮执行，模型可以调用 function tool、handoff 或托管工具。SDK还提供 guardrails、sessions 和 tracing。开发者不必自己搭一套基础 Agent 循环，短请求的代码量和接入成本较低。

代价是：当流程不再是“一个 Agent 选择工具”，而是需要显式表达十几个业务节点、复杂依赖、人工审批和跨进程恢复时，仍要自己增加状态机或工作流系统。若项目主要使用 OpenAI Responses API，它的优势会更明显；当前项目使用自定义 Gemini Client 和已有 Dispatcher，迁移并不能自动减少业务代码。

### 4.2 Google ADK：适合 Gemini/Vertex 体系内的完整方案

ADK 将 Agent、顺序工作流、并行工作流和循环组合起来，提供会话、记忆、评测、MCP 和部署能力。它的价值在于把模型、云服务和运行时放在同一个生态里。

它并非只能使用 Gemini，但如果团队最终不采用 Google Cloud，很多集成优势就不会转化成收益。对当前项目来说，ADK可以作为未来 Google 统一技术栈时的迁移备选，而不是因为“现在调用 Gemini”就立即替换 LangGraph。

### 4.3 Microsoft Agent Framework：企业工作流取向明显

Microsoft Agent Framework 是 AutoGen 与 Semantic Kernel 团队在 2025 年之后合并方向的开源框架，提供 Python/.NET Agent 和 WorkflowBuilder。它把 Executor、边、并行 fan-out/fan-in、checkpoint、HITL、事件流等企业工作流概念放在一起。

它对 Azure、.NET 和微软企业系统更友好。当前项目的代码主要是 Python，且已有清晰的 `orchestration → routing → handlers` 分层，因此迁移需要重写编排和适配层，收益要等到公司技术栈向 Azure/.NET 靠拢时才明显。

### 4.4 AutoGen：强项是多 Agent 对话，而不是单 Agent 工具路由

AutoGen 的 AgentChat 用消息和团队表达多个 Agent，GraphFlow 进一步提供顺序、并行、条件和循环。它适合“研究员、审核员、执行员互相讨论”的问题。

但语音助手首先要解决的是“识别一个用户目标并调用正确工具”。为了查天气、导航或创建日程引入多个会话 Agent，会增加模型回合数和延迟。除非未来真的拆成多个独立角色，否则 AutoGen 的主要能力会变成额外复杂度。

### 4.5 CrewAI：角色与任务很易懂，底层控制不是重点

CrewAI 把 Agent、Crew 和 Flow 作为主要抽象：先定义角色和任务，再让一组 Agent 协作。Flow 负责状态、路由、循环和持久化，适合研究、内容生产和业务分析等角色明确的场景。

它的学习曲线比低层图短，但当你需要精确控制每个工具调用的参数、依赖和恢复点时，要么下沉到底层，要么接受框架的抽象。当前语音助手只有在未来出现多个长期协作角色时，才值得优先考虑。

### 4.6 PydanticAI：意图理解层的好候选，编排层需组合

PydanticAI 将 Agent 输出放进类型模型，工具参数和返回值可以在运行时校验。这对于“查交通”与“创建日程”这类需要明确必填槽位的语音场景很有价值。

它提供图式控制流，也支持 MCP 和流式输出，但复杂拓扑、长时间恢复通常要接 pydantic-graph、Temporal、DBOS 或其他运行时。一个合理组合是：用 Pydantic 模型约束 `goal/domain/operation/slots`，用 LangGraph 负责多步骤编排，而不是二选一。

### 4.7 Dify：平台型选择，不和代码框架完全同层

Dify 通过画布把 LLM、检索、代码、工具、分支、迭代和人工审核连起来，提供版本、调试、日志和 HTTP/MCP 发布。它能让运营人员在不改 Python 的情况下调整流程，非常适合快速试验和业务配置。

代价是：复杂的参数校验、特殊重试、手机端权限和自定义状态会逐渐进入插件或代码节点，最终仍要维护平台外的工程。它可以作为原型或运营配置平台，但不宜直接替代当前代码里的 Dispatcher/Handler。

### 4.8 Temporal：解决“可靠运行”，不解决“想做什么”

Temporal 的 Workflow 是确定性的，Activity 承担外部 API 调用，Server 保存事件历史，Worker 从任务队列领取工作。它擅长崩溃恢复、重试、定时器、信号和跨天运行。

Temporal 不知道用户说的是天气还是导航，也不会自己选择工具。将来若出现“创建提醒后每天定时检查并通知”“跨多个系统、需要人工审批的长任务”，可以让 LangGraph 负责 Agent 决策，再让 Temporal 负责可靠执行。LangGraph 官方关于二者差异的描述属于设计方观点，不应当当作独立性能基准。

### 4.9 定性评分：用于讨论，不是跑分

| 方案 | 拓扑控制 | 自主探索 | 结构化输出 | 长任务恢复 | 低延迟短请求 | 生态绑定 |
|---|---:|---:|---:|---:|---:|---|
| LangGraph | ★★★★★ | ★★★ | ★★★★ | ★★★★（需配置） | ★★★★ | 低 |
| OpenAI Agents SDK | ★★★ | ★★★★ | ★★★★ | ★★★（需外接） | ★★★★★（OpenAI 栈） | 中-高 |
| Google ADK | ★★★★ | ★★★★ | ★★★★ | ★★★★ | ★★★★（Gemini 栈） | 中-高 |
| Microsoft Agent Framework | ★★★★ | ★★★ | ★★★★ | ★★★★ | ★★★★ | 中-高 |
| AutoGen | ★★★★ | ★★★★ | ★★★ | ★★★ | ★★★ | 中 |
| CrewAI | ★★★ | ★★★★ | ★★★ | ★★★★（Flow） | ★★★ | 中 |
| PydanticAI | ★★★★ | ★★★ | ★★★★★ | ★★★（靠外部运行时） | ★★★★ | 低 |
| Dify | ★★（代码级） | ★★★ | ★★★ | ★★★★（平台能力） | ★★★★ | 高 |
| Temporal | ★★★★★（确定性） | ☆（不负责） | ☆（不负责） | ★★★★★ | ★★ | 中 |

## 五、横纵交汇：LangGraph 的优势和短板从哪里来

### 5.1 它的优势是历史选择的结果

LangGraph 早期就选择把 State、Node 和 Edge 暴露给开发者，所以它能清楚表达循环、条件、并行和人工介入。这个选择带来了可审计性，也带来了学习成本。它没有把所有“智能”封装成一个黑盒 Agent，因而不会自动帮你解决意图错误、权限错误或数据错误。

PydanticAI 的类型安全、OpenAI SDK 的回合体验、ADK 的云生态、CrewAI 的角色抽象、Dify 的可视化、Temporal 的耐久执行，分别优化了不同问题。LangGraph 的位置不是“所有维度第一”，而是把概率性模型放进一套开发者可见的状态机里。

### 5.2 语音助手的评价维度和通用 Agent 不完全一样

语音助手要额外关注：首字延迟、一次请求的模型往返次数、手机 GPS/日历等设备上下文、敏感动作是否需要确认、网络不稳定时如何降级。一个很会多 Agent 协作的框架，如果让“查天气”多跑三轮模型，也不一定适合手机用户。

因此更合理的是分层：

```text
结构化 NLU
  ↓
受控 LangGraph（短请求短路径，复杂请求循环）
  ↓
统一 Tool Adapter
  ├─ HTTP API：高德、Exa
  ├─ MCP：航班/快递等远程能力
  ├─ CLI/本机技能：服务端可执行能力
  └─ Mobile Action：GPS、日历、闹钟、倒计时、提醒
  ↓
结果校验与大模型总结
```

### 5.3 当前项目应当怎样理解，而不是盲目迁移

当前代码已经形成了一个受控 Agent，而不是完全开放自治系统：

```text
server_py/orchestration/graph.py
  AssistantState + StateGraph
  analyze → decide → execute_batch → observe → decide/compose
                 ↓
server_py/orchestration/planner.py
  GeminiRequestAnalyzer：理解目标、槽位和缺失信息
  GeminiActionDecider：从可见能力中提出下一批动作
                 ↓
server_py/routing/dispatcher.py
  根据 intent 查找 IntentSpec 和 Handler，统一执行入口
                 ↓
server_py/routing/handlers/*.py
  高德 REST、Exa、TripNow、日历/闹钟/提醒等具体能力
                 ↓
server_py/orchestration/composer.py
  把工具证据、历史和用户问题组织成自然语言回复
```

`graph.py` 负责“怎么走”，`planner.py` 负责“模型认为下一步做什么”，`dispatcher.py` 负责“把动作交给谁”，`handlers` 负责“真正访问外部世界”。这个分层让 API、MCP、CLI 和手机端动作可以共存，不需要让 LangGraph 直接了解每个第三方协议的细节。

### 5.4 现在还缺什么

这些不是换框架就会自动出现的能力：

1. **更清晰的意图对象**：建议让分析结果至少包含 `goal`、`domain`、`operation`、`slots`、`required_information`、`optional_information`、`confidence`。
2. **工具元数据**：`IntentSpec` 增加 `requires`、`produces`、`depends_on`、`side_effect`、`platforms`，让规划器根据能力契约做决定，而不是依赖输入句式特判。
3. **统一结果校验**：检查必填字段、城市和时间是否匹配、数据是否为空、是否足够回答用户问题；“接口返回 200”不等于“任务完成”。
4. **可靠执行**：每个 Handler 有独立超时、有限重试、降级和请求 ID；有副作用的日历、闹钟和提醒需要幂等键，避免重复创建。
5. **真正的状态持久化**：当前 `SessionStore` 主要保存对话历史，不等于完整的 LangGraph Checkpoint。长任务需要保存节点进度、中间结果和恢复信息。
6. **评测与观测**：记录模型版本、Prompt 版本、工具选择、参数、耗时和最终是否解决问题，建立中文口语测试集，才能知道优化是否有效。

## 六、推荐的目标架构与实施顺序

### 6.1 推荐架构

```text
手机端 ASR / 文本输入
  ↓
轻量预处理（口语归一化，不做复杂规则堆叠）
  ↓
NLU：结构化目标、领域、操作和槽位
  ↓
LangGraph
  ├─ 条件检查
  ├─ 选择动作
  ├─ 依赖分析与批量并行
  ├─ 结果校验
  ├─ 继续循环或结束
  └─ 统一总结
  ↓
Dispatcher → Handler → API / MCP / CLI / Mobile Action
  ↓
结构化结果 + 自然语言回答 + 可选手机动作
```

### 6.2 分阶段落地

**P0：先补正确性**

- 固定 `RequestAnalysis` 和 `AgentDecision` 的 JSON Schema；
- 为所有能力建立可见范围、必填槽位、平台和副作用元数据；
- 统一校验工具结果，失败时让图进入明确的失败出口；
- 保留 `_MAX_TOOL_STEPS`、工具白名单和超时，禁止无限循环；
- 为手机 GPS、日历、闹钟、倒计时和提醒动作记录来源和执行状态。

**P1：再降低语音延迟**

- 对“一个意图、一个工具、参数齐全”的请求采用短路径；
- 复杂请求才进入多轮循环；
- 同一批互不依赖的工具并行，依赖关系明确后再进入下一批；
- 对天气、地理编码等可缓存结果设置短时缓存；
- 逐步把同步 HTTP 改为可取消的异步调用。

**P2：最后补生产可靠性**

- 接入 LangGraph Checkpointer 或等价数据库；
- 增加请求级 Trace、指标、告警和可重放日志；
- 对副作用工具增加幂等、权限确认和审计；
- 如果任务跨天、需要队列和人工审批，再叠加 Temporal；
- 如果运营需要频繁调整流程，可把稳定节点发布到 Dify 等平台，但保留核心代码能力。

### 6.3 什么时候应该换成其他方案

| 变化 | 更值得评估的方案 |
|---|---|
| 全面采用 OpenAI Responses 和托管工具，流程较短 | OpenAI Agents SDK |
| 公司统一 Gemini、Vertex AI、Google Cloud | Google ADK |
| 团队主体是 .NET/Azure，企业工作流和人工审核很多 | Microsoft Agent Framework |
| 未来有多个长期协作角色 | AutoGen 或 CrewAI |
| 意图和结构化输出成为主要难点，图很简单 | PydanticAI |
| 运营人员需要可视化配置和发布 | Dify |
| 任务跨天、必须可恢复、有强事务要求 | LangGraph + Temporal |

## 七、最终判断

LangGraph 不是“开源小玩具”，也不是买来就自动商用的完整产品。它经历了从固定链、隐式 Agent 循环，到显式状态图，再到带持久化、流式、中断和部署能力的运行时演进；这个过程是对真实工程问题的回应。

它适合当前项目的原因，是项目已经有 Python 编排层、Dispatcher/Handler 工具层，并且需求会从单次查询逐步走向多工具、结果依赖和手机端动作。它不适合承担的事情也很明确：主意图理解的准确性、第三方数据质量、权限、安全和所有生产运维工作仍要由项目补齐。

所以推荐的不是“永远只用 LangGraph”，而是：**用结构化 NLU 解决理解，用 LangGraph 解决受控编排，用统一适配层承载 API/MCP/CLI/手机动作，用 Temporal 解决必要的长任务可靠性。** 这是一条可以逐步演进、也方便替换单个部件的路线。

## 八、来源与方法说明

### 主要来源

- [LangGraph 官方概览](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangGraph：从 AgentExecutor 到 StateGraph](https://www.langchain.com/blog/langgraph)
- [LangChain v0.1.0：拆分核心与集成](https://www.langchain.com/blog/langchain-v0-1-0)
- [LangChain v0.2：LangGraph 作为 Agent 控制层](https://www.langchain.com/blog/langchain-v02-leap-to-stability)
- [LangGraph Cloud 介绍](https://www.langchain.com/blog/langgraph-cloud)
- [LangGraph v0.2：可插拔 Checkpointer](https://www.langchain.com/blog/langgraph-v0-2)
- [LangGraph Functional API](https://www.langchain.com/blog/introducing-the-langgraph-functional-api)
- [LangGraph 0.3 预构建 Agent](https://www.langchain.com/blog/langgraph-0-3-release-prebuilt-agents)
- [Building LangGraph：运行时设计解释](https://www.langchain.com/blog/building-langgraph)
- [LangGraph 1.0 正式版说明](https://www.langchain.com/blog/langchain-langgraph-1dot0)
- [LangGraph GitHub 仓库与许可证](https://github.com/langchain-ai/langgraph)
- [OpenAI Agents SDK 官方文档](https://openai.github.io/openai-agents-python/agents/)
- [Google ADK 工作流文档](https://github.com/google/adk-docs/blob/main/docs/workflows/index.md)
- [Microsoft Agent Framework 工作流文档](https://learn.microsoft.com/en-us/agent-framework/concepts/workflows/)
- [AutoGen GraphFlow 文档](https://microsoft.github.io/autogen/dev/user-guide/agentchat-user-guide/graph-flow.html)
- [CrewAI 官方文档](https://docs.crewai.com/index)
- [PydanticAI Agent 文档](https://pydantic.dev/docs/ai/core-concepts/agent/)
- [Dify Workflow](https://www.dify.ai/workflows)
- [Temporal 官方文档](https://docs.temporal.io/)

### 方法论说明

本报告采用横纵分析法：纵轴按时间追踪 LangGraph 从 Chain、AgentExecutor 到 StateGraph 和生产运行时的演进，并用“问题—决策—结果”解释技术形态；横轴以同一组工程问题比较替代方案；最后把两条轴交汇到手机语音助手的约束、当前代码结构和实施顺序。框架评分是定性讨论工具，不是独立性能测试；涉及未来版本、托管服务或商业版能力时，以报告日期前能够查到的官方资料为边界，不能由此推断未验证的产品承诺。
