from __future__ import annotations

from pathlib import Path

from .ha import HomeAssistantClient
from .models import RuleDraft


class AutomationWriter:
    def __init__(
        self,
        allow_write: bool,
        ha_config_dir: Path | None,
        ha_client: HomeAssistantClient | None = None,
    ) -> None:
        self.allow_write = allow_write
        self.ha_config_dir = ha_config_dir
        self.ha_client = ha_client

    def commit(self, draft: RuleDraft, automation_yaml: str) -> str:
        if not self.allow_write:
            return "Dry-run mode: no Home Assistant files were changed."
        if self.ha_config_dir is None:
            raise RuntimeError("HA_CONFIG_DIR is required when ALLOW_WRITE_AUTOMATIONS=true")
        config_root = self.ha_config_dir.resolve()
        package_dir = (config_root / "packages").resolve()
        target = (package_dir / "home_event_rule_bridge.yaml").resolve()
        if config_root not in target.parents:
            raise RuntimeError("refusing to write outside HA_CONFIG_DIR")
        package_dir.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("automation:\n", encoding="utf-8")
        with target.open("a", encoding="utf-8") as handle:
            handle.write("\n")
            for line in automation_yaml.splitlines():
                handle.write("  " + line + "\n")
        if self.ha_client is not None:
            self.ha_client.call_service("automation", "reload", {})
        return f"Wrote {target} and requested automation.reload."

