from __future__ import annotations

import contextlib
import io
import os
import re
import tempfile
import unittest
from pathlib import Path

from home_event_rule_bridge.approval import ApprovalStore
from home_event_rule_bridge.bridge import RuleBridge
from home_event_rule_bridge.cli import build_arg_parser, cmd_doctor
from home_event_rule_bridge.ha import EntitySnapshot
from home_event_rule_bridge.nsp import RuleBasedParser
from home_event_rule_bridge.writer import AutomationWriter

ROOT = Path(__file__).resolve().parents[1]

BANNED_PUBLIC_TERMS = [
    r"\bpretest\b",
    r"\bvalidation\b",
    r"\bgtm\b",
    r"\bconversion\b",
    r"\bseed users\b",
    r"\bwedge\b",
    r"\bfunnel\b",
]


class PublicSurfaceTests(unittest.TestCase):
    def assert_public_text(self, label: str, text: str) -> None:
        for pattern in BANNED_PUBLIC_TERMS:
            with self.subTest(label=label, pattern=pattern):
                self.assertIsNone(re.search(pattern, text, flags=re.IGNORECASE))

    def test_public_files_do_not_use_internal_terms(self) -> None:
        for path in [
            ROOT / "README.md",
            ROOT / "examples" / ".env.example",
            ROOT / "pyproject.toml",
        ]:
            self.assert_public_text(str(path), path.read_text(encoding="utf-8"))

    def test_cli_help_doctor_and_bot_status_do_not_use_internal_terms(self) -> None:
        self.assert_public_text("cli help", build_arg_parser().format_help())

        old_env = dict(os.environ)
        old_cwd = Path.cwd()
        try:
            for key in list(os.environ):
                if key.startswith(("NSP_", "OPENAI_COMPAT_", "HA_", "DISCORD_", "TELEGRAM_", "ALLOW_WRITE_", "BRIDGE_")):
                    os.environ.pop(key, None)
            with tempfile.TemporaryDirectory() as temp:
                try:
                    os.chdir(temp)
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        cmd_doctor(object())
                finally:
                    os.chdir(old_cwd)
            self.assert_public_text("doctor", output.getvalue())
        finally:
            os.environ.clear()
            os.environ.update(old_env)

        bridge = RuleBridge(RuleBasedParser(), ApprovalStore(), AutomationWriter(False, None))
        reply = bridge.handle_text("chat", "help", EntitySnapshot.empty())
        self.assert_public_text("bot help", reply.text)


if __name__ == "__main__":
    unittest.main()
