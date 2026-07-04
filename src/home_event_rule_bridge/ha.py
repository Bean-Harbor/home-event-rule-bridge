from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import EntityRef


def normalize_entity_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _query_tokens(text: str) -> set[str]:
    tokens = set(normalize_entity_text(text).split())
    aliases: dict[str, str] = {
        "switches": "switch",
        "lights": "light",
        "cameras": "camera",
        "sensors": "sensor",
        "scenes": "scene",
        "scripts": "script",
        "devices": "device",
    }
    return {aliases.get(token, token) for token in tokens}


@dataclass(frozen=True)
class HomeAssistantState:
    entity_id: str
    state: str
    friendly_name: str | None

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]

    @property
    def search_text(self) -> str:
        return normalize_entity_text(f"{self.entity_id} {self.friendly_name or ''}")


class EntitySnapshot:
    def __init__(self, states: list[HomeAssistantState]) -> None:
        self.states = states
        self.by_id = {state.entity_id: state for state in states}

    @classmethod
    def from_api_states(cls, payload: list[dict[str, Any]]) -> "EntitySnapshot":
        states = []
        for item in payload:
            entity_id = item.get("entity_id")
            if not entity_id:
                continue
            attrs = item.get("attributes") or {}
            states.append(
                HomeAssistantState(
                    entity_id=entity_id,
                    state=str(item.get("state", "")),
                    friendly_name=attrs.get("friendly_name"),
                )
            )
        return cls(states)

    @classmethod
    def from_file(cls, path: Path) -> "EntitySnapshot":
        return cls.from_api_states(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def empty(cls) -> "EntitySnapshot":
        return cls([])

    def exists(self, entity_id: str | None) -> bool:
        if not entity_id:
            return False
        return entity_id in self.by_id

    def find_one(self, text: str, domains: set[str] | None = None, hints: list[str] | None = None) -> HomeAssistantState | None:
        matches = self.find(text, domains=domains, hints=hints)
        return matches[0] if matches else None

    def find(self, text: str, domains: set[str] | None = None, hints: list[str] | None = None) -> list[HomeAssistantState]:
        haystack = normalize_entity_text(text)
        tokens = _query_tokens(text)
        hints = [normalize_entity_text(hint) for hint in (hints or [])]
        scored: list[tuple[int, HomeAssistantState]] = []
        for state in self.states:
            if domains and state.domain not in domains:
                continue
            score = 0
            search_text = state.search_text
            search_tokens = set(search_text.split())
            entity_text = normalize_entity_text(state.entity_id)
            friendly_text = normalize_entity_text(state.friendly_name or "")
            if entity_text and entity_text in haystack:
                score += 12
            if friendly_text and friendly_text in haystack:
                score += 10
            if state.domain in tokens:
                score += 6
            for token in tokens:
                if len(token) >= 3 and token in search_tokens:
                    score += 2
            for hint in hints:
                if hint and hint in haystack and hint in search_text:
                    score += 4
            if score:
                scored.append((score, state))
        scored.sort(key=lambda item: (-item[0], item[1].entity_id))
        return [state for _, state in scored]

    def refs_for(self, entity_ids: list[str | None]) -> list[EntityRef]:
        refs = []
        for entity_id in entity_ids:
            if not entity_id:
                continue
            state = self.by_id.get(entity_id)
            refs.append(
                EntityRef(
                    entity_id=entity_id,
                    name=state.friendly_name if state else None,
                    domain=entity_id.split(".", 1)[0],
                )
            )
        return refs


class HomeAssistantClient:
    def __init__(self, base_url: str, token: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Home Assistant API returned HTTP {exc.code}: {exc.read().decode('utf-8')}") from exc
        return json.loads(data) if data else None

    def states(self) -> EntitySnapshot:
        return EntitySnapshot.from_api_states(self._request("GET", "/api/states"))

    def call_service(self, domain: str, service: str, payload: dict[str, Any] | None = None) -> Any:
        return self._request("POST", f"/api/services/{domain}/{service}", payload or {})
