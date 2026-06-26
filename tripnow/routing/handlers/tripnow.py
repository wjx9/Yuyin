"""TripNow 出行能力的两个 Handler：公开信息 / 个人信息。

为什么 TripNow 占两个意图、而高德/快递只占一个？
    高德、快递 agent 自身会做内部场景路由，对外是单一入口。
    TripNow 也会做内部场景路由，但"是否携带 union_id"是一个**业务身份分叉**，
    决定了能否访问个人数据，无法由下游模型自行判断——所以在路由层显式拆成两支。
"""

from __future__ import annotations

from tripnow_client.services.personal import PersonalTravelService
from tripnow_client.services.public import PublicTravelService
from tripnow_client.transport import TripNowTransport

from ..handler import Handler, RouteContext, RouteResult


class TripNowPublicHandler(Handler):
    intent = "tripnow_public"
    description = "查询公开出行信息：火车票/机票余票、车次航班动态、车站大屏、抢票分析等（不涉及个人账号）"

    def __init__(self, transport: TripNowTransport, model: str = "tripnow-travel-pro"):
        self._service = PublicTravelService(transport, model=model)

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        resp = self._service.ask(query, include_data=context.include_data)
        return RouteResult(text=resp.content, data=resp.model_data, intent=self.intent)


class TripNowPersonalHandler(Handler):
    intent = "tripnow_personal"
    description = "查询/操作与当前用户绑定的出行信息：我的行程、我的订单、订阅关注车次等（需要已登录的 union_id）"

    def __init__(
        self,
        transport: TripNowTransport,
        model: str = "tripnow-travel-pro",
        mock_union_id: str | None = None,
    ):
        self._transport = transport
        self._model = model
        # 真实产品在此处应走 OAuth 登录拿 union_id；demo 阶段用配置里的测试账号 mock 跳过
        self._mock_union_id = mock_union_id

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        union_id = context.union_id or self._mock_union_id
        if not union_id:
            return RouteResult(
                text="这是涉及你个人行程的请求，但还没有登录身份（union_id），"
                "且未配置测试账号。请用 --union-id 传入，或在 .env 设置 TRIPNOW_UNION_ID。",
                intent=self.intent,
            )

        # 标记是否走了 mock 鉴权（context 未带身份、靠测试账号兜上）
        mocked = not context.union_id
        service = PersonalTravelService(self._transport, union_id, model=self._model)
        resp = service.ask(query, include_data=context.include_data)

        text = resp.content
        if mocked:
            text = (
                f"[本次 mock 假装 OAuth 鉴权通过，使用测试账号 {self._mask(union_id)} 查询]\n"
                f"{text}"
            )
        return RouteResult(text=text, data=resp.model_data, intent=self.intent)

    @staticmethod
    def _mask(union_id: str) -> str:
        """脱敏展示测试账号，避免完整 id 打到屏幕/日志。"""
        if len(union_id) <= 8:
            return union_id[:2] + "***"
        return f"{union_id[:4]}***{union_id[-4:]}"
