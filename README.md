# Home Event Rule Bridge

Create Home Assistant rule drafts from IM messages, with local-first parsing and explicit approval.

This is a small wedge project for people who already use Home Assistant and want a calmer way to create household rules:

```text
"When driveway motion happens while nobody is home, message me."
        |
        v
Rule draft + YAML preview
        |
        v
Confirm before anything can be written
```

It starts with Discord for the Home Assistant / open-source community, while keeping Telegram as the simplest polling option for power users.

## What it does

- Reads Home Assistant entities through the local HA API.
- Parses an IM message into a structured `RuleDraft`.
- Resolves entities against real HA state names instead of inventing ids.
- Produces a Home Assistant automation YAML preview.
- Requires `CONFIRM <draft_id>` before any write path.
- Defaults to dry-run mode.

## What it does not do

- It does not expose your Home Assistant instance publicly.
- With the default parser, it does not send HA metadata to any model endpoint.
- If you configure a remote OpenAI-compatible provider, selected entity metadata is sent to that endpoint.
- It does not execute high-risk device actions by default.
- It is not a replacement for Home Assistant.

## Quick start

```powershell
cd C:\Users\beanw\OpenSource\home-event-rule-bridge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
home-rule-bridge demo "If driveway motion happens when nobody is home, send me a message" --states fixtures\ha_states.json
```

Run tests:

```powershell
python -m pytest -q
```

## Discord mode

Discord is the recommended first testing channel for the GitHub wedge.

Create a Discord application and bot in the Discord Developer Portal, then:

1. Enable the bot's `Message Content Intent`.
2. Invite the bot to your test server with permission to view channels and send messages.
3. Copy `examples/.env.example` to `.env` and fill:

```text
DISCORD_BOT_TOKEN=...
DISCORD_ALLOWED_CHANNEL_IDS=...
HA_URL=http://homeassistant.local:8123
HA_TOKEN=...
```

Install the optional Discord dependency:

```powershell
pip install -e .[discord]
```

Start the bridge:

```powershell
home-rule-bridge run-discord
```

If `DISCORD_ALLOWED_CHANNEL_IDS` is set, the bot listens in those channels. If it is empty, the bot only responds in DMs or when mentioned in a server channel.

Try sending:

```text
If a package is no longer visible on the porch, message me.
```

The bot will reply with a draft and YAML preview. Use:

```text
CONFIRM <draft_id>
CANCEL <draft_id>
```

## Telegram mode

Create a bot with BotFather, then copy `examples/.env.example` to `.env` and fill:

```text
TELEGRAM_BOT_TOKEN=...
HA_URL=http://homeassistant.local:8123
HA_TOKEN=...
```

Start the bridge:

```powershell
home-rule-bridge run
```

Try sending:

```text
If a package is no longer visible on the porch, message me.
```

The bot will reply with a draft and YAML preview. Use:

```text
CONFIRM <draft_id>
CANCEL <draft_id>
```

## Write mode

Dry-run is the default. To let the bridge write a package file, set:

```text
ALLOW_WRITE_AUTOMATIONS=true
HA_CONFIG_DIR=/config
```

The bridge only writes:

```text
packages/home_event_rule_bridge.yaml
```

After a confirmed write, it calls `automation.reload` through Home Assistant.

## NSP provider

The default provider is `rules`, a small local parser for the first test scenarios.

For local LLM parsing, run an OpenAI-compatible endpoint such as llama.cpp or Ollama and set:

```text
NSP_PROVIDER=openai-compatible
OPENAI_COMPAT_BASE_URL=http://localhost:11434/v1
OPENAI_COMPAT_API_KEY=local
OPENAI_COMPAT_MODEL=qwen3:1.7b
```

For privacy-sensitive homes, keep this endpoint on the same LAN machine.

Recommended product direction:

- Primary local NSP: Qwen3-1.7B.
- Low-memory fallback: Qwen3-0.6B.
- Larger LLMs should repair or explain, not directly control Home Assistant.

## Safety model

Every draft goes through:

1. Schema validation.
2. Entity resolution.
3. Service allowlist.
4. Human confirmation.

If the bridge is unsure, it asks for clarification instead of guessing.
