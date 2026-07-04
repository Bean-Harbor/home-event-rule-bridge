# Home Event Rule Bridge

Describe a Home Assistant rule in Discord. Review a readable draft. Confirm before anything changes.

Home Assistant is powerful, but creating a small rule still means thinking in entities, triggers, conditions, services, and YAML. This project tests a lower-friction workflow:

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

## Quick Demo

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,discord]"

home-rule-bridge demo "If driveway motion happens when nobody is home, message me" --states fixtures\ha_states.json
```

Expected shape:

```text
Draft ready.
Rule: Notify on driveway or garage motion with optional occupancy context.
Trigger: binary_sensor.driveway_motion -> on
Conditions: group.family == not_home
Actions: persistent_notification.create (Driveway motion)

Reply with `confirm`, `edit <clearer rule>`, `cancel`, or `show yaml`.
```

## Discord Smoke Test

This is the workflow the project is trying to make feel normal:

```text
you:
Let me know if the HarborDock test switch goes offline

bot:
Draft ready.
Rule: Notify when a selected device becomes unavailable.
Trigger: switch.harbordock_test_switch -> unavailable
Actions: persistent_notification.create (Device offline)
Confidence: 0.72

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

## Why This Exists

Most smart-home alerts start easy and then turn into noise. Motion detected. Device offline. Person seen. Door opened. The hard part is not sending more alerts. The useful part is turning a household sentence into a reviewable rule with the right device, condition, and action.

This repo starts with a narrow Home Assistant + Discord wedge:

- Use natural language as the entry point.
- Resolve real Home Assistant entities instead of inventing ids.
- Show a readable draft before YAML.
- Ask for clarification when the bridge is unsure.
- Keep the write path explicit and conservative.

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

## Discord Setup

Create a Discord application and bot in the Discord Developer Portal, then:

1. Enable the bot's `Message Content Intent`.
2. Invite the bot to your test server with permission to view channels, send messages, and read message history.
3. Copy `examples/.env.example` to `.env`.
4. Fill in the local settings:

```text
DISCORD_BOT_TOKEN=...
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

1. Schema validation.
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

## Local NSP / Local Model Path

The default parser is `rules`, a small local parser for the first test scenarios.

For local LLM parsing, run an OpenAI-compatible endpoint such as llama.cpp or Ollama and set:

```text
NSP_PROVIDER=openai-compatible
OPENAI_COMPAT_BASE_URL=http://localhost:11434/v1
OPENAI_COMPAT_API_KEY=local
OPENAI_COMPAT_MODEL=qwen3:1.7b
```

For privacy-sensitive homes, keep this endpoint on the same LAN machine.

Recommended direction:

- Primary local NSP: Qwen3-1.7B.
- Low-memory fallback: Qwen3-0.6B.
- Larger LLMs should repair or explain, not directly control Home Assistant.

## Test

```powershell
python -m pytest -q
python -m compileall -q src tests
home-rule-bridge demo "Let me know if a mystery device goes offline" --states fixtures\ha_states.json
```

## Roadmap

- Better clarification flows for missing trigger, condition, and action.
- More Home Assistant entity matching tests from real setups.
- A local model parser with stricter schema repair.
- Safer rule disable/delete support for the managed package file.
- Optional screenshots or short demo clips once the interaction stabilizes.
