from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from home_event_rule_bridge.discord_bot import _clean_content, _message_chunks


class DiscordBotHelpersTests(unittest.TestCase):
    def test_clean_content_removes_bot_mentions(self) -> None:
        text = _clean_content("<@12345> If driveway motion happens, message me", 12345)
        self.assertEqual(text, "If driveway motion happens, message me")

    def test_message_chunks_stay_under_limit(self) -> None:
        chunks = _message_chunks("a" * 4500, limit=1900)
        self.assertEqual(len(chunks), 3)
        self.assertTrue(all(len(chunk) <= 1900 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()

