"""McpToolClient —— P2 方案 A：每 MCP server 一个常驻 loop 线程。

P1（方案 B）是每次 call_tool 独立 asyncio.run，天然规避线程/重连问题但每次重握手。
P2 升 A：连接复用 + 断线自动重连，接口不变（call_tool(name, args) -> str），
MCPHandler 零改动；多一个 close() 供 ChatService 换图时回收（设计 §4.3 _cleanup_graph）。

正确形态（针对评估点 2 的修正，见 最终技术路线.md §3）：
连接/会话作为**后台 task**（`_connect_forever`），loop 用 `run_forever` 接受
`run_coroutine_threadsafe` 提交；不是 `run_until_complete(常驻协程)`——后者在连接
断开时会让协程返回、loop 线程整体退出、无重连。

P4.2 动态凭证注入（完整方案 §7）：credentials.type=byok 时，连接前按 schema 现取
用户凭证，header 注入 → 自定义 httpx client 的请求头，query 注入 → 重写连接 URL。
注入的 client 由我们托管生命周期（transport 不 aclose 它，见 streamable_http.py:677）。

mcp 版本：2.1.1（2.x API：`streamable_http_client` / `ClientSession` / 依赖 httpx2）。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import urllib.parse

from routing.handler import RouteContext, RouteResult

_log = logging.getLogger("mcp_skill.client")


def _exception_detail(error: BaseException) -> str:
    """从 ExceptionGroup 中提取最底层原因，避免只显示笼统的 ExceptionGroup。"""
    if isinstance(error, BaseExceptionGroup):
        for nested in error.exceptions:
            detail = _exception_detail(nested)
            if detail:
                return detail
    return str(error) or type(error).__name__


class McpSkillError(RuntimeError):
    """MCP 技能调用失败（连接、超时、工具报错）。"""


class LocalHandlerClient:
    """把现有 Handler 放到 MCPHandler 的同一执行接口中。

    这是内置能力的 local transport：上层仍按 MCP skill/Handler 调用，底层不再
    额外启动一个 HTTP MCP 进程，因此不会增加本机网络跳转；远程技能继续使用
    McpToolClient 的 Streamable HTTP transport。
    """

    def __init__(self, handler):
        self._handler = handler

    def call_tool(
        self,
        name: str,
        arguments: dict,
        timeout: int = 30,
        *,
        context: RouteContext | None = None,
        query: str = "",
    ) -> RouteResult:
        del name, timeout
        ctx = context or RouteContext()
        ctx.slots = dict(arguments or {})
        return self._handler.handle(query, ctx)

    def close(self) -> None:
        """与远程 MCP 客户端保持相同生命周期接口。"""


class McpToolClient:
    """每个 MCP server 一个客户端；`call_tool` 经 `run_coroutine_threadsafe` 同步等待。

    线程安全：run_coroutine_threadsafe 天然把请求串行化到该 loop，多线程请求安全。
    """

    def __init__(self, manifest, credential_provider=None, user_id=None):
        self._m = manifest
        self._cred_provider = credential_provider
        self._user_id = user_id
        self._cred_error: McpSkillError | None = None  # 缺凭证/凭证服务不可达时置位（loop 线程写）
        self._loop = asyncio.new_event_loop()
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()  # close() 优雅停机用：心跳等它退出 → 关流 → 停 loop
        self._session = None  # 由 loop 线程写，请求线程只读；GIL 保证原子
        self._started = False
        self._start_lock = threading.Lock()
        self._loop_thread = threading.Thread(
            target=self._run, name=f"mcp-{manifest.skill_id}", daemon=True
        )

    def _ensure_started(self) -> None:
        """首次真正调用技能时才启动连接线程。

        技能图构建时会装配所有已启用的 MCP。若在构造客户端时立即连接，
        一个错误地址就会在用户没有调用该技能时持续重连并刷屏。延迟到首次
        call_tool，既减少启动开销，也让未使用的技能不产生网络请求。
        """
        with self._start_lock:
            if self._started:
                return
            self._started = True
            self._loop_thread.start()

    # ---- 凭证注入（P4.2，完整方案 §7）----

    def _build_connection_params(self) -> tuple[str, dict[str, str]]:
        """连接参数：(连接 URL, 请求头)。按 manifest.credentials 注入用户凭证。

        type=none（或无 credentials）→ 原样返回 (url, {})。
        type=byok → 遍历 schema：header 注入 → headers[inject.name]=prefix+value；
        query 注入 → params[inject.name]=value，重写 URL。必填缺值 → McpSkillError。
        P0 只做 header/query（env/ssl/body 见 完整方案 §12.3 后置）。
        """
        url = self._m.mcp_server.get("url")
        parsed = urllib.parse.urlparse(url or "")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise McpSkillError(
                f"MCP 地址无效：{url!r}（应为 http(s)://主机/路径）"
            )
        creds = self._m.credentials or {}
        if creds.get("type") in (None, "none"):
            return url, {}
        if self._cred_provider is None:
            raise McpSkillError("服务端未配置凭证提供器，无法注入凭证")
        values = self._cred_provider.get(self._user_id, self._m.skill_id) or {}
        headers: dict[str, str] = {}
        query: dict[str, str] = {}
        for f in creds.get("schema") or []:
            inject = f.get("inject")
            if not inject:
                continue  # 未声明注入位置的字段只存不注（如展示用字段）
            key, label = f["key"], f.get("label", f["key"])
            value = values.get(key)
            if f.get("required") and value in (None, ""):
                raise McpSkillError(f"缺少必填凭证：{label}")
            if value is None:
                continue
            where = inject.get("where")
            if where == "header":
                headers[inject["name"]] = f"{inject.get('prefix', '')}{value}"
            elif where == "query":
                query[inject["name"]] = str(value)
        if query:
            sep = "&" if "?" in url else "?"
            url = url + sep + "&".join(
                f"{urllib.parse.quote(k)}={urllib.parse.quote(v)}" for k, v in query.items()
            )
        return url, headers

    # ---- loop 线程 ----

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.create_task(self._connect_forever())
        self._loop.run_forever()  # 接受 run_coroutine_threadsafe 提交
        # 优雅停机后可能有未完结的流 task：取消并等待，避免 "Task was destroyed" 噪音
        pending = asyncio.all_tasks(self._loop)
        for t in pending:
            t.cancel()
        self._loop.run_until_complete(
            asyncio.gather(*pending, return_exceptions=True)
        )
        self._loop.close()

    async def _connect_forever(self) -> None:
        """连接/会话作为后台 task；断开自动重连（5s 间隔）。

        凭证参数在连接循环外取一次：缺凭证/凭证服务不可达 → 置 _cred_error 并退出
        （等下次图重建新客户端再试）；网络抖动则走重连（不重建）。
        """
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client

        try:
            url, headers = self._build_connection_params()
        except McpSkillError as e:
            self._cred_error = e
            _log.warning("MCP 技能 %s 凭证不可用: %s", self._m.skill_id, e)
            return

        # 有请求头才用自定义 client（MCP 默认超时 30s/300s 不变）；无则走默认，零行为差异。
        http_client = create_mcp_http_client(headers=headers) if headers else None
        kwargs = {"http_client": http_client} if http_client is not None else {}
        failures = 0
        try:
            while not self._stop.is_set():
                delay = 5
                try:
                    async with streamable_http_client(url, **kwargs) as (r, w, *_):
                        async with ClientSession(r, w) as s:
                            await s.initialize()
                            self._session = s
                            self._ready.set()
                            _log.info("MCP 技能 %s 已连接 %s", self._m.skill_id, url)
                            await self._hold(s)  # 心跳保活；断开/停机时返回 → 退出 async with
                            failures = 0
                except Exception as e:
                    failures += 1
                    delay = min(5 * (2 ** min(failures - 1, 4)), 60)
                    # 首次失败和进入最长退避时记录；之后按较低频率提示，
                    # 避免错误地址导致每几秒刷屏，同时仍保留故障可观测性。
                    if failures <= 2 or delay == 60 or failures % 6 == 0:
                        detail = _exception_detail(e)
                        _log.warning(
                            "MCP 技能 %s 连接中断: %s；%ss 后重试",
                            self._m.skill_id,
                            detail[:160],
                            delay,
                        )
                finally:
                    self._ready.clear()
                    self._session = None
                if self._stop.is_set():
                    return
                await asyncio.sleep(delay)
        finally:
            if http_client is not None:
                await http_client.aclose()  # 自定义 client 由我们托管（streamable_http.py:677）

    async def _hold(self, session) -> None:
        """保活：每 10s 心跳 ping；stop 事件置位即返回（触发外层停机）。

        部分 MCP server（如 mcp.mcd.cn / 东财）不响应 ping（send_ping 超时），
        但连接实际健康（call_tool 正常）。若把 ping 超时当死连接，会把健康连接每
        10s 误杀一次 → 无限「重连中」，语音请求撞上重连窗口就报错。因此：
        ping 失败一次后降级为「不心跳、靠流断开感知」——真断连时
        streamable_http_client 的读循环会退出 async with，外层自动重连。
        """
        ping_enabled = True
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=10)
                return
            except TimeoutError:
                pass
            if not ping_enabled:
                continue  # 降级：不再 ping，等流断开或 stop
            try:
                await asyncio.wait_for(session.send_ping(), timeout=5)
            except Exception as e:
                _log.warning(
                    "MCP 技能 %s 心跳 ping 失败，降级为不心跳（连接仍保持）: %s",
                    self._m.skill_id,
                    type(e).__name__,
                )
                ping_enabled = False

    # ---- 请求线程 ----

    def call_tool(
        self,
        name: str,
        arguments: dict,
        timeout: int = 30,
        *,
        context: RouteContext | None = None,
        query: str = "",
    ) -> str:
        # context/query 是统一 Handler 适配接口的一部分；远程 MCP 只需要
        # arguments，保留这两个参数可让 LocalHandlerClient 与它无缝替换。
        del context, query
        if self._cred_error is not None:
            raise self._cred_error  # 缺凭证/凭证服务不可达：直接报给 handler（友好文案）
        self._ensure_started()
        fut = asyncio.run_coroutine_threadsafe(
            self._call_when_ready(name, arguments, timeout), self._loop
        )
        try:
            return fut.result(timeout)
        except TimeoutError:
            fut.cancel()
            raise McpSkillError(f"tool {name!r} 超时") from None
        except McpSkillError:
            raise
        except Exception as e:  # 传输层任何异常 → 收敛成 McpSkillError（MCPHandler 转"暂不可用"）
            raise McpSkillError(f"tool {name!r} 调用失败: {type(e).__name__}") from e

    async def _call_when_ready(self, name: str, arguments: dict, timeout: int) -> str:
        """等待首次握手完成，再调用工具；连接失败不会被误报为参数错误。"""
        try:
            await asyncio.wait_for(self._ready.wait(), timeout=timeout)
        except TimeoutError:
            raise McpSkillError(
                f"MCP 技能 {self._m.skill_id} 连接未就绪（请检查 MCP 地址和服务状态）"
            ) from None
        return await self._call(name, arguments)

    async def _call(self, name: str, arguments: dict) -> str:
        s = self._session
        if s is None:
            raise McpSkillError("MCP 连接未就绪（重连中）")
        res = await s.call_tool(name, arguments)
        if getattr(res, "isError", False):
            raise McpSkillError(f"tool {name!r} 返回错误")
        parts = [c.text for c in res.content if getattr(c, "type", "") == "text"]
        return "\n".join(parts)

    def close(self) -> None:
        """换图时回收（设计 §4.3）：优雅停机——置 stop 事件让心跳退出、async with 关流，
        再停 loop 线程。防线程泄漏；幂等。"""
        if not self._started or not self._loop.is_running():
            return

        async def _shutdown() -> None:
            self._stop.set()
            await asyncio.sleep(1.0)  # 给"心跳返回 → async with 关流"留时间
            self._loop.stop()

        asyncio.run_coroutine_threadsafe(_shutdown(), self._loop)
        self._loop_thread.join(timeout=3)
