# LobeHub 使用 SOP：普通用户篇 + 开发者篇

> 整理时间：2026-07-15。基于官方文档与已验证的第三方实战教程，来源见附录。
> 配套阅读：LobeHub 的技术本质分析见 [lobehub_analysis_and_vui_ecosystem.md](./lobehub_analysis_and_vui_ecosystem.md)。
>
> **速览**：普通用户活在"驾驶舱 + 三个市场"里（U 系列 SOP），开发者活在"协议（MCP/SKILL.md）+ 部署"里（D 系列 SOP）；中间的桥是桌面版——两边都绕不开它。两种视角的第一步都是**选对形态**，选错形态是最常见的返工来源。

---

## 第 0 步（两种视角通用）：选形态

| 你的情况 | 选择 |
|---|---|
| 想最省事、跨设备用 | **Cloud web 版**：lobehub.com 注册即用，付订阅或用免费额度 |
| 想要全部功能（本地工具 MCP、Claude Code、文件操作） | **桌面版**：lobehub.com/downloads 下载（macOS/Win/Linux，未上架应用商店） |
| 数据敏感、公司有服务器 | **自托管**：按 SOP-D1 部署，使用侧仍按 U 系列执行 |

登录一次后，Agent、Pages、Memory 在 web/桌面/手机（Google Play 有原生包 com.lobehub.app）间自动同步。

**形态背后的技术边界**（记住它就能预判所有"为什么这个功能没有"）：web 版跑在浏览器沙箱里，起不了本地进程——所以本地 MCP 安装、Claude Code 接入、本地文件操作全部是桌面版独占。

---

# 第一部分：普通用户视角 SOP（零代码）

## SOP-U1 起步与模型选择

1. 注册/登录 → 进入 Workspace。
2. 模型来源二选一：
   - 用平台订阅捆绑的算力额度（省心，约 $9.9–20/月档位）；
   - 设置里填自己的 API key（OpenAI/Claude/Gemini/DeepSeek 均可），按量付费，重度用户更省钱。

## SOP-U2 从市场领"人"（Agent 市场）

1. 左侧栏 Community → Agents（即 lobehub.com/agent）。
2. 按分类（写作/编程/问答/图像/视频/语音/工作流）或搜索找目标。
3. 点卡片进详情页 → 添加到 Workspace。
4. 可自由修改它的提示词和模型参数——它本质是提示词配置包，改坏了删掉重领，零成本。

## SOP-U3 给助手装"手和脚"（MCP，需桌面版）

1. 打开 MCP 市场 → 搜索目标能力（Google Drive、Notion、数据库等）。
2. 点安装——桌面端自动检查系统依赖，缺了会给出对应操作系统的安装命令。
3. 按提示填配置：API key，或走 OAuth 授权（Google 系需在浏览器完成一次登录同意）。
4. 等验证通过（自动确认服务可达、认证有效、工具可用）→ 会话里用自然语言使唤。
5. **安全三条**：
   - 官方明确声明不保证所有 MCP 的安全性——只装来源可查的；
   - 能选只读权限（如 `drive.readonly`）就不给写权限；
   - 涉及公司数据先问 IT。

## SOP-U4 知识库问答（RAG）

上传文件到知识库 → 对话时引用该知识库 → 助手基于你的文档回答。适合"对着一堆文档提问"的场景。

## SOP-U5 派后台任务 + IM 收报（CAO/Task）

1. 自然语言描述要完成的事 → 派发为 Task，agent 在云端后台持续跑。
2. 完成的工作进入待审核区 → 你评论 → 它据此修改迭代。
3. 设置里绑定 IM（Slack/Discord/Telegram/微信/飞书/Lark/LINE/QQ/iMessage）→ 收每日简报，不用守网页。

## SOP-U6 云沙箱（让助手真的跑代码）

助理档案页"+ 添加技能"勾选云沙箱（或会话中点输入框下方技能图标勾选）→ 助手在隔离云端环境执行 Python/JS/TS 并返回真实输出；生成文件给下载链接，文件随会话临时存在。

## 普通用户最常踩的坑

- 在 web 版里找不到 MCP 安装 / Claude Code 入口——那是桌面版独占（见第 0 步的技术边界）。
- 所有授权类操作（OAuth、权限）都在设置页完成，不要期待在对话里"说"完成授权。

---

# 第二部分：开发者视角 SOP

## 第 0 步：确认你是哪种开发者

| 角色 | 走哪条 SOP |
|---|---|
| A. 自托管运维 | SOP-D1 |
| B. 能力提供者（把自家服务接进生态） | SOP-D2（MCP server）/ SOP-D3（Skill） |
| C. Agent 创作者 | SOP-D4 |
| D. 拿它当日常开发驾驶舱 | SOP-D5 |

## SOP-D1 自托管部署（Docker Compose，服务端数据库版）

1. **先看许可证**：LobeHub Community License（基于 Apache 2.0 修改）——原样部署、内部商用免费；**改代码做商业衍生品需向 LobeHub 购买授权**。
2. **架构前置**，完整版需四个服务 + 一个推荐项：
   - LobeHub 本体；
   - 带 **pgvector 插件**的 PostgreSQL（知识库/RAG 依赖）；
   - S3 兼容对象存储（文件上传依赖；官方 compose 默认 RustFS，MinIO 也常用）；
   - SSO 鉴权服务（推荐 NextAuth 或 Logto）；
   - Redis（推荐：会话/限流/缓存）。
3. **拉官方配置**：
   ```bash
   curl -O https://raw.githubusercontent.com/lobehub/lobe-chat/HEAD/docker-compose/local/docker-compose.yml
   curl -O https://raw.githubusercontent.com/lobehub/lobe-chat/HEAD/docker-compose/local/.env.zh-CN.example
   mv .env.zh-CN.example .env
   ```
4. **必填环境变量**：
   - `APP_URL`
   - `DATABASE_URL`（`postgres://user:pass@host:port/db`；`DATABASE_DRIVER` 默认 node）
   - `KEY_VAULTS_SECRET`（`openssl rand -base64 32` 生成）
   - `NEXT_AUTH_SECRET`、`NEXT_AUTH_SSO_PROVIDERS`、`NEXTAUTH_URL`
   - `NEXT_PUBLIC_SERVICE_MODE=server`
5. **两个已知坑**：
   - `NEXT_PUBLIC_` 前缀变量是**构建期**打进镜像的——要改必须自己 build 镜像（所以 Clerk 在公共镜像上开箱不可用，选 NextAuth/Logto）；
   - `S3_ENDPOINT` 别直接写容器名（如 `http://rustfs:9000`）——浏览器解析不了容器名，图片上传会挂；要用宿主机可达地址。
6. **启动**：`docker compose up -d`。镜像启动前自动跑数据库 migration——**用空库**；建表出问题：`docker compose down` → 删挂载数据目录 → 重新 `up -d` 强制重建。
7. **网络模式三选一**：本地模式（默认仅本机）/ 端口模式（局域网/公网 http，无域名场景）/ 域名模式（反代 + https，团队日常用；**Logto 反代必须带 `X-Forwarded-Proto: https`**）。

## SOP-D2 写 MCP server 接入私域/三方能力（生态接入的正道）

1. 选官方 SDK（TypeScript 或 Python）→ 声明 tools（名字 + JSON Schema 参数 + 处理函数）。包住内部 DB/API 通常几十行代码。
2. **传输选型**：
   - **stdio**：本地进程，桌面场景；
   - **Streamable HTTP + OAuth 2.1**：远程托管，可被所有 MCP 客户端接入。注意规范硬要求：强制 PKCE、token 的 `aud` 校验（RFC 8707 资源指示符）、**禁止把客户端 token 透传给上游 API**（防"混淆代理"漏洞，server 调上游必须自己作为 OAuth 客户端拿单独 token）。
3. 本地验证：LobeHub 桌面端手动添加自定义 MCP → 确认握手、工具列表申报、调用链路全通。
4. 顺手多测两个宿主（Claude Code / Cursor）——**MCP 是中立标准，写一次全生态可用，LobeHub 只是分发渠道之一**。
5. 提交 LobeHub MCP 市场收录，附清晰的权限说明（要什么 scope、碰什么数据）——直接影响用户敢不敢装。

## SOP-D3 写 Skill（SKILL.md 开放标准）

1. 建文件夹，核心是 `SKILL.md`：
   - 文件**第一行必须是 `---`**（YAML frontmatter 起始分隔符，前面不能有任何内容）；
   - `name`：只能小写字母/数字/连字符，≤64 字符，不能含 anthropic/claude 等保留词；
   - `description`：写清"做什么 + 何时用"——**它决定 agent 何时自动加载你的技能，是整个 skill 最重要的一行**。
2. 正文写 Markdown 指令；可选携带 `scripts/`（可执行代码）、`references/`（参考文档）、`assets/`（模板）。
3. 按**渐进披露**设计：元数据 → 正文 → 脚本，逐层按需加载；别把所有内容堆进正文。
4. 本地验证：放进 `~/.claude/skills/`（个人）或项目 `.claude/skills/`（团队 git 共享），用 Claude Code 实测触发时机。
5. 发布到 GitHub → LobeHub 市场自动收录（或主动提交）。用户侧安装命令：
   ```bash
   npx -y @lobehub/market-cli skills install <skill-name> --agent <cursor|claude|...>
   ```
6. 附加收益：SKILL.md 是 Anthropic 开源的行业标准（agentskills.io），Claude Code / Codex / Cursor / Gemini CLI 都认——写一次，全生态分发。

## SOP-D4 发布 Agent 到市场

1. 首次提交先创建社区档案。
2. 提交 agent 配置（提示词 + 模型参数 + 工具引用）。
3. 平台 i18n 流水线自动产出多语言版本全球分发。
4. **投入产出提示**：Agent 是纯配置、无技术壁垒，价值在领域知识的提示词沉淀；真想构建壁垒，做 SOP-D2 的 MCP server。

## SOP-D5 异构 Agent 工作流（把它当日常开发驾驶舱）

1. **前置**：桌面版 + 已装 Claude Code CLI 且 `claude` 在 PATH——终端能用，LobeHub 里就能用（认证直接复用本机 CLI 登录态，无需再登录）。
2. 添加 Claude Code 助手 → **发第一条消息前先绑定工作目录**（目录内它有完全读写权限，谨慎选择）。
3. 日常使用要点：
   - 长任务跨消息自动续接（底层复用 Claude Code session ID）；
   - 子 agent 以独立线程呈现，不污染主对话；
   - 中途切工作目录会开新会话，旧上下文不可恢复。
4. 两种替代执行位置：不想让它碰本地文件 → 切云沙箱；项目在另一台机器 → `lh connect` 接入远程设备驱动。

---

## 附录：主要信息来源

- **部署**：[官方 Docker Compose 部署文档](https://lobehub.com/docs/self-hosting/platform/docker-compose) · [Docker 单容器部署](https://lobehub.com/docs/self-hosting/platform/docker) · [服务端数据库配置（中文）](https://lobehub.com/zh/docs/self-hosting/server-database) · [自托管选型](https://lobehub.com/docs/self-hosting/start)
- **使用**：[Agent 市场使用文档](https://lobehub.com/docs/usage/community/agent-market) · [发布 Agent 指南](https://lobehub.com/docs/usage/community/publish-agent) · [MCP 市场文档](https://lobehub.com/docs/usage/community/mcp-market) · [Claude Code 集成文档](https://lobehub.com/zh/docs/usage/agent/claude-code) · [云沙箱文档](https://lobehub.com/zh/docs/usage/agent/sandbox)
- **Skill 标准**：[Claude Code Skills 文档](https://code.claude.com/docs/zh-CN/skills) · [SKILL.md 格式详解](https://agentskillsdev.com/courses/agent-skills-l1/) · agentskills.io
- **MCP 授权规范**：[MCP 官方授权文档](https://modelcontextprotocol.io/docs/tutorials/security/authorization) · [OAuth 2.1 for Remote MCP (2026)](https://mcp.directory/blog/oauth-21-for-remote-mcp-servers-streamable-http-explained-2026)
- **第三方部署实战**：[THsInk（compose 整合 Logto/MinIO）](https://www.thsink.com/notes/1707/) · [FlareBlog](https://www.jamesflare.com/zh-cn/install-lobechat-db/) · [南风大叔（.env 示例）](https://raylenzed.com/169.html)
