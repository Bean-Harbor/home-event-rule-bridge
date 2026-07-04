from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from home_event_rule_bridge.config import Settings
from home_event_rule_bridge.nsp import OpenAICompatibleParser, RuleBasedParser, build_parser


ENV_KEYS = {
    "NSP_PROFILE",
    "NSP_PROVIDER",
    "OPENAI_COMPAT_BASE_URL",
    "OPENAI_COMPAT_API_KEY",
    "OPENAI_COMPAT_MODEL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_ALLOWED_CHAT_IDS",
    "DISCORD_BOT_TOKEN",
    "DISCORD_ALLOWED_CHANNEL_IDS",
    "HA_URL",
    "HA_TOKEN",
    "ALLOW_WRITE_AUTOMATIONS",
    "HA_CONFIG_DIR",
    "BRIDGE_AUDIT_LOG",
}


class SettingsProfileTests(unittest.TestCase):
    def settings_from(self, env: dict[str, str]) -> Settings:
        old_env = {key: os.environ.get(key) for key in ENV_KEYS}
        old_cwd = Path.cwd()
        try:
            for key in ENV_KEYS:
                os.environ.pop(key, None)
            os.environ.update(env)
            with tempfile.TemporaryDirectory() as temp:
                try:
                    os.chdir(temp)
                    settings = Settings.from_env()
                finally:
                    os.chdir(old_cwd)
                return settings
        finally:
            for key in ENV_KEYS:
                os.environ.pop(key, None)
                if old_env[key] is not None:
                    os.environ[key] = old_env[key] or ""

    def test_default_profile_is_rules_only(self) -> None:
        settings = self.settings_from({})
        self.assertEqual(settings.nsp_profile, "rules-only")
        self.assertEqual(settings.nsp_provider, "rules")
        self.assertEqual(settings.openai_model, "")
        self.assertIsInstance(build_parser(settings), RuleBasedParser)

    def test_fast_profile_maps_to_small_model(self) -> None:
        settings = self.settings_from({"NSP_PROFILE": "fast"})
        self.assertEqual(settings.nsp_provider, "openai-compatible")
        self.assertEqual(settings.openai_model, "qwen3:0.6b")
        self.assertIsInstance(build_parser(settings), OpenAICompatibleParser)

    def test_balanced_profile_maps_to_default_local_model(self) -> None:
        settings = self.settings_from({"NSP_PROFILE": "balanced"})
        self.assertEqual(settings.nsp_provider, "openai-compatible")
        self.assertEqual(settings.openai_model, "qwen3:1.7b")

    def test_legacy_provider_and_model_still_work_without_profile(self) -> None:
        settings = self.settings_from(
            {
                "NSP_PROVIDER": "openai-compatible",
                "OPENAI_COMPAT_MODEL": "custom-local-model",
            }
        )
        self.assertEqual(settings.nsp_profile, "custom")
        self.assertEqual(settings.nsp_provider, "openai-compatible")
        self.assertEqual(settings.openai_model, "custom-local-model")


if __name__ == "__main__":
    unittest.main()
