# Troubleshooting

Home Event Rule Bridge is still a small self-hosted tool. Most first-run issues come from Discord bot setup, Docker permissions, or Home Assistant connectivity.

Do not paste Discord bot tokens, Home Assistant tokens, private channel ids, or full `.env` files into GitHub issues.

## `docker compose` cannot talk to Docker

Typical message:

```text
permission denied while trying to connect to the Docker daemon socket
```

What to check:

- Run Docker Compose from an account that can use Docker.
- On Linux, your user may need Docker group access or you may need to run the command with your normal admin flow.
- After changing group membership, log out and back in before trying again.

## Docker Hub times out

Typical message:

```text
failed to fetch anonymous token
```

What to check:

- Try again later or from a network that can reach Docker Hub.
- If this happens on a private host, first confirm the repo still works locally with `python -m pytest -q`.
- Avoid changing Home Assistant settings just to work around an image pull issue.

## Bot does not reply in Discord

Check:

- `docker compose ps` shows the bridge service is running.
- `docker compose logs --tail=80 bridge` shows the bot logged in.
- `DISCORD_BOT_TOKEN` is configured.
- The bot has been added to the Discord server.
- `Message Content Intent` is enabled in the Discord Developer Portal.
- If `DISCORD_ALLOWED_CHANNEL_IDS` is set, the current channel id is included.

Try a DM to the bot. If DMs work but a server channel does not, it is usually a channel permission or allowlist issue.

## Bot replies twice

This usually means two bridge processes are running with the same Discord bot token.

Check:

```powershell
docker compose ps
docker compose logs --tail=80 bridge
```

Stop extra local runs such as:

```powershell
home-rule-bridge run-discord
```

Keep one Docker Compose service or one local process, not both.

## `doctor` cannot reach Home Assistant

Check:

- `HA_URL` is reachable from the machine running the bridge.
- `HA_TOKEN` is a long-lived Home Assistant access token.
- The token belongs to a user that can read entity states.
- The URL includes the scheme, for example `http://homeassistant.local:8123`.

Run:

```powershell
docker compose run --rm bridge doctor --mode discord
```

The output should show a numeric `ha_state_count`.

## `doctor` is ready but the bot cannot find my device

Try:

```text
devices
find camera
find switch
find <room or device name>
```

The bridge can only match entities present in the current Home Assistant snapshot. If the entity is missing there, the bot should ask a clarification question instead of guessing.

## `show yaml` works, but nothing changed in Home Assistant

That is expected with the default setup.

```text
ALLOW_WRITE_AUTOMATIONS=false
```

Dry-run mode is the recommended first run. It lets you check whether the bot understands the rule before any Home Assistant file is touched.

## QR setup opens, but the Add to Discord link is missing

The setup page needs `DISCORD_APPLICATION_ID` to build the invite link.

You can still add the bot manually from the Discord Developer Portal, then fill the token and channel settings in `.env`.

## What to include in an issue

Please include:

- Install path: Docker Compose or local Python.
- Home Assistant install type.
- `doctor --mode discord` output with secrets removed.
- The exact Discord message you sent.
- The bot reply.
- Whether `ALLOW_WRITE_AUTOMATIONS` is `false` or `true`.

Do not include tokens, private channel ids, or full `.env` files.
