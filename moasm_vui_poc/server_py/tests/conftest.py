"""共享测试夹具(fixture)。pytest 会自动发现本文件，无需 import。"""

import pytest

from tripnow_client.models import ChatRequest, ChatResponse, Choice, Usage
from tripnow_client.transport.base import TripNowTransport


class FakeTransport(TripNowTransport):
    """假传输：记录最后一次请求，返回预设响应。用于隔离业务层测试。"""

    def __init__(self, response: ChatResponse | None = None):
        self.last_request: ChatRequest | None = None
        self.closed = False
        self._response = response or ChatResponse(
            id="resp-1",
            model="tripnow-travel-pro",
            created=0,
            choices=[Choice(content="ok", model_data={"flight": 1})],
            usage=Usage(total_tokens=10),
            raw={},
        )

    def chat(self, request: ChatRequest) -> ChatResponse:
        self.last_request = request
        return self._response

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_transport() -> FakeTransport:
    return FakeTransport()
