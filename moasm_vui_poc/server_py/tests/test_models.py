"""模型层：请求序列化 / 响应解析。"""

from tripnow_client.models import (
    UNION_ID_KEY,
    ChatRequest,
    ChatResponse,
    Message,
    build_messages,
)


def test_payload_without_union_id():
    req = ChatRequest(messages=[Message("user", "北京到上海机票")])
    payload = req.to_payload()

    assert payload["model"] == "tripnow-travel-pro"
    assert payload["messages"] == [{"role": "user", "content": "北京到上海机票"}]
    assert payload["stream"] is False
    assert payload["include_data"] is False
    assert UNION_ID_KEY not in payload  # 公开调用不带 union_id


def test_payload_with_union_id():
    req = ChatRequest(
        messages=[Message("user", "我的行程")],
        include_data=True,
        union_id="u123",
    )
    payload = req.to_payload()

    assert payload[UNION_ID_KEY] == "u123"
    assert payload["include_data"] is True


def test_build_messages_appends_query_after_history():
    history = [Message("user", "Q1"), Message("assistant", "A1")]
    msgs = build_messages("Q2", history)

    assert [m.content for m in msgs] == ["Q1", "A1", "Q2"]
    assert msgs[-1].role == "user"
    assert history == [Message("user", "Q1"), Message("assistant", "A1")]  # 未被改动


def test_response_from_dict_parses_content_and_model_data():
    raw = {
        "id": "chatcmpl-1",
        "model": "tripnow-travel-pro",
        "created": 100,
        "usage": {"total_tokens": 37, "details": {"prompt_tokens": 30, "completion_tokens": 7}},
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "最早一班 07:40"},
                "model_data": {"train": "G3"},
            }
        ],
    }
    resp = ChatResponse.from_dict(raw)

    assert resp.content == "最早一班 07:40"
    assert resp.model_data == {"train": "G3"}
    assert resp.usage.total_tokens == 37
    assert resp.usage.prompt_tokens == 30
    assert resp.choices[0].finish_reason == "stop"


def test_response_content_empty_when_no_choices():
    resp = ChatResponse.from_dict({"id": "x", "choices": []})
    assert resp.content == ""
    assert resp.model_data is None
