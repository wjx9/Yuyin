"""ChatService：服务端核心，框架无关。

复用现有 Dispatcher 与 LangGraph 编排入口，自身只多做四件事：
    1. 经 CredentialProvider 取该用户的三方凭证（当前 mock）；
    2. 按 session_id 取/建该会话的多轮历史，串行注入 RouteContext；
    3. 图执行完成后把这轮问答记进该会话历史；
    4. 按 user_id 装配图——商店模式（配置了 store_client）下每个用户一份
       AssistantGraph；内置能力走 local MCP facade，远程能力走 HTTP MCP，均由
       MCPHandler 进入同一 Dispatcher，LRU 缓存 + 版本比对按需重建。
不依赖任何 HTTP 框架——HTTP/WS 适配器只调用 handle_chat()，便于将来换框架/迁阿里云。

P1/P2 分界（见 最终技术路线.md §4.3）：
  - 未配置商店（store_client=None）→ 维持 P1 现状：单图，MCP 技能来自本地 manifest；
  - 配置商店 → base 图保留无商店时的兜底，用户图按启用状态装配统一 MCPHandler。
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict

from a2ui import build_a2ui

from routing import RouteContext, build_dispatcher
from orchestration import build_assistant_graph
from mcp_skill.assembly import build_mcp_handlers
from mcp_skill.builtin import build_builtin_manifests
from mcp_skill.handler import MCPHandler
from mcp_skill.client import LocalHandlerClient, McpToolClient
from mcp_skill.provider import SkillCredentialProvider
from mcp_skill.registry import SkillRegistry
from store_client import StoreUnavailable

from .auth import CredentialProvider, MockCredentialProvider
from .schemas import ChatRequest, ChatResponse
from .session import SessionStore

_log = logging.getLogger("server.service")

# 存活用户图上限（设计 §3 规模边界 / §4.3）：每用户×每技能一个 MCP 连接，演示级无感；
# 商用前收敛为"每 MCP server 共享连接 + 按用户鉴权头切换"。
MAX_GRAPHS = 200


class ChatService:
    def __init__(
        self,
        dispatcher=None,
        composer=None,
        analyzer=None,
        decider=None,
        store: SessionStore | None = None,
        credentials: CredentialProvider | None = None,
        store_client=None,
    ):
        if store_client is None:
            # 未配置商店 → P1 现状：MCP 技能从本地 manifest 装配进单图。
            dispatcher = dispatcher or build_dispatcher(extra_handlers=build_mcp_handlers())
            self._base_graph = build_assistant_graph(
                dispatcher=dispatcher,
                composer=composer,
                analyzer=analyzer,
                decider=decider,
            )
            self._registry = None
            self._cred_provider = None  # P1 无商店模式：无凭证注入（本地 manifest 无 byok）
        else:
            # 有商店 → base 图 = 纯内置（/health 无参语义 §4.5）；用户图按选购装配。
            self._base_graph = build_assistant_graph(
                dispatcher=dispatcher or build_dispatcher(),
                composer=composer,
                analyzer=analyzer,
                decider=decider,
            )
            self._store_client = store_client
            self._registry = SkillRegistry(store_client)
            self._cred_provider = SkillCredentialProvider(store_client)
            self._builtin_sync_done = False
            # 目录由主服务根据实际注册结果同步，避免商店展示未配置 key 的虚假能力。
            try:
                store_client.sync_builtin_skills(
                    build_builtin_manifests(self._base_graph._dispatcher)
                )
                self._builtin_sync_done = True
            except StoreUnavailable:
                _log.warning("技能商店暂不可达，稍后聊天请求仍会退回内置能力")
        self._graphs: "OrderedDict[str, tuple[int, object, list[object]]]" = OrderedDict()
        self._lock = threading.Lock()
        # 内置意图集捕获一次（设计 §4.3 双保险②）：装配时过滤撞内置意图的 MCP 技能。
        self._builtin_intents = set(self._base_graph._dispatcher.intents)

        self._store = store or SessionStore()
        self._credentials = credentials or MockCredentialProvider()
        self._mock_notified: set[str] = set()  # 已打过 mock 鉴权提示的会话

    @property
    def capabilities(self) -> list[str]:
        return self._base_graph.capabilities

    def capabilities_for(self, platform: str = "pc") -> list[str]:
        """指定端可用的能力清单（/health 无 user_id：base 图 = 内置或本地 manifest，行为与现状一致）。"""
        return self._base_graph.capabilities_for(platform)

    def capabilities_for_user(self, user_id: str, platform: str = "pc") -> list[str]:
        """/health?user_id=：该用户的能力（内置 + 已选购 MCP），仍按 platform 过滤。"""
        return self._assistant_for(user_id).capabilities_for(platform)

    def _assistant_for(self, user_id: str):
        """返回该用户的 AssistantGraph。商店模式按版本比对重建；未配置商店恒为 base 图。"""
        if self._registry is None:
            return self._base_graph
        try:
            if not self._builtin_sync_done:
                self._store_client.sync_builtin_skills(
                    build_builtin_manifests(self._base_graph._dispatcher)
                )
                self._builtin_sync_done = True
            version, skills = self._registry.resolve(user_id)  # 锁外：TTL 缓存多数命中
        except StoreUnavailable:
            # 商店挂了 → 退回纯内置，不阻塞聊天（设计 §4.1）。
            _log.warning("商店不可达，用户 %s 退回内置技能", user_id)
            return self._base_graph

        with self._lock:  # 锁内重验版本 → 杜绝并发重复构建（设计 §4.3 竞态修正）
            hit = self._graphs.get(user_id)
            if hit and hit[0] >= version:
                # 复用条件放宽：某线程 resolve 到旧版本、但另一线程已写入更新图时，
                # 直接复用新图，避免"旧版本覆盖新版本"（版本回退保护）。
                self._graphs.move_to_end(user_id)
                return hit[1]

            # 远程 MCP 与内置能力都统一转成 MCPHandler；builtin 使用 local transport，
            # 由 LocalHandlerClient 调原有 Handler，远程技能使用 McpToolClient。
            builtin_skills = [m for m in skills if getattr(m, "kind", "mcp") == "builtin"]
            mcp_skills = [m for m in skills if getattr(m, "kind", "mcp") != "builtin"]
            conflict = {m.skill_id for m in mcp_skills if m.intent in self._builtin_intents}
            if conflict:
                _log.warning("用户 %s 的技能 intent 与内置冲突，已跳过: %s", user_id, sorted(conflict))
            mcp_skills = [m for m in mcp_skills if m.intent not in self._builtin_intents]

            # 为每个已启用的 manifest 创建统一客户端。内置 Handler 不启动网络连接。
            local_clients = []
            local_handlers = []
            for manifest in builtin_skills:
                handler = self._base_graph._dispatcher.handler_for(manifest.intent)
                if handler is None:
                    _log.warning("内置技能 %s 没有对应 Handler，已跳过", manifest.intent)
                    continue
                client = LocalHandlerClient(handler)
                local_clients.append(client)
                local_handlers.append(MCPHandler(manifest, client))
            remote_clients = [
                McpToolClient(m, credential_provider=self._cred_provider, user_id=user_id)
                for m in mcp_skills
            ]
            clients = local_clients + remote_clients
            # /me/skills/sync 只返回 active 且用户启用的 builtin，因此不在列表中的
            # 内置能力会被排除；保留 chitchat 作为无工具时的安全兜底。
            # 顶替内置：收集该用户全部已购技能声明的 replaces（如 ["amap_weather_live"]），
            # 从 dispatcher 与 plannable 白名单里剔除，实现"买了技能就用它、内置让位"。
            exclude = {i for m in skills for i in m.replaces} | (self._builtin_intents - {"chitchat"})
            dispatcher = build_dispatcher(
                extra_handlers=local_handlers + [MCPHandler(m, c) for m, c in zip(mcp_skills, remote_clients)],
                exclude_intents=exclude,
            )
            graph = build_assistant_graph(dispatcher=dispatcher, exclude_intents=exclude)

            old = self._graphs.pop(user_id, None)
            if old:  # 换图回收旧常驻连接，防线程泄漏（设计 §4.3 _cleanup_graph）
                for c in old[2]:
                    c.close()
            self._graphs[user_id] = (version, graph, clients)
            self._graphs.move_to_end(user_id)

            while len(self._graphs) > MAX_GRAPHS:  # 简单 LRU：淘汰最久未用
                _uid, (_v, _g, cs) = self._graphs.popitem(last=False)
                for c in cs:
                    c.close()
                _log.info("LRU 淘汰用户 %s 的图", _uid)
            return graph

    def handle_chat(self, req: ChatRequest) -> ChatResponse:
        creds = self._credentials.resolve(req.user_id)
        if creds.mocked and req.session_id not in self._mock_notified:
            self._mock_notified.add(req.session_id)
            _log.info(
                "[我们mock了鉴权过程, 假装拿到了key] user=%s session=%s", req.user_id, req.session_id
            )

        context = RouteContext(
            union_id=creds.tripnow_union_id,
            location=req.location,
            include_data=req.include_data,
            platform=req.platform,
            metadata={"location_source": req.location_source or "unknown"},
        )

        hist = self._store.get(req.session_id)
        with self._store.lock_for(req.session_id):
            context.history = hist.turns  # 本轮之前的历史
            result = self._assistant_for(req.user_id).run(req.query, context)
            hist.append(req.query, result.text)

        # 只下发可序列化的 dict 型 data（如音乐深链）；富对象（NewsResult 等）保持不下发。
        data = result.data if isinstance(result.data, dict) else None
        # A2UI 卡片只对富 UI 端（client_flutter，platform=mobile）生成；
        # 纯文本端（chat_app/client_py）不产不发，省流量也免得老客户端困惑。
        a2ui = (
            build_a2ui(result.intent, result.card_text)
            if req.platform == "mobile"
            else None
        )
        return ChatResponse(
            text=result.text, intent=result.intent, session_id=req.session_id, data=data, a2ui=a2ui
        )
