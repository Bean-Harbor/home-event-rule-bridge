from __future__ import annotations

import html
import io
import json
import os
import secrets
import tempfile
import urllib.parse
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


DISCORD_INVITE_PERMISSIONS = 68608
DISCORD_INVITE_SCOPES = ("bot", "applications.commands")
SETUP_DEFAULT_PORT = 8788

MANAGED_ENV_KEYS = [
    "DISCORD_BOT_TOKEN",
    "DISCORD_APPLICATION_ID",
    "DISCORD_ALLOWED_CHANNEL_IDS",
    "HA_URL",
    "HA_TOKEN",
    "ALLOW_WRITE_AUTOMATIONS",
    "NSP_PROFILE",
]


class SetupError(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class SetupPortalConfig:
    host: str
    port: int
    env_file: Path
    public_url: str | None = None
    session_code: str | None = None


class DiscordSetupPortal:
    def __init__(self, config: SetupPortalConfig) -> None:
        self.config = config
        self.session_code = config.session_code or generate_session_code()
        self.public_origin = resolve_public_origin(config.host, config.port, config.public_url)

    @property
    def setup_url(self) -> str:
        return f"{self.public_origin}/setup/discord?session={urllib.parse.quote(self.session_code)}"

    @property
    def qr_page_url(self) -> str:
        return f"{self.public_origin}/setup/qr"

    @property
    def qr_svg_url(self) -> str:
        return f"{self.public_origin}/setup/qr.svg"

    def status(self) -> dict[str, Any]:
        env = read_env_file(self.config.env_file)
        application_id = env.get("DISCORD_APPLICATION_ID", "")
        return {
            "env_file": str(self.config.env_file),
            "discord_bot_token": configured_label(env.get("DISCORD_BOT_TOKEN", "")),
            "discord_application_id": configured_label(application_id),
            "discord_invite_url": "available" if application_id.strip() else "missing",
            "discord_allowed_channel_count": csv_count(env.get("DISCORD_ALLOWED_CHANNEL_IDS", "")),
            "ha_url": configured_label(env.get("HA_URL", "")),
            "ha_token": configured_label(env.get("HA_TOKEN", "")),
            "write_mode": env.get("ALLOW_WRITE_AUTOMATIONS", "false").strip().lower() == "true",
            "nsp_profile": env.get("NSP_PROFILE", ""),
        }

    def save_discord_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        received = str(payload.get("session_code", "")).strip()
        if received != self.session_code:
            raise SetupError(HTTPStatus.FORBIDDEN, "Setup session expired. Refresh the setup page and try again.")

        bot_token = str(payload.get("discord_bot_token", "")).strip()
        application_id = str(payload.get("discord_application_id", "")).strip()
        allowed_channels = str(payload.get("discord_allowed_channel_ids", "")).strip()
        ha_url = str(payload.get("ha_url", "")).strip()
        ha_token = str(payload.get("ha_token", "")).strip()

        missing = [
            label
            for label, value in [
                ("Discord Bot Token", bot_token),
                ("HA URL", ha_url),
                ("HA Token", ha_token),
            ]
            if not value
        ]
        if missing:
            raise SetupError(HTTPStatus.UNPROCESSABLE_ENTITY, f"Missing required fields: {', '.join(missing)}.")
        if application_id and not application_id.isdigit():
            raise SetupError(HTTPStatus.UNPROCESSABLE_ENTITY, "Discord Application ID should contain digits only.")

        updates = {
            "DISCORD_BOT_TOKEN": bot_token,
            "DISCORD_APPLICATION_ID": application_id,
            "DISCORD_ALLOWED_CHANNEL_IDS": allowed_channels,
            "HA_URL": ha_url,
            "HA_TOKEN": ha_token,
            "ALLOW_WRITE_AUTOMATIONS": "false",
        }
        existing = read_env_file(self.config.env_file)
        if not existing.get("NSP_PROFILE", "").strip():
            updates["NSP_PROFILE"] = "rules-only"
        merge_env_file(self.config.env_file, updates)

        invite_url = build_discord_invite_url(application_id) if application_id else ""
        return {
            "success": True,
            "message": "Discord setup saved.",
            "status": self.status(),
            "invite_url": invite_url,
        }

    def render_setup_page(self, session_code: str) -> str:
        if session_code != self.session_code:
            return portal_document(
                "Discord setup",
                '<section class="card"><h1>Setup link expired</h1><p>Open the setup URL printed by the bridge again.</p></section>',
            )
        status = self.status()
        invite = build_discord_invite_url_from_env(self.config.env_file)
        return portal_document(
            "Discord setup",
            f"""
<section class="card stack">
  <header>
    <div>
      <p class="eyebrow">Home Event Rule Bridge</p>
      <h1>Discord setup</h1>
      <p>Use your own Discord bot. Tokens are saved only to this local .env file and are never placed in the QR code.</p>
    </div>
    <span class="badge">{html.escape(status["discord_bot_token"])}</span>
  </header>
  <div class="notice">
    In the Discord Developer Portal, enable <strong>Message Content Intent</strong> for the bot before running the bridge.
  </div>
  <form id="setup-form" class="form-panel">
    <input type="hidden" id="session-code" value="{html.escape(self.session_code)}" />
    <label for="discord-bot-token">Discord Bot Token</label>
    <input id="discord-bot-token" type="password" autocomplete="off" placeholder="Paste bot token" required />
    <label for="discord-application-id">Discord Application ID</label>
    <input id="discord-application-id" type="text" autocomplete="off" inputmode="numeric" placeholder="Application / client id" />
    <label for="discord-allowed-channel-ids">Allowed Channel IDs</label>
    <input id="discord-allowed-channel-ids" type="text" autocomplete="off" placeholder="Optional comma-separated channel ids" />
    <label for="ha-url">Home Assistant URL</label>
    <input id="ha-url" type="text" autocomplete="off" placeholder="http://homeassistant.local:8123" required />
    <label for="ha-token">Home Assistant Token</label>
    <input id="ha-token" type="password" autocomplete="off" placeholder="Long-lived access token" required />
    <div class="actions">
      <button class="primary" type="submit">Save local setup</button>
      <a id="invite-link" class="secondary {'' if invite else 'disabled'}" href="{html.escape(invite)}" target="_blank" rel="noreferrer">Add to Discord</a>
    </div>
    <p id="result" class="hint"></p>
  </form>
</section>
<script>
const form = document.getElementById('setup-form');
const result = document.getElementById('result');
const inviteLink = document.getElementById('invite-link');
function field(id) {{ return document.getElementById(id).value.trim(); }}
form.addEventListener('submit', async (event) => {{
  event.preventDefault();
  result.className = 'hint';
  result.textContent = 'Saving setup...';
  try {{
    const response = await fetch('/api/setup/discord', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{
        session_code: field('session-code'),
        discord_bot_token: field('discord-bot-token'),
        discord_application_id: field('discord-application-id'),
        discord_allowed_channel_ids: field('discord-allowed-channel-ids'),
        ha_url: field('ha-url'),
        ha_token: field('ha-token')
      }})
    }});
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.message || 'Setup failed.');
    result.className = 'hint ok';
    result.textContent = 'Setup saved. Run doctor, then start the Discord bridge.';
    if (data.invite_url) {{
      inviteLink.href = data.invite_url;
      inviteLink.classList.remove('disabled');
    }}
  }} catch (error) {{
    result.className = 'hint err';
    result.textContent = error.message || 'Setup failed.';
  }}
}});
</script>
""",
        )

    def render_qr_page(self) -> str:
        return portal_document(
            "Discord setup QR",
            f"""
<section class="card narrow-card">
  <p class="eyebrow">Home Event Rule Bridge</p>
  <h1>Open setup on your phone</h1>
  <img class="qr" src="/setup/qr.svg" alt="Discord setup QR" />
  <p>The QR opens the local setup page. It does not contain Discord or Home Assistant tokens.</p>
  <p><a href="{html.escape(self.setup_url)}">Open setup link</a></p>
</section>
""",
        )

    def render_qr_svg(self) -> str:
        return qr_svg(self.setup_url)

    def make_server(self) -> ThreadingHTTPServer:
        handler = make_setup_handler(self)
        return ThreadingHTTPServer((self.config.host, self.config.port), handler)


def build_discord_invite_url(application_id: str) -> str:
    application_id = application_id.strip()
    if not application_id:
        return ""
    query = urllib.parse.urlencode(
        {
            "client_id": application_id,
            "permissions": str(DISCORD_INVITE_PERMISSIONS),
            "scope": " ".join(DISCORD_INVITE_SCOPES),
        }
    )
    return f"https://discord.com/oauth2/authorize?{query}"


def build_discord_invite_url_from_env(path: Path) -> str:
    return build_discord_invite_url(read_env_file(path).get("DISCORD_APPLICATION_ID", ""))


def generate_session_code() -> str:
    token = secrets.token_hex(4).upper()
    return f"{token[:4]}-{token[4:]}"


def resolve_public_origin(host: str, port: int, public_url: str | None = None) -> str:
    candidate = (public_url or os.environ.get("SETUP_PUBLIC_URL") or "").strip().rstrip("/")
    if candidate:
        return candidate
    visible_host = "127.0.0.1" if host in {"", "0.0.0.0", "::"} else host
    return f"http://{visible_host}:{port}"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def merge_env_file(path: Path, updates: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    original_lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen: set[str] = set()
    output: list[str] = []
    for raw_line in original_lines:
        stripped = raw_line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                output.append(f"{key}={updates[key]}")
                seen.add(key)
                continue
        output.append(raw_line)

    missing = [key for key in MANAGED_ENV_KEYS if key in updates and key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        output.append("# Discord setup portal values.")
        for key in missing:
            output.append(f"{key}={updates[key]}")

    text = "\n".join(output).rstrip() + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as handle:
        handle.write(text)
        temp_name = handle.name
    os.replace(temp_name, path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def configured_label(value: str | None) -> str:
    return "configured" if value and value.strip() else "missing"


def csv_count(value: str | None) -> int:
    if not value:
        return 0
    return len([item for item in value.split(",") if item.strip()])


def make_setup_handler(portal: DiscordSetupPortal):
    class SetupHandler(BaseHTTPRequestHandler):
        server_version = "HomeEventRuleBridgeSetup/0.1"

        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path in {"/", "/setup", "/setup/discord"}:
                query = urllib.parse.parse_qs(parsed.query)
                session = query.get("session", [""])[0]
                self._send_html(portal.render_setup_page(session))
            elif parsed.path == "/setup/qr":
                self._send_html(portal.render_qr_page())
            elif parsed.path == "/setup/qr.svg":
                self._send(HTTPStatus.OK, portal.render_qr_svg().encode("utf-8"), "image/svg+xml; charset=utf-8")
            elif parsed.path == "/api/setup/status":
                self._send_json(HTTPStatus.OK, portal.status())
            elif parsed.path == "/health":
                self._send_json(HTTPStatus.OK, {"ok": True})
            else:
                self._send_json(HTTPStatus.NOT_FOUND, {"success": False, "message": "Not found."})

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path != "/api/setup/discord":
                self._send_json(HTTPStatus.NOT_FOUND, {"success": False, "message": "Not found."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                response = portal.save_discord_config(payload)
                self._send_json(HTTPStatus.OK, response)
            except SetupError as exc:
                self._send_json(exc.status, {"success": False, "message": exc.message})
            except json.JSONDecodeError:
                self._send_json(HTTPStatus.BAD_REQUEST, {"success": False, "message": "Request body must be JSON."})

        def _send_html(self, text: str) -> None:
            self._send(HTTPStatus.OK, text.encode("utf-8"), "text/html; charset=utf-8")

        def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            self._send(status, json.dumps(payload, sort_keys=True).encode("utf-8"), "application/json; charset=utf-8")

        def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return SetupHandler


def qr_svg(text: str) -> str:
    try:
        import segno

        buffer = io.StringIO()
        segno.make_qr(text).save(buffer, kind="svg", xmldecl=False, scale=6, border=3)
        return buffer.getvalue()
    except Exception:
        escaped = html.escape(text)
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 180">'
            '<rect width="100%" height="100%" fill="#f8fafc"/>'
            '<text x="20" y="44" font-size="18" fill="#111827">QR support is not installed.</text>'
            f'<text x="20" y="82" font-size="12" fill="#374151">{escaped}</text>'
            "</svg>"
        )


def portal_document(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; --bg:#f5f7fb; --card:#fff; --text:#111827; --muted:#5f6878; --line:#d9dee8; --primary:#5865f2; --ok:#0f766e; --err:#b42318; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--text); }}
    main {{ width:min(880px, calc(100% - 28px)); margin:28px auto; }}
    .card {{ background:var(--card); border:1px solid var(--line); border-radius:8px; box-shadow:0 1px 2px rgba(15,23,42,.06); overflow:hidden; }}
    .narrow-card {{ max-width:520px; margin:0 auto; padding:24px; text-align:center; }}
    header {{ display:flex; justify-content:space-between; align-items:flex-start; gap:18px; padding:22px; border-bottom:1px solid var(--line); }}
    h1 {{ margin:4px 0 8px; font-size:28px; line-height:1.12; }}
    p {{ margin:0 0 10px; color:var(--muted); line-height:1.55; }}
    .eyebrow {{ margin:0; color:var(--primary); font-size:13px; font-weight:750; text-transform:uppercase; }}
    .notice {{ padding:14px 22px; border-bottom:1px solid var(--line); color:var(--muted); background:#f8fafc; }}
    .form-panel {{ padding:20px 22px 24px; }}
    label {{ display:block; margin:14px 0 7px; font-weight:700; }}
    input {{ width:100%; min-height:44px; border:1px solid var(--line); border-radius:8px; padding:10px 12px; font-size:15px; }}
    .actions {{ display:flex; flex-wrap:wrap; gap:12px; margin-top:18px; align-items:center; }}
    button, .secondary {{ min-height:42px; border-radius:8px; padding:11px 16px; font-weight:750; text-decoration:none; cursor:pointer; }}
    .primary {{ border:0; background:var(--primary); color:white; }}
    .secondary {{ border:1px solid var(--primary); color:var(--primary); background:white; display:inline-flex; align-items:center; }}
    .secondary.disabled {{ pointer-events:none; opacity:.45; border-color:var(--line); color:var(--muted); }}
    .badge {{ display:inline-flex; align-items:center; min-height:30px; padding:5px 11px; border-radius:999px; background:#eef2ff; color:#3730a3; font-weight:750; }}
    .hint {{ margin-top:12px; font-size:14px; }}
    .ok {{ color:var(--ok); }}
    .err {{ color:var(--err); }}
    .qr {{ width:min(320px, 100%); aspect-ratio:1; border:1px solid var(--line); border-radius:8px; background:white; margin:18px auto; display:block; }}
    @media (max-width:640px) {{ header {{ flex-direction:column; }} h1 {{ font-size:24px; }} }}
  </style>
</head>
<body>
  <main>{body}</main>
</body>
</html>"""
