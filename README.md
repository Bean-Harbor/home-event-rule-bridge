# Home Event Rule Bridge

Describe a Home Assistant rule in Discord. Review a readable draft. Confirm before anything changes.

Home Assistant is powerful, but creating a small rule still means thinking in entities, triggers, conditions, services, and YAML. This project tries a lower-friction workflow:

```text
"Let me know if the HarborDock test switch goes offline"
        |
        v
Readable rule draft
        |
        v
show yaml / edit / cancel / confirm
```

The bridge reads your Home Assistant entity list, drafts an automation from a chat message, and waits for explicit approval. Dry-run mode is the default.

## Discord Docker Quick Start

Docker Compose is the easiest way to try the Discord bridge on a NAS, mini PC, or a machine near your Home Assistant instance.

If you are helping test the Discord path, start with the [private tester guide](docs/private-tester-guide.md).

```powershell
cp examples/.env.example .env
```

If you prefer a browser form, use the one-time setup portal:

```powershell
docker compose --profile setup up --build setup
```

Open the printed setup URL, or set `SETUP_PUBLIC_URL=http://<lan-ip>:8788` before starting the setup profile and scan the QR from a phone on the same network.

Or edit `.env` manually and set:

```text
DISCORD_BOT_TOKEN=...
DISCORD_APPLICATION_ID=...
DISCORD_ALLOWED_CHANNEL_IDS=...
HA_URL=http://homeassistant.local:8123
HA_TOKEN=...
ALLOW_WRITE_AUTOMATIONS=false
```

Check the setup without starting the bot:

```powershell
docker compose run --rm bridge doctor --mode discord
```

Start the Discord bridge:

```powershell
docker compose up --build
```

In Discord, try:

```text
devices
find harbordock
Let me know if the HarborDock test switch goes offline
```

The full first-run smoke list is in `examples/smoke-prompts.txt`.

Dry-run is the default. With `ALLOW_WRITE_AUTOMATIONS=false`, the bridge does not write Home Assistant files.

## Discord QR Setup

The QR setup flow opens a local setup page. It is not a Discord account QR login, and it does not put Discord or Home Assistant tokens inside the QR code.

Run the setup portal:

```powershell
home-rule-bridge setup-discord --host 127.0.0.1 --port 8788 --env-file .env
```

For a phone on the same LAN:

```powershell
$env:SETUP_PUBLIC_URL="http://<lan-ip>:8788"
docker compose --profile setup up --build setup
```

The page asks for:

```text
Discord Bot Token
Discord Application ID
Allowed Channel IDs
HA URL
HA Token
```

The Application ID lets the page build an `Add to Discord` link. The bot still belongs to your Discord Developer Portal account. In that portal, enable `Message Content Intent` for the bot before running the bridge.

After saving setup:

```powershell
docker compose run --rm bridge doctor --mode discord
docker compose up --build
```

## Python Quick Demo

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,discord]"

home-rule-bridge demo "If driveway motion happens when nobody is home, message me" --states fixtures\ha_states.json
```

Expected shape:

```text
Draft ready.
Meaning: Notify on driveway motion with optional occupancy context.
When: binary_sensor.driveway_motion -> on
If: group.family == not_home
Do: persistent_notification.create (Driveway motion)
Matched: binary_sensor.driveway_motion (Driveway motion), group.family (Family)
Safety: dry-run until confirmed

Reply with `confirm`, `edit <clearer rule>`, `cancel`, or `show yaml`.
```

## Discord Smoke Test

This is the workflow the project is trying to make feel normal:

```text
you:
Let me know if the HarborDock test switch goes offline

bot:
Draft ready.
Meaning: Notify when a selected device becomes unavailable.
When: switch.harbordock_test_switch -> unavailable
If: none
Do: persistent_notification.create (Device offline)
Matched: switch.harbordock_test_switch (HarborDock Test Switch)
Safety: dry-run until confirmed
Confidence: 0.76

Reply with `confirm`, `edit <clearer rule>`, `cancel`, or `show yaml`.

you:
show yaml

bot:
YAML preview for draft_xxxxx:
...

you:
ok

bot:
Confirmed draft_xxxxx.
Dry-run mode: no Home Assistant files were changed.
```

For a local dry smoke with fixture data:

```powershell
home-rule-bridge eval --states fixtures\ha_states.json --prompts examples\smoke-prompts.txt
home-rule-bridge eval --states fixtures\ha_states_harbordock_lab.json --prompts examples\smoke-prompts.txt
```

One private Discord dogfood run is recorded in `docs/smoke/2026-07-05-discord-dogfood.md`.

## Why This Exists

Most smart-home alerts start easy and then turn into noise. Motion detected. Device offline. Person seen. Door opened. The hard part is not sending more alerts. The useful part is turning a household sentence into a reviewable rule with the right device, condition, and action.

The first working path is intentionally narrow:

- Use natural language as the entry point.
- Resolve real Home Assistant entities instead of inventing ids.
- Show a readable draft before YAML.
- Ask for clarification when the bridge is unsure.
- Keep the write path explicit and conservative.

## Who This Is For

- Home Assistant users who already use automations.
- Self-hosters running HA on Docker, NAS, mini PC, Proxmox, or a similar host.
- People who want a safer way to draft rules from plain language before editing YAML.
- Households where simple alerts became noisy and need more context.

If you mostly want a finished consumer app, this repo will feel too early. It is closer to a small tool for people who already run HA and do not mind a bit of setup.

## Hardware Expectations

- HA Green, Raspberry Pi, or similar small hosts: start with `rules-only`, or point the bridge at a model running somewhere else.
- mini PC, NAS, Proxmox, or Docker host: a better fit for local model parsing.
- Remote model endpoint: useful for development, but entity metadata may leave your local machine or LAN.

You do not need a local model to try the basic flow.

## What It Does

- Reads Home Assistant entities through the local HA API.
- Parses a Discord or Telegram message into a structured `RuleDraft`.
- Produces a human-readable rule card first.
- Shows YAML only when the user asks for it.
- Supports `confirm`, `ok`, or `yes` for the latest draft.
- Keeps each Discord user's pending draft separate in a shared channel.
- Defaults to dry-run mode.
- Can optionally write to one Home Assistant package file after confirmation.

## What It Does Not Do

- It does not expose your Home Assistant instance publicly.
- It does not change Home Assistant unless write mode is enabled.
- It does not execute high-risk device actions by default.
- It does not replace Home Assistant's automation engine.
- With the default parser, it does not send HA metadata to a model endpoint.
- If you configure a remote OpenAI-compatible provider, selected entity metadata is sent to that endpoint.

## Current Limits

- The rule parser handles a small set of common household patterns today.
- Real package, pet, or camera understanding must come from your existing HA entities.
- `disable rule` and `delete rule` currently update bridge-managed state; package-file rewriting is still limited.
- Model quality depends on the local endpoint and hardware you choose.

## Discord Setup

Create a Discord application and bot in the Discord Developer Portal, then:

1. Enable the bot's `Message Content Intent`.
2. Invite the bot to your test server with permission to view channels, send messages, and read message history.
3. Copy `examples/.env.example` to `.env`.
4. Fill in the local settings:

```text
DISCORD_BOT_TOKEN=...
DISCORD_APPLICATION_ID=...
DISCORD_ALLOWED_CHANNEL_IDS=
HA_URL=http://homeassistant.local:8123
HA_TOKEN=...
ALLOW_WRITE_AUTOMATIONS=false
```

Install and run:

```powershell
pip install -e ".[discord]"
home-rule-bridge doctor
home-rule-bridge run-discord
```

If `DISCORD_ALLOWED_CHANNEL_IDS` is set, the bot listens in those channels. If it is empty, the bot only responds in DMs or when mentioned in a server channel.

## Common Commands

```text
help
status
devices
find <text>
show yaml
show yaml <draft_id_or_rule_id>
confirm
ok
cancel
edit <clearer rule sentence>
list rules
show rule <rule_id>
disable rule <rule_id>
delete rule <rule_id>
```

If the bridge is missing a device or condition, it asks a short clarification question. You can reply with a numbered entity, a full entity id, or a clearer rule sentence.

## Telegram Mode

Telegram is kept as a simple polling option for power users.

```text
TELEGRAM_BOT_TOKEN=...
TELEGRAM_ALLOWED_CHAT_IDS=
HA_URL=http://homeassistant.local:8123
HA_TOKEN=...
```

```powershell
pip install -e .
home-rule-bridge run
```

## Safety Model

Every draft goes through:

1. Schema checks.
2. Entity resolution against the current HA snapshot.
3. Service allowlist.
4. Human confirmation.

The default low-risk actions are notifications, lights, switches, scenes, and scripts. High-risk domains such as locks, covers, alarms, and vacuums are blocked or kept draft-only by default.

When the bridge is unsure, it asks for clarification instead of guessing.

## Write Mode

Dry-run is the default. To let the bridge write a Home Assistant package file:

```text
ALLOW_WRITE_AUTOMATIONS=true
HA_CONFIG_DIR=/config
```

The bridge only writes:

```text
packages/home_event_rule_bridge.yaml
```

Write mode refuses to commit unless `configuration.yaml` appears to enable Home Assistant packages. After a confirmed write, it calls `automation.reload` through Home Assistant.

For an optional local audit trail:

```text
BRIDGE_AUDIT_LOG=audit/home_event_rule_bridge.jsonl
```

## NSP Profiles

Use `NSP_PROFILE` to choose how the bridge parses plain language:

- `rules-only`: no model, minimal setup.
- `fast`: small local model, mapped to `qwen3:0.6b`.
- `balanced`: better local parsing on stronger hardware, mapped to `qwen3:1.7b`.
- `remote-dev`: OpenAI-compatible endpoint for development. Entity metadata may leave this machine or LAN.

```text
NSP_PROFILE=rules-only
```

For `fast`, `balanced`, or `remote-dev`, run an OpenAI-compatible endpoint such as llama.cpp or Ollama:

```text
NSP_PROFILE=balanced
OPENAI_COMPAT_BASE_URL=http://localhost:11434/v1
OPENAI_COMPAT_API_KEY=local
```

For privacy-sensitive homes, keep this endpoint on the same LAN machine.

Developer override:

```text
NSP_PROVIDER=openai-compatible
OPENAI_COMPAT_MODEL=qwen3:1.7b
```

When `NSP_PROFILE` is set, the profile decides the provider and default model.

## Open Questions

- Would this fit how you manage HA automations?
- What hardware do you run Home Assistant on?
- Would you run a small local model, or prefer `rules-only`?
- Which alerts became noise in your home?


## Test

```powershell
python -m pytest -q
python -m compileall -q src tests
home-rule-bridge demo "Let me know if a mystery device goes offline" --states fixtures\ha_states.json
home-rule-bridge eval --states fixtures\ha_states.json
home-rule-bridge eval --states fixtures\ha_states.json --prompts examples\smoke-prompts.txt
```

## Roadmap

- Better clarification flows for missing trigger, condition, and action.
- More Home Assistant entity matching tests from real setups.
- A local model parser with stricter schema repair.
- Safer rule disable/delete support for the managed package file.
- Optional screenshots or short demo clips once the interaction stabilizes.
