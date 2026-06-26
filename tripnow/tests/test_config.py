"""配置：端点拼装、from_env、传输工厂。"""

import pytest

from tripnow_client.config import Settings, build_transport
from tripnow_client.errors import ConfigError
from tripnow_client.transport import McpClient, OpenApiClient


def test_url_building_test_vs_prod():
    test = Settings(api_key="sk", env="test")
    assert test.openapi_url == "https://tripnowengine.133.cn/test/tripnow/v1/chat/completions"
    assert test.mcp_url == "https://tripnowengine.133.cn/test/tripnow/v1/mcp"

    prod = Settings(api_key="sk", env="prod")
    assert prod.openapi_url == "https://tripnowengine.133.cn/tripnow/v1/chat/completions"
    assert prod.mcp_url == "https://tripnowengine.133.cn/tripnow/v1/mcp"


def test_build_transport_selects_implementation():
    assert isinstance(build_transport(Settings(api_key="sk", transport="openapi")), OpenApiClient)
    assert isinstance(build_transport(Settings(api_key="sk", transport="mcp")), McpClient)


def test_build_transport_rejects_unknown():
    with pytest.raises(ConfigError):
        build_transport(Settings(api_key="sk", transport="grpc"))


def test_from_env_reads_values(monkeypatch):
    monkeypatch.setenv("TRIPNOW_API_KEY", "sk-live-x")
    monkeypatch.setenv("TRIPNOW_TRANSPORT", "mcp")
    monkeypatch.setenv("TRIPNOW_ENV", "prod")
    monkeypatch.setenv("TRIPNOW_UNION_ID", "u42")

    s = Settings.from_env()
    assert (s.api_key, s.transport, s.env, s.union_id) == ("sk-live-x", "mcp", "prod", "u42")


def test_from_env_requires_api_key(monkeypatch):
    monkeypatch.delenv("TRIPNOW_API_KEY", raising=False)
    with pytest.raises(ConfigError):
        Settings.from_env()
