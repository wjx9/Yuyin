from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any


APP_NAME = "myChatGPT"

PROVIDER_NAMES = ["openai", "aitogit_openai", "openai-compatible", "gemini", "claude"]

API_KEY_ENV_NAMES = {
    "openai": ("OPENAI_API_KEY", "openai_api_key"),
    "aitogit_openai": (
        "AITOGIT_OPENAI_API_KEY",
        "AITOGIT_API_KEY",
        "OPENAI_API_KEY",
        "openai_api_key",
    ),
    "openai-compatible": ("OPENAI_API_KEY", "openai_api_key"),
    "gemini": ("GEMINI_API_KEY", "GOOGLE_API_KEY", "gemini_api_key"),
    "claude": ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY", "anthropic_api_key"),
}


def app_data_dir() -> Path:
    base = os.environ.get("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME}"


def _getenv_case_insensitive(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value.strip()
    lower_name = name.lower()
    for key, candidate in os.environ.items():
        if key.lower() == lower_name and candidate:
            return candidate.strip()
    return ""


def _registry_env_get_case_insensitive(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg
    except Exception:
        return ""

    locations = [
        (winreg.HKEY_CURRENT_USER, r"Environment"),
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
    ]
    lower_name = name.lower()
    for hive, subkey in locations:
        try:
            with winreg.OpenKey(hive, subkey) as key_handle:
                index = 0
                while True:
                    try:
                        value_name, value, _value_type = winreg.EnumValue(key_handle, index)
                    except OSError:
                        break
                    if value_name.lower() == lower_name and value:
                        return str(value).strip()
                    index += 1
        except OSError:
            continue
    return ""


def _candidate_env_dirs() -> list[Path]:
    roots: list[Path] = []
    try:
        roots.append(Path.cwd())
    except OSError:
        pass
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    try:
        roots.append(Path(__file__).resolve().parent)
    except OSError:
        pass

    dirs: list[Path] = []
    for root in roots:
        for candidate in [root, *root.parents]:
            if candidate not in dirs:
                dirs.append(candidate)
            if len(dirs) >= 16:
                return dirs
    return dirs


def _parse_dotenv_value(raw: str) -> str:
    value = raw.strip()
    if not value:
        return ""
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        value = value[1:-1]
    return value.strip()


def _dotenv_get_case_insensitive(name: str) -> str:
    lower_name = name.lower()
    for directory in _candidate_env_dirs():
        path = directory / ".env"
        if not path.exists() or not path.is_file():
            continue
        try:
            for line in path.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                key = key.strip()
                if key.lower().startswith("export "):
                    key = key[7:].strip()
                if key.lower() == lower_name:
                    parsed = _parse_dotenv_value(value)
                    if parsed:
                        return parsed
        except OSError:
            continue
    return ""


def environment_api_key(provider: str) -> str:
    names = API_KEY_ENV_NAMES.get(provider.lower(), ())
    for name in names:
        value = _getenv_case_insensitive(name)
        if value:
            return value
    for name in names:
        value = _registry_env_get_case_insensitive(name)
        if value:
            return value
    for name in names:
        value = _dotenv_get_case_insensitive(name)
        if value:
            return value
    return ""


def effective_api_key(config: "AppConfig") -> str:
    if config.api_key.strip():
        return config.api_key.strip()
    return environment_api_key(config.provider)


def api_key_env_hint(provider: str) -> str:
    names = API_KEY_ENV_NAMES.get(provider.lower(), ())
    return ", ".join(names) if names else "对应 provider 的 API Key 环境变量"


@dataclass(slots=True)
class AppConfig:
    provider: str = "openai"
    api_key: str = ""
    model: str = "gpt-4.1-mini"
    base_url: str = "https://api.openai.com/v1"
    workspace: str = ""
    use_workspace: bool = True
    agent_mode: bool = False
    allow_write_tools: bool = False
    auto_speak: bool = False
    enable_web_search: bool = True
    temperature: float = 0.3
    max_output_tokens: int = 4096

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        valid = {field.name for field in fields(cls)}
        values = {key: value for key, value in data.items() if key in valid}
        cfg = cls(**values)
        cfg.provider = (cfg.provider or "openai").lower()
        return cfg

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def apply_provider_defaults(self) -> None:
        provider = self.provider.lower()
        if provider == "aitogit_openai":
            if not self.model or self.model.startswith(("gpt-4", "gemini", "claude")):
                self.model = "gpt-5.5"
            if not self.base_url or any(value in self.base_url for value in ("openai", "googleapis", "anthropic")):
                self.base_url = "https://api.aitogit.cc"
        elif provider == "gemini":
            if not self.model or self.model.startswith("gpt-"):
                self.model = "gemini-2.5-flash"
            if not self.base_url or "openai" in self.base_url or "aitogit" in self.base_url:
                self.base_url = "https://generativelanguage.googleapis.com/v1beta"
        elif provider == "claude":
            if not self.model or self.model.startswith("gpt-") or self.model.startswith("gemini"):
                self.model = "claude-3-5-sonnet-latest"
            if not self.base_url or "openai" in self.base_url or "googleapis" in self.base_url or "aitogit" in self.base_url:
                self.base_url = "https://api.anthropic.com"
        elif provider == "openai-compatible":
            if not self.model:
                self.model = "gpt-4.1-mini"
            if not self.base_url:
                self.base_url = "https://api.openai.com/v1"
        else:
            self.provider = "openai"
            if not self.model or self.model.startswith("gemini") or self.model.startswith("claude"):
                self.model = "gpt-4.1-mini"
            if not self.base_url or "googleapis" in self.base_url or "anthropic" in self.base_url or "aitogit" in self.base_url:
                self.base_url = "https://api.openai.com/v1"


class ConfigStore:
    def __init__(self, data_dir: Path | None = None) -> None:
        self.data_dir = data_dir or app_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "config.json"

    def load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return AppConfig()
        cfg = AppConfig.from_dict(data)
        cfg.apply_provider_defaults()
        return cfg

    def save(self, config: AppConfig) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


