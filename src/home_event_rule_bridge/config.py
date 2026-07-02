from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _csv_env(name: str) -> set[str]:
    raw = os.environ.get(name, "")
    return {item.strip() for item in raw.split(",") if item.strip()}


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str | None
    telegram_allowed_chat_ids: set[str]
    discord_bot_token: str | None
    discord_allowed_channel_ids: set[str]
    ha_url: str | None
    ha_token: str | None
    nsp_provider: str
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    allow_write_automations: bool
    ha_config_dir: Path | None
    audit_log_path: Path | None

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv()
        config_dir = os.environ.get("HA_CONFIG_DIR") or None
        audit_log = os.environ.get("BRIDGE_AUDIT_LOG") or None
        return cls(
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN") or None,
            telegram_allowed_chat_ids=_csv_env("TELEGRAM_ALLOWED_CHAT_IDS"),
            discord_bot_token=os.environ.get("DISCORD_BOT_TOKEN") or None,
            discord_allowed_channel_ids=_csv_env("DISCORD_ALLOWED_CHANNEL_IDS"),
            ha_url=os.environ.get("HA_URL") or None,
            ha_token=os.environ.get("HA_TOKEN") or None,
            nsp_provider=os.environ.get("NSP_PROVIDER", "rules").strip().lower(),
            openai_base_url=os.environ.get("OPENAI_COMPAT_BASE_URL", "http://localhost:11434/v1"),
            openai_api_key=os.environ.get("OPENAI_COMPAT_API_KEY", "local"),
            openai_model=os.environ.get("OPENAI_COMPAT_MODEL", "qwen3:1.7b"),
            allow_write_automations=_bool_env("ALLOW_WRITE_AUTOMATIONS", False),
            ha_config_dir=Path(config_dir) if config_dir else None,
            audit_log_path=Path(audit_log) if audit_log else None,
        )
