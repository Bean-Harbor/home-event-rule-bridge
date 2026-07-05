from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from home_event_rule_bridge.setup_portal import (
    DISCORD_INVITE_PERMISSIONS,
    DiscordSetupPortal,
    SetupError,
    SetupPortalConfig,
    build_discord_invite_url,
)


class DiscordSetupPortalTests(unittest.TestCase):
    def make_portal(self, env_file: Path, port: int = 0) -> DiscordSetupPortal:
        return DiscordSetupPortal(
            SetupPortalConfig(
                host="127.0.0.1",
                port=port,
                env_file=env_file,
                public_url="http://127.0.0.1:8788",
                session_code="TEST-1234",
            )
        )

    def test_invite_url_uses_expected_scopes_and_permissions(self) -> None:
        url = build_discord_invite_url("1234567890")
        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, "discord.com")
        self.assertEqual(query["client_id"], ["1234567890"])
        self.assertEqual(query["permissions"], [str(DISCORD_INVITE_PERMISSIONS)])
        self.assertEqual(query["scope"], ["bot applications.commands"])

    def test_wrong_session_does_not_write_env(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / ".env"
            env_file.write_text("TELEGRAM_BOT_TOKEN=keep\n", encoding="utf-8")
            portal = self.make_portal(env_file)

            with self.assertRaises(SetupError):
                portal.save_discord_config(
                    {
                        "session_code": "WRONG",
                        "discord_bot_token": "discord-secret",
                        "ha_url": "http://ha.local:8123",
                        "ha_token": "ha-secret",
                    }
                )

            self.assertEqual(env_file.read_text(encoding="utf-8"), "TELEGRAM_BOT_TOKEN=keep\n")

    def test_save_merges_env_and_keeps_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / ".env"
            env_file.write_text(
                "TELEGRAM_BOT_TOKEN=keep\nALLOW_WRITE_AUTOMATIONS=true\nCUSTOM_KEY=keep-me\n",
                encoding="utf-8",
            )
            portal = self.make_portal(env_file)

            result = portal.save_discord_config(
                {
                    "session_code": "TEST-1234",
                    "discord_bot_token": "discord-secret",
                    "discord_application_id": "1234567890",
                    "discord_allowed_channel_ids": "111,222",
                    "ha_url": "http://ha.local:8123",
                    "ha_token": "ha-secret",
                }
            )

            text = env_file.read_text(encoding="utf-8")
            self.assertIn("TELEGRAM_BOT_TOKEN=keep", text)
            self.assertIn("CUSTOM_KEY=keep-me", text)
            self.assertIn("DISCORD_BOT_TOKEN=discord-secret", text)
            self.assertIn("DISCORD_APPLICATION_ID=1234567890", text)
            self.assertIn("DISCORD_ALLOWED_CHANNEL_IDS=111,222", text)
            self.assertIn("HA_URL=http://ha.local:8123", text)
            self.assertIn("HA_TOKEN=ha-secret", text)
            self.assertIn("ALLOW_WRITE_AUTOMATIONS=false", text)
            self.assertIn("NSP_PROFILE=rules-only", text)
            self.assertTrue(result["invite_url"].startswith("https://discord.com/oauth2/authorize?"))

    def test_status_redacts_secret_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / ".env"
            portal = self.make_portal(env_file)
            portal.save_discord_config(
                {
                    "session_code": "TEST-1234",
                    "discord_bot_token": "discord-secret",
                    "discord_application_id": "1234567890",
                    "discord_allowed_channel_ids": "111,222",
                    "ha_url": "http://ha.local:8123",
                    "ha_token": "ha-secret",
                }
            )

            status_json = json.dumps(portal.status(), sort_keys=True)
            self.assertIn('"discord_bot_token": "configured"', status_json)
            self.assertIn('"ha_token": "configured"', status_json)
            self.assertIn('"discord_allowed_channel_count": 2', status_json)
            self.assertNotIn("discord-secret", status_json)
            self.assertNotIn("ha-secret", status_json)
            self.assertNotIn("111", status_json)
            self.assertNotIn("222", status_json)

    def test_qr_endpoint_returns_svg_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            env_file = Path(temp) / ".env"
            env_file.write_text("DISCORD_BOT_TOKEN=discord-secret\nHA_TOKEN=ha-secret\n", encoding="utf-8")
            portal = self.make_portal(env_file, port=0)
            server = portal.make_server()
            host, port = server.server_address
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f"http://{host}:{port}/setup/qr.svg", timeout=5) as response:
                    body = response.read().decode("utf-8")
                    content_type = response.headers.get("Content-Type", "")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

            self.assertIn("image/svg+xml", content_type)
            self.assertIn("<svg", body)
            self.assertNotIn("discord-secret", body)
            self.assertNotIn("ha-secret", body)


if __name__ == "__main__":
    unittest.main()
