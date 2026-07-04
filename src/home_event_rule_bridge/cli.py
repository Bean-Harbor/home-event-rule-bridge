from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from .audit import AuditLogger
from .approval import ApprovalStore
from .bridge import RuleBridge
from .compiler import validate_draft
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
        audit=AuditLogger(settings.audit_log_path),
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
    local_model_endpoint = settings.uses_model and settings.openai_base_url.startswith(("http://localhost", "http://127.0.0.1"))
    checks = {
        "telegram_token": bool(settings.telegram_bot_token),
        "discord_token": bool(settings.discord_bot_token),
        "discord_allowed_channel_count": len(settings.discord_allowed_channel_ids),
        "ha_url": bool(settings.ha_url),
        "ha_token": bool(settings.ha_token),
        "nsp_profile": settings.nsp_profile,
        "nsp_provider": settings.nsp_provider,
        "nsp_model": settings.openai_model or "none",
        "nsp_base_url": settings.openai_base_url if settings.uses_model else "not used",
        "local_model_endpoint": local_model_endpoint,
        "write_mode": settings.allow_write_automations,
        "ha_config_dir": str(settings.ha_config_dir) if settings.ha_config_dir else None,
        "audit_log_path": str(settings.audit_log_path) if settings.audit_log_path else None,
    }
    for key, value in checks.items():
        print(f"{key}: {value}")
    if settings.ha_url and settings.ha_token:
        count = len(HomeAssistantClient(settings.ha_url, settings.ha_token).states().states)
        print(f"ha_state_count: {count}")
    return 0


def cmd_eval(args) -> int:
    settings = Settings.from_env()
    snapshot = _load_snapshot(args, settings)
    parser = build_parser(settings)
    prompts = _load_prompts(Path(args.prompts))
    if not prompts:
        raise SystemExit(f"No prompts found in {args.prompts}")

    ready = 0
    clarify = 0
    blocked = 0
    invalid_entity = 0

    print(f"profile: {settings.nsp_profile}")
    print(f"parser: {parser.display_name}")
    print(f"prompts: {len(prompts)}")
    print()

    for index, prompt in enumerate(prompts, start=1):
        started = time.perf_counter()
        draft = parser.parse(prompt, snapshot)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        result = validate_draft(draft, snapshot)
        visible_errors = [item for item in result.errors if "None" not in item]
        has_unknown_entity = any("unknown" in item for item in visible_errors)
        invalid_entity += int(has_unknown_entity)
        if result.ok and not draft.missing_slots and draft.confidence >= 0.60:
            status = "ready"
            ready += 1
        elif draft.missing_slots or draft.confidence < 0.60:
            status = "clarify"
            clarify += 1
        else:
            status = "blocked"
            blocked += 1
        print(f"{index}. {status} confidence={draft.confidence:.2f} latency_ms={elapsed_ms}")
        print(f"   {prompt}")
        print(f"   {draft.explanation}")
        if visible_errors:
            print(f"   errors: {'; '.join(visible_errors)}")

    print()
    print(f"summary: ready={ready} clarify={clarify} blocked={blocked} invalid_entity={invalid_entity}")
    return 0


def _load_prompts(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


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


def cmd_run_discord(args) -> int:
    settings = Settings.from_env()
    if not settings.discord_bot_token:
        raise SystemExit("DISCORD_BOT_TOKEN is required for run-discord mode.")
    ha_client = None
    if settings.ha_url and settings.ha_token:
        ha_client = HomeAssistantClient(settings.ha_url, settings.ha_token)
    bridge = _build_bridge(settings, ha_client)

    from .discord_bot import DiscordBot

    bot = DiscordBot(settings.discord_bot_token, settings.discord_allowed_channel_ids)

    def handle(chat_id: str, text: str) -> str:
        snapshot = ha_client.states() if ha_client else _load_snapshot(args, settings)
        return bridge.handle_text(chat_id, text, snapshot).text

    bot.run(handle)
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

    run_discord = sub.add_parser("run-discord", help="Run the Discord bridge.")
    run_discord.add_argument("--states", help="Optional fixture path when HA_URL/HA_TOKEN are not configured.")
    run_discord.set_defaults(func=cmd_run_discord)

    doctor = sub.add_parser("doctor", help="Check local configuration.")
    doctor.set_defaults(func=cmd_doctor)

    eval_parser = sub.add_parser("eval", help="Run fixed rule prompts against the configured parser.")
    eval_parser.add_argument("--states", help="Path to a Home Assistant states JSON fixture.")
    eval_parser.add_argument("--prompts", default="examples/eval-prompts.txt", help="Path to a prompt list.")
    eval_parser.set_defaults(func=cmd_eval)
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
