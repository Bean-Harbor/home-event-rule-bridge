from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from collections.abc import Callable


class TelegramBot:
    def __init__(self, token: str, allowed_chat_ids: set[str] | None = None, timeout: int = 30) -> None:
        self.token = token
        self.allowed_chat_ids = allowed_chat_ids or set()
        self.timeout = timeout
        self.base_url = f"https://api.telegram.org/bot{token}"

    def _api(self, method: str, payload: dict | None = None) -> dict:
        data = None if payload is None else urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.base_url}/{method}", data=data, method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=self.timeout + 10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_message(self, chat_id: str, text: str) -> None:
        self._api("sendMessage", {"chat_id": chat_id, "text": text[:3900], "parse_mode": "Markdown"})

    def poll(self, handler: Callable[[str, str], str]) -> None:
        offset = 0
        while True:
            result = self._api("getUpdates", {"timeout": self.timeout, "offset": offset})
            for update in result.get("result", []):
                offset = max(offset, int(update["update_id"]) + 1)
                message = update.get("message") or {}
                text = message.get("text")
                chat = message.get("chat") or {}
                chat_id = str(chat.get("id"))
                if not text or not chat_id:
                    continue
                if self.allowed_chat_ids and chat_id not in self.allowed_chat_ids:
                    continue
                try:
                    reply = handler(chat_id, text)
                except Exception as exc:  # keep the polling loop alive
                    reply = f"Bridge error: {exc}"
                self.send_message(chat_id, reply)
            time.sleep(0.2)

