"""快递100 物流查询 Handler。

路由层只负责"这是查快递"的判断；从自然语言里抽单号交给一个极简正则，
抽不到就把原文交还给用户提示补充。真正的快递公司识别由 ExpressService 内部完成。
"""

from __future__ import annotations

import re

from kuaidi100_client.errors import Kuaidi100Error
from kuaidi100_client.service import ExpressService

from ..handler import Handler, RouteContext, RouteResult

# 主流快递单号：一段 8~24 位的数字/字母组合。
# 用显式字符类而非 \b：中文字符在 Python 正则里也算 \w，"单号为1234..."
# 中的词边界不存在，\b 会匹配失败；而 [A-Za-z0-9]+ 天然以中文为界切出号码。
_NUM_RE = re.compile(r"[A-Za-z0-9]{8,24}")


class ExpressTrackingHandler(Handler):
    intent = "express_tracking"
    description = "查询快递/物流轨迹：根据运单号查包裹到哪了、是否签收"

    def __init__(self, service: ExpressService):
        self._service = service

    def handle(self, query: str, context: RouteContext) -> RouteResult:
        num = self._extract_num(query)
        if not num:
            return RouteResult(
                text="没在你的消息里找到快递单号，请把运单号发我（一般是 10~15 位数字/字母）。",
                intent=self.intent,
            )
        try:
            result = self._service.track(num)
        except Kuaidi100Error as e:
            return RouteResult(text=f"查询失败：{e}", intent=self.intent)

        head = f"单号 {result.num}（{result.com or '未知快递'}）当前状态：{result.state_text}"
        latest = f"\n最新轨迹：{result.latest}" if result.latest else ""
        return RouteResult(text=head + latest, data=result, intent=self.intent)

    @staticmethod
    def _extract_num(query: str) -> str | None:
        # 取第一段含数字的字母数字串（纯字母的词如 "express" 不算单号）
        for cand in _NUM_RE.findall(query):
            if any(c.isdigit() for c in cand):
                return cand
        return None
