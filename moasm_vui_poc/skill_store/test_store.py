"""商店后端单测：事务语义 + 接口（设计 §5.2）。

跑法（仓库根）：
    .venv\\Scripts\\python -m pytest skill_store\\test_store.py -q
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from skill_store import builtin_catalog, catalog, db, main, mcp_probe

SAMPLE = {
    "skill_id": "weather-mcp",
    "name": "天气查询（MCP）",
    "description": "查询城市天气",
    "intent": "weather_mcp",
    "entry_tool": "get_weather",
    "mcp_server": {"transport": "http", "url": "http://127.0.0.1:9100/mcp"},
    "tools": [
        {
            "name": "get_weather",
            "input_schema": {"required": ["city"], "properties": {"city": {"type": "string"}}},
        }
    ],
}


BYOK = {
    **SAMPLE,
    "skill_id": "region-mcp",
    "name": "区域查询（MCP）",
    "credentials": {
        "type": "byok",
        "schema": [
            {
                "key": "api_key",
                "label": "API Key",
                "type": "secret",
                "required": True,
                "inject": {"where": "header", "name": "X-API-Key", "prefix": "Bearer "},
            },
            {
                "key": "region",
                "label": "服务区域",
                "type": "select",
                "required": True,
                "options": [{"value": "cn", "label": "中国大陆"}],
                "inject": {"where": "query", "name": "region"},
            },
            {"key": "endpoint", "label": "端点（可选）", "type": "string", "required": False},
        ],
    },
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    """每测一个独立临时库，避免污染 store.db。master key 注入测试环境变量。"""
    monkeypatch.setenv("STORE_MASTER_KEY", "ab" * 32)  # 32 字节 hex
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_store.db")
    # lifespan 里的官方目录同步指向空临时目录 → 自然无操作，测试库从空库开始；
    # catalog 用例用 sync_catalog(dir=...) 显式传自己的临时目录（CONNECTORS_DIR 仍是模块全局）
    monkeypatch.setattr(catalog, "CONNECTORS_DIR", tmp_path / "connectors_empty")
    # 单测只验证商店事务/API；内置目录同步由生产启动流程单独覆盖，避免环境 .env
    # 中的真实 key 让每个测试库额外出现内置技能。
    monkeypatch.setattr(builtin_catalog, "sync_catalog", lambda: {"synced": [], "count": 0})
    db.init_db()
    with TestClient(main.app) as c:  # with 触发 startup 建表（幂等）
        yield c


def test_put_skill_bumps_version(client):
    """PUT 全量替换：每次写 version+1；清空选购后列表为空。"""
    assert client.put("/me/skills", json={"user_id": "u", "skill_ids": ["weather-mcp"]}).json()["version"] == 1
    assert client.put("/me/skills", json={"user_id": "u", "skill_ids": ["a", "b"]}).json()["version"] == 2
    assert client.put("/me/skills", json={"user_id": "u", "skill_ids": []}).json()["version"] == 3
    me = client.get("/me/skills", params={"user_id": "u"}).json()
    assert me["skill_ids"] == []


def test_sync_returns_full_manifests(client):
    """sync 返回 version + 该用户选购的完整 manifest（含 mcp_server/tools）。"""
    client.post("/skills", json={"manifest": SAMPLE})
    client.put("/me/skills", json={"user_id": "u", "skill_ids": ["weather-mcp"]})
    sync = client.get("/me/skills/sync", params={"user_id": "u"}).json()
    assert sync["version"] == 1
    assert len(sync["skills"]) == 1
    m = sync["skills"][0]
    assert m["skill_id"] == "weather-mcp"
    assert m["mcp_server"]["url"] == "http://127.0.0.1:9100/mcp"


def test_publish_rejects_duplicate_intent(client):
    """intent 唯一性（设计 §2.2①）：同 intent 不同 skill_id → 409。"""
    assert client.post("/skills", json={"manifest": SAMPLE}).status_code == 200
    dup = {**SAMPLE, "skill_id": "weather-mcp-2"}
    r = client.post("/skills", json={"manifest": dup})
    assert r.status_code == 409


# ---- 管理员自助上架（P3 修复 2）：probe / status / admin 列表 / DELETE ----

def test_probe_discovers_tools(monkeypatch):
    """probe 发现工具：mcp_probe.list_tools 成功 → ok:true + tools。"""
    monkeypatch.setattr(
        mcp_probe,
        "list_tools",
        lambda url, timeout=10.0, headers=None: [
            {"name": "translate_text", "description": "翻译", "input_schema": {"type": "object"}}
        ],
    )
    r = main.probe_tools({"mcp_server": "http://127.0.0.1:9100/mcp"})
    assert r["ok"] is True
    assert r["tools"][0]["name"] == "translate_text"


def test_probe_failure_returns_ok_false(monkeypatch):
    """probe 失败不抛 5xx，返回 {ok:false, error} 让前端展示原因。"""
    monkeypatch.setattr(
        mcp_probe,
        "list_tools",
        lambda url, timeout=10.0, headers=None: (_ for _ in ()).throw(mcp_probe.ProbeError("连接失败")),
    )
    r = main.probe_tools({"mcp_server": "http://127.0.0.1:9/mcp"})
    assert r["ok"] is False
    assert "连接失败" in r["error"]


def test_probe_headers_are_validated(client, monkeypatch):
    """probe_headers 必须是非空字符串字典；合法 headers 透传给 list_tools（临时 Token 只走请求）。"""
    seen: dict = {}

    def fake_list_tools(url, timeout=10.0, headers=None):
        seen["headers"] = headers
        return [{"name": "t", "description": "", "input_schema": {"type": "object"}}]

    monkeypatch.setattr(mcp_probe, "list_tools", fake_list_tools)
    # 非法值 → 400
    r = client.post("/skills/probe", json={"mcp_server": "x", "probe_headers": "Bearer xx"})
    assert r.status_code == 400
    r = client.post("/skills/probe", json={"mcp_server": "x", "probe_headers": {"Authorization": 123}})
    assert r.status_code == 400
    # 合法 → 透传 probe_headers
    r = client.post(
        "/skills/probe",
        json={"mcp_server": "http://127.0.0.1:9100/mcp", "probe_headers": {"Authorization": "Bearer t"}},
    )
    assert r.status_code == 200 and r.json()["ok"] is True
    assert seen.get("headers") == {"Authorization": "Bearer t"}
    # 不传 probe_headers → headers=None（无鉴权 MCP）
    r = client.post("/skills/probe", json={"mcp_server": "http://127.0.0.1:9100/mcp"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert seen.get("headers") is None


def test_probe_rejects_non_http_transport(client):
    r = client.post("/skills/probe", json={"mcp_server": "x", "transport": "stdio"})
    assert r.status_code == 400


def test_publish_with_inactive_status_is_hidden_from_catalog(client):
    """status=inactive → 目录（GET /skills）与用户 sync 都不含，但 admin 列表可见。"""
    assert client.post("/skills", json={"manifest": SAMPLE}).status_code == 200
    assert client.post("/skills", json={"manifest": SAMPLE, "status": "inactive"}).status_code == 200
    cat = client.get("/skills").json()
    assert all(s["skill_id"] != "weather-mcp" for s in cat["skills"])
    admin = client.get("/skills/admin").json()
    row = next(s for s in admin["skills"] if s["skill_id"] == "weather-mcp")
    assert row["status"] == "inactive"


def test_publish_rejects_bad_status(client):
    r = client.post("/skills", json={"manifest": SAMPLE, "status": "weird"})
    assert r.status_code == 400


def test_publish_rejects_builtin_intent(client):
    """intent 撞内置能力（如 amap_weather_live）→ 409，管理员上架直接拦下。"""
    bad = {**SAMPLE, "skill_id": "evil-mcp", "intent": "amap_weather_live"}
    r = client.post("/skills", json={"manifest": bad})
    assert r.status_code == 409
    assert "内置能力" in r.json()["detail"]


def test_publish_bumps_holders_version(client):
    """发布/更新技能 → 该技能持有者 version+1（server 侧据此重建图，热插拔）。"""
    client.post("/skills", json={"manifest": SAMPLE})
    client.put("/me/skills", json={"user_id": "u", "skill_ids": ["weather-mcp"]})
    assert client.get("/me/skills/sync", params={"user_id": "u"}).json()["version"] == 1
    client.post("/skills", json={"manifest": {**SAMPLE, "description": "v2"}})
    assert client.get("/me/skills/sync", params={"user_id": "u"}).json()["version"] == 2


def test_delete_skill_cascades_and_bumps(client):
    """DELETE 硬删：user_skills 级联清理 + 持有者 bump 版本；重复删除 404。"""
    client.post("/skills", json={"manifest": SAMPLE})
    client.put("/me/skills", json={"user_id": "u", "skill_ids": ["weather-mcp"]})
    r = client.delete("/skills/weather-mcp")
    assert r.status_code == 200
    assert r.json()["holders_bumped"] == 1
    assert client.get("/me/skills", params={"user_id": "u"}).json()["skill_ids"] == []
    assert client.get("/skills").json()["skills"] == []
    assert client.delete("/skills/weather-mcp").status_code == 404


def test_get_single_skill_returns_manifest(client):
    """GET /skills/{id}：管理员改状态/编辑前拉完整 manifest；不存在 404。"""
    client.post("/skills", json={"manifest": SAMPLE, "status": "inactive"})
    g = client.get("/skills/weather-mcp").json()
    assert g["status"] == "inactive"
    assert g["manifest"]["entry_tool"] == "get_weather"
    assert client.get("/skills/nope").status_code == 404


# ---- 已选购 vs 已启用（区分停用与退订）----

def test_me_returns_enabled_map(client):
    """GET /me/skills 同时给 skill_ids 与 enabled map（{skill_id: bool}），只含已选购。"""
    client.post("/skills", json={"manifest": SAMPLE})
    client.put("/me/skills", json={"user_id": "u", "skill_ids": ["weather-mcp"]})
    me = client.get("/me/skills", params={"user_id": "u"}).json()
    assert me["skill_ids"] == ["weather-mcp"]
    assert me["enabled"] == {"weather-mcp": True}


def test_enable_auto_purchases(client):
    """未选购时 PUT enabled=true → 自动选购并启用，sync 含它、版本+1。"""
    client.post("/skills", json={"manifest": SAMPLE})
    r = client.put("/me/skills/enabled", json={"user_id": "u", "skill_id": "weather-mcp", "enabled": True})
    assert r.status_code == 200
    assert r.json()["version"] == 1
    me = client.get("/me/skills", params={"user_id": "u"}).json()
    assert me["skill_ids"] == ["weather-mcp"]
    assert me["enabled"]["weather-mcp"] is True
    sync = client.get("/me/skills/sync", params={"user_id": "u"}).json()
    assert [s["skill_id"] for s in sync["skills"]] == ["weather-mcp"]


def test_disable_keeps_purchased_excludes_sync(client):
    """停用：保留选购（enabled=false），sync 不含、版本+1；再启用 sync 恢复。"""
    client.post("/skills", json={"manifest": SAMPLE})
    client.put("/me/skills", json={"user_id": "u", "skill_ids": ["weather-mcp"]})
    r = client.put("/me/skills/enabled", json={"user_id": "u", "skill_id": "weather-mcp", "enabled": False})
    assert r.status_code == 200
    assert r.json()["version"] == 2
    me = client.get("/me/skills", params={"user_id": "u"}).json()
    assert me["skill_ids"] == ["weather-mcp"]  # 仍已选购
    assert me["enabled"]["weather-mcp"] is False
    sync = client.get("/me/skills/sync", params={"user_id": "u"}).json()
    assert sync["version"] == 2
    assert sync["skills"] == []  # 停用不进图
    client.put("/me/skills/enabled", json={"user_id": "u", "skill_id": "weather-mcp", "enabled": True})
    sync = client.get("/me/skills/sync", params={"user_id": "u"}).json()
    assert [s["skill_id"] for s in sync["skills"]] == ["weather-mcp"]


def test_remove_unsubscribes(client):
    """退订：移除选购（连带停用），sync 不含、版本+1。"""
    client.post("/skills", json={"manifest": SAMPLE})
    client.put("/me/skills", json={"user_id": "u", "skill_ids": ["weather-mcp"]})
    r = client.put("/me/skills/remove", json={"user_id": "u", "skill_id": "weather-mcp"})
    assert r.status_code == 200
    assert r.json()["version"] == 2
    me = client.get("/me/skills", params={"user_id": "u"}).json()
    assert me["skill_ids"] == []
    assert me["enabled"] == {}


def test_remove_nonexistent_does_not_bump(client):
    """退订不存在的技能：200 且版本不变（避免无效重建）。"""
    client.post("/skills", json={"manifest": SAMPLE})
    client.put("/me/skills", json={"user_id": "u", "skill_ids": ["weather-mcp"]})
    r = client.put("/me/skills/remove", json={"user_id": "u", "skill_id": "nope"})
    assert r.json()["version"] == 1
    assert client.get("/me/skills/sync", params={"user_id": "u"}).json()["version"] == 1


def test_enabled_endpoint_validates(client):
    """enabled 必须布尔；skill_id 必须非空字符串。"""
    assert client.put(
        "/me/skills/enabled", json={"user_id": "u", "skill_id": "x", "enabled": "yes"}
    ).status_code == 400
    assert client.put(
        "/me/skills/enabled", json={"user_id": "u", "skill_id": "", "enabled": True}
    ).status_code == 400


# ---- 管理员/用户状态隔离（管理员只上架下架，用户只启用停用）----

def test_unpublish_preserves_user_enable_state(client):
    """核心隔离：管理员下架只从目录/sync 隐藏，不动用户的选购+启用；重上架原样恢复。"""
    client.post("/skills", json={"manifest": SAMPLE})
    client.put("/me/skills", json={"user_id": "u", "skill_ids": ["weather-mcp"]})
    assert [s["skill_id"] for s in client.get("/me/skills/sync", params={"user_id": "u"}).json()["skills"]] == ["weather-mcp"]
    # 管理员下架
    client.post("/skills", json={"manifest": SAMPLE, "status": "inactive"})
    assert client.get("/skills").json()["skills"] == []  # 目录隐藏
    assert client.get("/me/skills/sync", params={"user_id": "u"}).json()["skills"] == []  # sync 隐藏
    me = client.get("/me/skills", params={"user_id": "u"}).json()  # 用户状态原样保留
    assert me["skill_ids"] == ["weather-mcp"]
    assert me["enabled"]["weather-mcp"] is True
    # 管理员重上架 → 用户原样恢复（无需重新启用）
    client.post("/skills", json={"manifest": SAMPLE})
    sync = client.get("/me/skills/sync", params={"user_id": "u"}).json()
    assert [s["skill_id"] for s in sync["skills"]] == ["weather-mcp"]


def test_user_enable_does_not_change_admin_status(client):
    """反向隔离：用户启用/停用只动 user_skills，不碰 skills.status（管理员轴上架状态不受影响）。"""
    client.post("/skills", json={"manifest": SAMPLE})
    client.put("/me/skills/enabled", json={"user_id": "u", "skill_id": "weather-mcp", "enabled": True})
    admin = client.get("/skills/admin").json()
    assert next(s for s in admin["skills"] if s["skill_id"] == "weather-mcp")["status"] == "active"
    client.put("/me/skills/enabled", json={"user_id": "u", "skill_id": "weather-mcp", "enabled": False})
    admin = client.get("/skills/admin").json()
    assert next(s for s in admin["skills"] if s["skill_id"] == "weather-mcp")["status"] == "active"


def test_cannot_enable_inactive_or_missing_skill(client):
    """用户只能「新建启用」上架中的技能：下架 → 409，不存在 → 404；停用不设限（清理权保留）。"""
    client.post("/skills", json={"manifest": SAMPLE})
    client.post("/skills", json={"manifest": SAMPLE, "status": "inactive"})
    r = client.put("/me/skills/enabled", json={"user_id": "u", "skill_id": "weather-mcp", "enabled": True})
    assert r.status_code == 409
    assert client.put("/me/skills/enabled", json={"user_id": "u", "skill_id": "nope", "enabled": True}).status_code == 404
    # 停用不存在/下架技能：宽容 200（无变更不 bump）
    assert client.put("/me/skills/enabled", json={"user_id": "u", "skill_id": "nope", "enabled": False}).status_code == 200


def test_put_credentials_rejects_inactive_skill(client):
    """给下架技能新建/更新凭证 → 409（不产生死凭证）；清凭证仍可用（清理权）。"""
    client.post("/skills", json={"manifest": BYOK})
    client.post("/skills", json={"manifest": BYOK, "status": "inactive"})
    r = client.put("/me/credentials", json={"user_id": "u", "skill_id": "region-mcp", "values": {"api_key": "k"}})
    assert r.status_code == 409
    assert client.delete("/me/credentials", params={"user_id": "u", "skill_id": "region-mcp"}).status_code == 200


def test_me_detail_includes_unpublished_purchased(client):
    """detail 端点：已购技能含已下架（status=inactive）→ 用户下架期间仍可见、可停用/退订。"""
    client.post("/skills", json={"manifest": SAMPLE})
    client.post("/skills", json={"manifest": {**BYOK, "intent": "region_mcp"}})
    client.put("/me/skills", json={"user_id": "u", "skill_ids": ["weather-mcp", "region-mcp"]})
    # 管理员下架 weather（region 保持上架）
    client.post("/skills", json={"manifest": SAMPLE, "status": "inactive"})
    d = client.get("/me/skills/detail", params={"user_id": "u"}).json()
    assert d["version"] >= 1
    by_id = {s["skill_id"]: s for s in d["skills"]}
    assert set(by_id) == {"weather-mcp", "region-mcp"}  # 只含已选购
    # 下架技能仍带着用户状态返回，可渲染「已下架」卡
    assert by_id["weather-mcp"]["status"] == "inactive"
    assert by_id["weather-mcp"]["enabled"] is True  # 用户启用状态保留
    assert by_id["weather-mcp"]["name"] == "天气查询（MCP）"  # 渲染字段可用
    # 上架技能 status=active
    assert by_id["region-mcp"]["status"] == "active"
    assert by_id["region-mcp"]["credentials"]["type"] == "byok"
    # 未选购技能不出现在 detail
    client.post("/skills", json={"manifest": {**SAMPLE, "skill_id": "stock-mcp", "name": "股票", "intent": "stock_mcp"}})
    d2 = client.get("/me/skills/detail", params={"user_id": "u"}).json()
    assert "stock-mcp" not in {s["skill_id"] for s in d2["skills"]}


# ---- 动态凭证（完整方案 §7）：加密存储 + 脱敏读 + 明文读 + 级联 ----

def test_credentials_roundtrip_masked_and_plain(client):
    """保存凭证 → version+1；GET masked 隐藏 secret 但返回非敏感字段；GET plain 返回明文。"""
    client.post("/skills", json={"manifest": BYOK})
    r = client.put(
        "/me/credentials",
        json={"user_id": "u", "skill_id": "region-mcp", "values": {"api_key": "k-123", "region": "cn"}},
    )
    assert r.status_code == 200
    assert r.json()["version"] == 1

    masked = client.get("/me/credentials", params={"user_id": "u", "skill_id": "region-mcp"}).json()
    assert masked["configured"] is True
    assert masked["values"]["api_key"] is None  # secret 不返回明文
    assert masked["values"]["region"] == "cn"  # 非敏感字段可预填
    assert masked["values"]["endpoint"] is None  # 未配置

    plain = client.get(
        "/me/credentials/plain", params={"user_id": "u", "skill_id": "region-mcp"}
    ).json()
    assert plain["configured"] is True
    assert plain["values"] == {"api_key": "k-123", "region": "cn"}

    # 库里存的是密文，不是明文 JSON
    with db.connect() as conn:
        blob = conn.execute(
            "SELECT cred_json FROM user_skill_credentials WHERE user_id='u' AND skill_id='region-mcp'"
        ).fetchone()["cred_json"]
    assert "api_key" not in blob and "k-123" not in blob


def test_credentials_blank_secret_keeps_old_value(client):
    """敏感字段留空 = 保留旧值（脱敏 GET 不回传明文，用户只改非敏感字段不能清掉密钥）。"""
    client.post("/skills", json={"manifest": BYOK})
    client.put(
        "/me/credentials",
        json={"user_id": "u", "skill_id": "region-mcp", "values": {"api_key": "k-123", "region": "cn"}},
    )
    r = client.put(
        "/me/credentials",
        json={"user_id": "u", "skill_id": "region-mcp", "values": {"api_key": "", "region": "us"}},
    )
    assert r.status_code == 200
    plain = client.get(
        "/me/credentials/plain", params={"user_id": "u", "skill_id": "region-mcp"}
    ).json()
    assert plain["values"] == {"api_key": "k-123", "region": "us"}


def test_credentials_requires_master_key(client, monkeypatch):
    """缺 STORE_MASTER_KEY → 凭证端点 fail-closed 返回清晰 500，非凭证功能不受影响。"""
    monkeypatch.delenv("STORE_MASTER_KEY")
    client.post("/skills", json={"manifest": BYOK})
    r = client.put(
        "/me/credentials",
        json={"user_id": "u", "skill_id": "region-mcp", "values": {"api_key": "k", "region": "cn"}},
    )
    assert r.status_code == 500
    assert "STORE_MASTER_KEY" in r.text
    # 目录/选购照常可用
    assert client.get("/skills").status_code == 200


def test_credentials_put_required_validation(client):
    """必填字段缺失 → 400；技能不存在 → 404。"""
    client.post("/skills", json={"manifest": BYOK})
    r = client.put("/me/credentials", json={"user_id": "u", "skill_id": "region-mcp", "values": {"api_key": ""}})
    assert r.status_code == 400
    assert "必填" in r.json()["detail"]
    assert client.put(
        "/me/credentials", json={"user_id": "u", "skill_id": "nope", "values": {"api_key": "k"}}
    ).status_code == 404
    assert client.get("/me/credentials", params={"user_id": "u", "skill_id": "nope"}).status_code == 404


def test_credentials_delete_bumps_version(client):
    """删除凭证 → version+1，plain 返回 configured=false；删不存在不 bump。"""
    client.post("/skills", json={"manifest": BYOK})
    client.put(
        "/me/credentials",
        json={"user_id": "u", "skill_id": "region-mcp", "values": {"api_key": "k", "region": "cn"}},
    )
    assert client.get("/me/skills/sync", params={"user_id": "u"}).json()["version"] == 1
    r = client.delete("/me/credentials", params={"user_id": "u", "skill_id": "region-mcp"})
    assert r.json()["version"] == 2
    plain = client.get("/me/credentials/plain", params={"user_id": "u", "skill_id": "region-mcp"}).json()
    assert plain["configured"] is False
    r2 = client.delete("/me/credentials", params={"user_id": "u", "skill_id": "region-mcp"})
    assert r2.json()["version"] == 2  # 不存在不 bump


def test_unsubscribe_cascades_credentials(client):
    """退订 → 级联删凭证（三态语义：停用保留，退订才移除）。"""
    client.post("/skills", json={"manifest": BYOK})
    client.put("/me/skills", json={"user_id": "u", "skill_ids": ["region-mcp"]})
    client.put(
        "/me/credentials",
        json={"user_id": "u", "skill_id": "region-mcp", "values": {"api_key": "k", "region": "cn"}},
    )
    client.put("/me/skills/remove", json={"user_id": "u", "skill_id": "region-mcp"})
    plain = client.get("/me/credentials/plain", params={"user_id": "u", "skill_id": "region-mcp"}).json()
    assert plain["configured"] is False
    with db.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM user_skill_credentials WHERE user_id='u' AND skill_id='region-mcp'"
        ).fetchone()
    assert row is None


def test_disable_keeps_credentials(client):
    """停用保留凭证（重新启用即用，不重填）。"""
    client.post("/skills", json={"manifest": BYOK})
    client.put("/me/skills", json={"user_id": "u", "skill_ids": ["region-mcp"]})
    client.put(
        "/me/credentials",
        json={"user_id": "u", "skill_id": "region-mcp", "values": {"api_key": "k", "region": "cn"}},
    )
    client.put("/me/skills/enabled", json={"user_id": "u", "skill_id": "region-mcp", "enabled": False})
    plain = client.get("/me/credentials/plain", params={"user_id": "u", "skill_id": "region-mcp"}).json()
    assert plain["configured"] is True
    assert plain["values"]["api_key"] == "k"


def test_delete_skill_cascades_credentials(client):
    """删技能 → 级联删凭证。"""
    client.post("/skills", json={"manifest": BYOK})
    client.put(
        "/me/credentials",
        json={"user_id": "u", "skill_id": "region-mcp", "values": {"api_key": "k", "region": "cn"}},
    )
    client.delete("/skills/region-mcp")
    with db.connect() as conn:
        row = conn.execute(
            "SELECT 1 FROM user_skill_credentials WHERE user_id='u' AND skill_id='region-mcp'"
        ).fetchone()
    assert row is None


def test_credentials_aad_binding(tmp_path, monkeypatch):
    """AAD 绑定 (user, skill)：密文换属主读取 → 解密失败（防跨用户互换，§13 权限隔离）。"""
    monkeypatch.setenv("STORE_MASTER_KEY", "cd" * 32)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    with db.connect() as conn:
        db.put_credentials(conn, "alice", "s1", {"api_key": "k"})
        blob = conn.execute("SELECT cred_json FROM user_skill_credentials").fetchone()["cred_json"]
    assert db._decrypt("alice", "s1", blob) == {"api_key": "k"}
    with pytest.raises(RuntimeError, match="解密失败"):
        db._decrypt("bob", "s1", blob)  # AAD 不符
    with pytest.raises(RuntimeError, match="解密失败"):
        db._decrypt("alice", "s2", blob)  # 技能不符


# ---- 官方 MCP 目录（connector catalog）----


def _write_connector(dir_path, skill_id, intent, default_status="inactive", extra=None):
    """写一个 connector JSON 到临时目录。"""
    dir_path.mkdir(parents=True, exist_ok=True)
    m = {
        "skill_id": skill_id,
        "name": skill_id,
        "description": "catalog test",
        "icon": "📦",
        "intent": intent,
        "entry_tool": "get_weather",
        "mcp_server": {"transport": "http", "url": "http://127.0.0.1:9100/mcp"},
        "credentials": {"type": "none"},
        "tools": [],
    }
    if extra:
        m.update(extra)
    (dir_path / f"{skill_id}.json").write_text(
        json.dumps({**m, "default_status": default_status}, ensure_ascii=False), encoding="utf-8"
    )


def _skill_row(skill_id):
    with db.connect() as conn:
        return conn.execute(
            "SELECT skill_id, status, publisher, manifest FROM skills WHERE skill_id=?",
            (skill_id,),
        ).fetchone()


def test_catalog_sync_new_connector_default_inactive(client, tmp_path):
    """新 connector 落库：status 取 default_status（inactive）、publisher='catalog'、manifest 可解析。"""
    _write_connector(tmp_path / "c", "cat-a", "cat_a")
    result = catalog.sync_catalog(dir_path=tmp_path / "c")
    assert result["synced"] == ["cat-a"]
    row = _skill_row("cat-a")
    assert row is not None and row["status"] == "inactive"
    assert row["publisher"] == catalog.CATALOG_PUBLISHER
    assert json.loads(row["manifest"])["intent"] == "cat_a"
    # inactive 不在用户目录可见
    assert all(s["skill_id"] != "cat-a" for s in client.get("/skills").json()["skills"])


def test_catalog_sync_default_status_active(client, tmp_path):
    """default_status=active → 新行直接上架，进用户目录。"""
    _write_connector(tmp_path / "c", "cat-b", "cat_b", default_status="active")
    catalog.sync_catalog(dir_path=tmp_path / "c")
    assert _skill_row("cat-b")["status"] == "active"
    assert any(s["skill_id"] == "cat-b" for s in client.get("/skills").json()["skills"])


def test_catalog_sync_preserves_existing_status(client, tmp_path):
    """已有 active 的同 skill_id 同步后 status 不变（管理员上架/下架不被目录覆盖）。"""
    d = tmp_path / "c"
    _write_connector(d, "cat-c", "cat_c", default_status="inactive")
    catalog.sync_catalog(dir_path=d)  # 先按 inactive 落库
    # 管理员把它上架
    row = _skill_row("cat-c")
    client.post("/skills", json={"manifest": json.loads(row["manifest"]), "status": "active"})
    assert _skill_row("cat-c")["status"] == "active"
    # 再同步（文件仍是 inactive）→ status 保留 active
    catalog.sync_catalog(dir_path=d)
    assert _skill_row("cat-c")["status"] == "active"


def test_catalog_sync_idempotent_no_bump(client, tmp_path):
    """manifest 未变再同步：不重复写、不 bump（synced/bumped 为空）。"""
    d = tmp_path / "c"
    _write_connector(d, "cat-d", "cat_d", default_status="active")
    catalog.sync_catalog(dir_path=d)
    first = catalog.sync_catalog(dir_path=d)
    assert first == {"synced": [], "bumped": 0}


def test_catalog_sync_manifest_change_bumps_holders(client, tmp_path):
    """manifest 变化 → 给已选购用户 bump 版本（热插拔生效）。"""
    d = tmp_path / "c"
    _write_connector(d, "cat-e", "cat_e", default_status="active")
    catalog.sync_catalog(dir_path=d)
    client.put("/me/skills", json={"user_id": "u1", "skill_ids": ["cat-e"]})
    v0 = client.get("/me/skills/sync", params={"user_id": "u1"}).json()["version"]
    # 改动 manifest（换描述）再同步
    _write_connector(d, "cat-e", "cat_e", default_status="active", extra={"description": "v2"})
    result = catalog.sync_catalog(dir_path=d)
    assert result["synced"] == ["cat-e"]
    v1 = client.get("/me/skills/sync", params={"user_id": "u1"}).json()["version"]
    assert v1 == v0 + 1


def test_catalog_sync_endpoint(client, monkeypatch):
    """POST /skills/catalog/sync 回显 sync_catalog 结果。"""
    monkeypatch.setattr(
        catalog, "sync_catalog", lambda *a, **k: {"synced": ["weather-mcp"], "bumped": 2}
    )
    res = client.post("/skills/catalog/sync").json()
    assert res == {"ok": True, "synced": ["weather-mcp"], "bumped": 2}


def test_sync_all_endpoint(client, monkeypatch):
    """统一同步入口同时汇总 connector 与内置能力结果。"""
    monkeypatch.setattr(
        catalog, "sync_catalog", lambda *a, **k: {"synced": ["remote"], "bumped": 1}
    )
    monkeypatch.setattr(
        builtin_catalog, "sync_catalog", lambda: {"synced": ["builtin:calendar_create"], "count": 1}
    )
    res = client.post("/skills/sync-all").json()
    assert res == {
        "ok": True,
        "synced": ["remote", "builtin:calendar_create"],
        "bumped": 1,
        "builtin_count": 1,
    }


def test_status_endpoint_supports_builtin_skill(client, monkeypatch):
    """内置技能也能统一上下架，且状态不会被目录同步覆盖。"""
    client.post(
        "/internal/builtin-skills/sync",
        json={"skills": [{
            "kind": "builtin", "skill_id": "builtin:calendar_create",
            "name": "日程", "intent": "calendar_create",
        }]},
    )
    r = client.put("/skills/builtin:calendar_create/status", json={"status": "inactive"})
    assert r.status_code == 200
    assert r.json()["status"] == "inactive"
    assert client.get("/skills").json()["skills"] == []



def test_catalog_admin_grouping(client, tmp_path):
    """/skills/admin 返回 publisher，管理页据此分「官方目录」vs「自定义 MCP」。"""
    _write_connector(tmp_path / "c", "cat-f", "cat_f", default_status="inactive")
    catalog.sync_catalog(dir_path=tmp_path / "c")
    client.post("/skills", json={"manifest": {**SAMPLE, "skill_id": "custom-1"}})
    rows = client.get("/skills/admin").json()["skills"]
    by_id = {r["skill_id"]: r for r in rows}
    assert by_id["cat-f"]["publisher"] == catalog.CATALOG_PUBLISHER
    assert by_id["custom-1"]["publisher"] == "poc"
