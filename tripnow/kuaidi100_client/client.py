"""快递100 OpenAPI 客户端：实时查询 + 单号自动识别快递公司。

实时查询签名规则（见官方文档 https://api.kuaidi100.com/document/5f0ffb5ebc8da837cbd8aefc）：
    sign = MD5(param + key + customer).upper()
其中 param 为查询参数的 JSON 字符串，整体以 form 表单提交。
"""

from __future__ import annotations

import hashlib
import json

import requests

from .errors import Kuaidi100Error

_QUERY_URL = "https://poll.kuaidi100.com/poll/query.do"
_AUTO_URL = "https://www.kuaidi100.com/autonumber/auto"
_TIMEOUT = (10, 30)

# 单号前缀 -> 快递公司编码的本地映射。autonumber 在线识别是独立付费产品，
# key 未授权时会报 601；用这张表对"前缀明确"的单号做离线兜底（如 JT=极兔）。
_PREFIX_COM = [
    ("SF", "shunfeng"),
    ("JT", "jtexpress"),
    ("YT", "yuantong"),
    ("YD", "yunda"),
    ("ST", "shentong"),
    ("JD", "jd"),
    ("ZTO", "zhongtong"),
    ("ZT", "zhongtong"),
    ("EMS", "ems"),
]


def guess_com_by_prefix(num: str) -> str | None:
    """按单号字母前缀本地猜快递公司编码，猜不出（如纯数字单号）返回 None。"""
    u = num.strip().upper()
    for prefix, com in _PREFIX_COM:
        if u.startswith(prefix):
            return com
    return None


class Kuaidi100Client:
    def __init__(self, key: str, customer: str, session: requests.Session | None = None):
        self._key = key
        self._customer = customer
        self._session = session or requests.Session()

    def autodetect(self, num: str) -> list[str]:
        """根据单号猜测快递公司编码，按可能性从高到低返回。"""
        try:
            resp = self._session.get(
                _AUTO_URL, params={"num": num, "key": self._key}, timeout=_TIMEOUT
            )
        except requests.RequestException as e:
            raise Kuaidi100Error(f"快递公司识别失败: {e}") from e
        if not resp.ok:
            raise Kuaidi100Error(f"快递公司识别返回 {resp.status_code}")

        data = resp.json()
        # 错误形态是 dict，如 {"result":false,"returnCode":"601","message":"key过期"}
        if isinstance(data, dict):
            if data.get("result") is False or data.get("returnCode"):
                raise Kuaidi100Error(
                    f"快递公司识别失败: {data.get('message')} ({data.get('returnCode')})"
                )
            data = data.get("auto") or []  # 成功也可能包成 {"auto":[...]}
        if not isinstance(data, list):
            return []
        return [it["comCode"] for it in data if isinstance(it, dict) and it.get("comCode")]

    def query(self, com: str, num: str, phone: str | None = None) -> dict:
        """实时查询物流轨迹。phone：顺丰等需收/寄件人手机号后四位。"""
        param: dict[str, str] = {"com": com, "num": num}
        if phone:
            param["phone"] = phone
        param_str = json.dumps(param, ensure_ascii=False, separators=(",", ":"))

        form = {
            "customer": self._customer,
            "sign": self._sign(param_str),
            "param": param_str,
        }
        try:
            resp = self._session.post(_QUERY_URL, data=form, timeout=_TIMEOUT)
        except requests.RequestException as e:
            raise Kuaidi100Error(f"快递查询失败: {e}") from e
        if not resp.ok:
            raise Kuaidi100Error(f"快递查询返回 {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        # 失败时返回 {"result":false,"returnCode":"500","message":"..."}
        if data.get("result") is False or data.get("returnCode"):
            raise Kuaidi100Error(f"快递查询失败: {data.get('message')} ({data.get('returnCode')})")
        return data

    def _sign(self, param_str: str) -> str:
        raw = f"{param_str}{self._key}{self._customer}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest().upper()
