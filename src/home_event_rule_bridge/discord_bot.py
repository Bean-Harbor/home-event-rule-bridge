from __future__ import annotations

import asyncio
from collections.abc import Callable


def _clean_content(content: str, bot_user_id: int | None) -> str:
    text = content.strip()
    if bot_user_id is not None:
        for mention in (f"<@{bot_user_id}>", f"<@!{bot_user_id}>"):
            text = text.replace(mention, "")
    return text.strip()


def _message_chunks(text: str, limit: int = 1900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while rest:
        if len(rest) <= limit:
            chunks.append(rest)
            break
        split_at = rest.rfind("\n", 0, limit)
        if split_at < 200:
            split_at = limit
        chunks.append(rest[:split_at].rstrip())
        rest = rest[split_at:].lstrip()
    return chunks


class DiscordBot:
    def __init__(self, token: str, allowed_channel_ids: set[str] | None = None) -> None:
        self.token = token
        self.allowed_channel_ids = allowed_channel_ids or set()

    def run(self, handler: Callable[[str, str], str]) -> None:
        try:
            import discord
        except ImportError as exc:
            raise RuntimeError("Install Discord support with: pip install -e .[discord]") from exc

        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)

        @client.event
        async def on_ready() -> None:
            print(f"Discord bridge logged in as {client.user}")

        @client.event
        async def on_message(message) -> None:
            if message.author.bot:
                return
            channel_id = str(message.channel.id)
            in_dm = message.guild is None
            mentioned = client.user is not None and client.user in message.mentions

            if self.allowed_channel_ids:
                if channel_id not in self.allowed_channel_ids:
                    return
            elif not in_dm and not mentioned:
                return

            text = _clean_content(message.content, client.user.id if client.user else None)
            if not text:
                return

            approval_scope = f"discord:{channel_id}:{message.author.id}"
            async with message.channel.typing():
                reply = await asyncio.to_thread(handler, approval_scope, text)
            for chunk in _message_chunks(reply):
                await message.channel.send(chunk)

        client.run(self.token)

