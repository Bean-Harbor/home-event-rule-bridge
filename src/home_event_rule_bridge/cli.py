from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .approval import ApprovalStore
from .bridge import RuleBridge
from .config import Settings
from .ha import EntitySnapshot, HomeAssistantClient
from .nsp import build_parser
from .telegram import TelegramBot
from .writer import AutomationWriter


def _load_snapshot(args, settings: Settings) -> EntitySnapshot:
    if getattr(args, "states", None):
        return EntitySnapshot.from_file(Path(args.states))
    if settings.ha_url and settings.ha_token:
        return HomeAssistantClient(settings.ha_url, settings.ha_token).states()
    default_fixture = Path("fixtures/ha_states.json")
    if default_fixture.exists():
        return EntitySnapshot.from_file(default_fixture)
    return EntitySnapshot.empty()


def _build_bridge(settings: Settings, ha_client: HomeAssistantClient | None) -> RuleBridge:
    return RuleBridge(
        parser=build_parser(settings),
        approvals=ApprovalStore(),
        writer=AutomationWriter(
            allow_write=settings.allow_write_automations,
            ha_config_dir=settings.ha_config_dir,
            ha_client=ha_client,
        ),
    )


def cmd_demo(args) -> int:
    settings = Settings.from_env()
    snapshot = _load_snapshot(args, settings)
    bridge = _build_bridge(settings, None)
    reply = bridge.handle_text("demo", args.text, snapshot)
    print(reply.text)
    return 0


def cmd_doctor(args) -> int:
    settings = Settings.from_env()
    checks = {
        "telegram_token": bool(settings.telegram_bot_token),
        "ha_url": bool(settings.ha_url),
        "ha_token": bool(settings.ha_token),
        "nsp_provider": settings.nsp_provider,
        "write_mode": settings.allow_write_automations,
        "ha_config_dir": str(settings.ha_config_dir) if settings.ha_config_dir else None,
    }
    for key, value in checks.items():
        print(f"{key}: {value}")
    if settings.ha_url and settings.ha_token:
        count = len(HomeAssistantClient(settings.ha_url, settings.ha_token).states().states)
        print(f"ha_state_count: {count}")
    return 0


def cmd_run(args) -> int:
    settings = Settings.from_env()
    if not settings.telegram_bot_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is required for run mode.")
    ha_client = None
    if settings.ha_url and settings.ha_token:
        ha_client = HomeAssistantClient(settings.ha_url, settings.ha_token)
    bridge = _build_bridge(settings, ha_client)
    bot = TelegramBot(settings.telegram_bot_token, settings.telegram_allowed_chat_ids)

    def handle(chat_id: str, text: str) -> str:
        snapshot = ha_client.states() if ha_client else _load_snapshot(args, settings)
        return bridge.handle_text(chat_id, text, snapshot).text

    bot.poll(handle)
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="home-rule-bridge")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="Parse one message and print the rule draft.")
    demo.add_argument("text")
    demo.add_argument("--states", help="Path to a Home Assistant states JSON fixture.")
    demo.set_defaults(func=cmd_demo)

    run = sub.add_parser("run", help="Run the Telegram polling bridge.")
    run.add_argument("--states", help="Optional fixture path when HA_URL/HA_TOKEN are not configured.")
    run.set_defaults(func=cmd_run)

    doctor = sub.add_parser("doctor", help="Check local configuration.")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
