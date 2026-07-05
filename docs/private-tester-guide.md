# Private Tester Guide

Home Event Rule Bridge lets you describe a small Home Assistant rule in Discord, review a readable draft, and decide what to do next. By default it runs in dry-run mode and does not write Home Assistant files.

This guide is for people who already run Home Assistant and are comfortable with Docker Compose, Discord Developer Portal, and long-lived HA tokens.

## What You Need

- A Home Assistant instance with a long-lived access token.
- A machine that can reach Home Assistant over the network.
- Docker Compose on that machine.
- A Discord account and a server or private test channel.
- A Discord bot that you create and own.

Start with `NSP_PROFILE=rules-only`. A local model is not required for this first pass.

## Create A Discord Bot

1. Open the Discord Developer Portal.
2. Create an application.
3. Copy the Application ID from General Information.
4. Open the Bot page and create a bot.
5. Copy the Bot Token.
6. Enable `Message Content Intent` for the bot.

The setup page can build an `Add to Discord` link from the Application ID. The bot token stays in your local `.env` file.

## Prepare `.env`

```powershell
cp examples/.env.example .env
```

You can fill the file manually, or use the QR setup page:

```powershell
docker compose --profile setup up --build setup
```

For phone setup on the same LAN:

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

Keep this setting for the first run:

```text
ALLOW_WRITE_AUTOMATIONS=false
```

## Check Readiness

```powershell
docker compose run --rm bridge doctor --mode discord
```

A good first result looks like:

```text
discord_token: configured
ha_url: configured
ha_token: configured
ha_state_count: <number>
nsp_profile: rules-only
write_mode: False
ready: yes
```

The command should not print your Discord token, HA token, or channel id.

## Start The Bridge

```powershell
docker compose up --build
```

In Discord, try the smoke messages from `examples/smoke-prompts.txt`:

```text
devices
find camera
Tell me if the front door camera goes offline
Turn on the hallway light when someone arrives home
Run the evening scene when I say movie time
cancel
```

Expected behavior:

- `devices` shows the Home Assistant entities the bridge can see.
- `find camera` either lists camera entities or says none were found.
- If a requested device is missing, the bot asks a clear question instead of guessing.
- If a close candidate exists, the bot lists numbered candidates.
- `show yaml` shows the YAML preview for the latest draft.
- `confirm` or `ok` only confirms the draft. With `ALLOW_WRITE_AUTOMATIONS=false`, no HA files are changed.
- `cancel` cancels the current draft.

## Feedback Format

Please send:

```text
Host type:
Home Assistant install type:
HA entity count from doctor:
Did doctor show ready: yes/no?
Which Discord smoke messages worked?
Which reply was confusing?
Did any reply feel unsafe or too confident?
Would you prefer rules-only, local model, or remote model for parsing?
```

Do not share your Discord bot token, HA token, or private channel ids.
