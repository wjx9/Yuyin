from __future__ import annotations

from skill_store import builtin_catalog
from mcp_skill.manifest import SkillManifest


def test_builtin_catalog_contains_always_available_mobile_actions(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    manifests = builtin_catalog.build_manifests()
    ids = {m["intent"] for m in manifests}
    assert {"chitchat", "calendar_create", "alarm_create", "timer_create", "reminder_create"} <= ids


def test_builtin_catalog_filters_missing_provider_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini")
    monkeypatch.delenv("AMAP_KEY", raising=False)
    manifests = builtin_catalog.build_manifests()
    ids = {m["intent"] for m in manifests}
    assert "amap_weather_live" not in ids


def test_builtin_manifest_can_be_read_by_registry_model():
    manifest = SkillManifest.from_dict({
        "kind": "builtin",
        "skill_id": "builtin:calendar_create",
        "name": "日程",
        "description": "创建日程",
        "intent": "calendar_create",
        "always_enabled": True,
    })
    assert manifest.kind == "builtin"
    assert manifest.entry_tool == ""
    assert manifest.mcp_server == {}
