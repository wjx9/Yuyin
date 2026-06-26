"""快递100 provider 单测：签名规则 + 自动识别 + 模型解析（全部用假 session 隔离网络）。"""

from __future__ import annotations

import hashlib
import json

import pytest

from kuaidi100_client.client import Kuaidi100Client
from kuaidi100_client.errors import Kuaidi100Error
from kuaidi100_client.models import TrackResult
from kuaidi100_client.service import ExpressService


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, get_payload=None, post_payload=None):
        self._get_payload = get_payload
        self._post_payload = post_payload
        self.last_get = None
        self.last_post = None

    def get(self, url, params=None, timeout=None):
        self.last_get = {"url": url, "params": params}
        return FakeResponse(self._get_payload)

    def post(self, url, data=None, timeout=None):
        self.last_post = {"url": url, "data": data}
        return FakeResponse(self._post_payload)


def test_sign_is_md5_param_key_customer_upper():
    session = FakeSession(post_payload={"state": "3", "nu": "SF1", "com": "shunfeng", "data": []})
    client = Kuaidi100Client(key="K", customer="C", session=session)
    client.query("shunfeng", "SF1")

    param_str = json.dumps({"com": "shunfeng", "num": "SF1"}, ensure_ascii=False, separators=(",", ":"))
    expected = hashlib.md5(f"{param_str}KC".encode("utf-8")).hexdigest().upper()
    assert session.last_post["data"]["sign"] == expected
    assert session.last_post["data"]["customer"] == "C"
    assert session.last_post["data"]["param"] == param_str


def test_phone_included_in_param_when_given():
    session = FakeSession(post_payload={"state": "0", "data": []})
    client = Kuaidi100Client(key="K", customer="C", session=session)
    client.query("shunfeng", "SF1", phone="1234")
    assert '"phone":"1234"' in session.last_post["data"]["param"]


def test_query_raises_on_business_failure():
    session = FakeSession(post_payload={"result": False, "returnCode": "500", "message": "boom"})
    client = Kuaidi100Client(key="K", customer="C", session=session)
    with pytest.raises(Kuaidi100Error):
        client.query("shunfeng", "SF1")


def test_autodetect_returns_com_codes():
    session = FakeSession(get_payload=[{"comCode": "shunfeng"}, {"comCode": "yuantong"}, {}])
    client = Kuaidi100Client(key="K", customer="C", session=session)
    assert client.autodetect("12345") == ["shunfeng", "yuantong"]


def test_autodetect_accepts_wrapped_auto_dict():
    session = FakeSession(get_payload={"auto": [{"comCode": "jd"}]})
    client = Kuaidi100Client(key="K", customer="C", session=session)
    assert client.autodetect("12345") == ["jd"]


def test_autodetect_raises_on_error_dict():
    # 真实场景：key 过期返回 {"result":false,"returnCode":"601","message":"key过期"}
    session = FakeSession(get_payload={"result": False, "returnCode": "601", "message": "key过期"})
    client = Kuaidi100Client(key="K", customer="C", session=session)
    with pytest.raises(Kuaidi100Error):
        client.autodetect("12345")


def test_service_autodetects_when_com_missing():
    session = FakeSession(
        get_payload=[{"comCode": "shunfeng"}],
        post_payload={"state": "3", "nu": "SF1", "com": "shunfeng", "data": [
            {"ftime": "2026-06-25 10:00:00", "context": "已签收"},
        ]},
    )
    service = ExpressService(Kuaidi100Client(key="K", customer="C", session=session))
    result = service.track("SF1")
    assert result.state_text == "已签收"
    assert result.latest == "已签收"
    assert session.last_get["params"]["num"] == "SF1"


def test_track_result_from_dict_maps_state_and_nodes():
    result = TrackResult.from_dict(
        "SF1",
        {"nu": "SF1", "com": "shunfeng", "state": 0, "data": [
            {"time": "t1", "context": "揽收"},
        ]},
    )
    assert result.state == "0"
    assert result.state_text == "在途"
    assert result.nodes[0].context == "揽收"
