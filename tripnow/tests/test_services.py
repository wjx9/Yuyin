"""业务层：公开 vs 个人的核心差异 —— 是否注入 union_id。"""

import pytest

from tripnow_client.errors import ConfigError
from tripnow_client.models import UNION_ID_KEY
from tripnow_client.services import PersonalTravelService, PublicTravelService


def test_public_service_sends_no_union_id(fake_transport):
    service = PublicTravelService(fake_transport)
    resp = service.ask("查询明天北京到上海的火车票")

    req = fake_transport.last_request
    assert req.union_id is None
    assert UNION_ID_KEY not in req.to_payload()
    assert req.include_data is True  # 默认开启结构化数据
    assert resp.content == "ok"


def test_public_service_respects_include_data_off(fake_transport):
    PublicTravelService(fake_transport).ask("x", include_data=False)
    assert fake_transport.last_request.include_data is False


def test_personal_service_injects_union_id(fake_transport):
    service = PersonalTravelService(fake_transport, union_id="u999")
    service.ask("我的行程")

    req = fake_transport.last_request
    assert req.union_id == "u999"
    assert req.to_payload()[UNION_ID_KEY] == "u999"


def test_personal_service_requires_union_id(fake_transport):
    with pytest.raises(ConfigError):
        PersonalTravelService(fake_transport, union_id="")


def test_my_trips_and_subscribe_use_union_id(fake_transport):
    service = PersonalTravelService(fake_transport, union_id="u1")

    service.my_trips()
    assert fake_transport.last_request.union_id == "u1"

    service.subscribe("关注今天D7561次广州到深圳北的一等座")
    assert fake_transport.last_request.union_id == "u1"
    assert "D7561" in fake_transport.last_request.messages[-1].content
