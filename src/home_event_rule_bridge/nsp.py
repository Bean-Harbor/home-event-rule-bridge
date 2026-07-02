from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod

from .config import Settings
from .ha import EntitySnapshot
from .models import ActionSpec, ConditionSpec, RuleDraft, TriggerSpec, new_draft_id


class Parser(ABC):
    @abstractmethod
    def parse(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        raise NotImplementedError


class RuleBasedParser(Parser):
    def parse(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        lower = text.lower()
        if "package" in lower or "parcel" in lower:
            return self._package_rule(text, snapshot)
        if "pet" in lower or "dog" in lower or "cat" in lower:
            return self._pet_rule(text, snapshot)
        if "driveway" in lower or "garage" in lower:
            return self._driveway_rule(text, snapshot)
        if "arriv" in lower or "gets home" in lower or "come home" in lower:
            return self._arrival_rule(text, snapshot)
        if "offline" in lower or "unavailable" in lower:
            return self._offline_rule(text, snapshot)
        return self._clarify(text, "I need a trigger, condition, and action before creating a Home Assistant rule.")

    def _package_rule(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        entity = snapshot.find_one(text, {"binary_sensor", "sensor"}, ["package", "porch"])
        to_state = "off" if "no longer" in text.lower() or "missing" in text.lower() else "on"
        missing = [] if entity else ["package-visible sensor"]
        return self._draft(
            text,
            confidence=0.82 if entity else 0.52,
            trigger=TriggerSpec("state", entity.entity_id if entity else None, to_state, label="package visibility changed"),
            conditions=[],
            actions=[self._notify("Package visibility changed", "Package state changed near the porch.")],
            entities=snapshot.refs_for([entity.entity_id if entity else None]),
            missing_slots=missing,
            explanation="Notify when package visibility changes.",
        )

    def _pet_rule(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        entity = snapshot.find_one(text, {"camera", "binary_sensor", "sensor"}, ["pet", "dog", "cat", "living"])
        missing = [] if entity else ["pet camera or pet activity sensor"]
        return self._draft(
            text,
            confidence=0.74 if entity else 0.48,
            trigger=TriggerSpec("state", entity.entity_id if entity else None, None, label="pet activity event"),
            conditions=[],
            actions=[self._notify("Pet activity", "Pet activity may be worth checking.")],
            entities=snapshot.refs_for([entity.entity_id if entity else None]),
            missing_slots=missing,
            explanation="Notify when pet activity looks unusual.",
        )

    def _driveway_rule(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        trigger = snapshot.find_one(text, {"binary_sensor"}, ["driveway", "garage", "motion"])
        family = snapshot.find_one(text, {"group", "person"}, ["family", "home", "occupancy"])
        if family is None and ("nobody" in text.lower() or "no one" in text.lower() or "away" in text.lower()):
            family = snapshot.by_id.get("group.family")
            if family is None:
                family = next((state for state in snapshot.states if state.domain == "group"), None)
        missing = []
        if not trigger:
            missing.append("driveway or garage motion sensor")
        conditions = []
        if "nobody" in text.lower() or "no one" in text.lower() or "away" in text.lower():
            if family:
                conditions.append(ConditionSpec("state", family.entity_id, "not_home", "nobody home"))
            else:
                missing.append("home occupancy entity")
        entity_ids = [trigger.entity_id if trigger else None, family.entity_id if family else None]
        return self._draft(
            text,
            confidence=0.86 if trigger and not missing else 0.58,
            trigger=TriggerSpec("state", trigger.entity_id if trigger else None, "on", label="driveway motion"),
            conditions=conditions,
            actions=[self._notify("Driveway motion", "Driveway motion matched your rule.")],
            entities=snapshot.refs_for(entity_ids),
            missing_slots=missing,
            explanation="Notify on driveway or garage motion with optional occupancy context.",
        )

    def _arrival_rule(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        person = snapshot.find_one(text, {"person", "device_tracker"}, ["kid", "family", "alex"])
        missing = [] if person else ["person or device tracker entity"]
        return self._draft(
            text,
            confidence=0.78 if person else 0.45,
            trigger=TriggerSpec("state", person.entity_id if person else None, "home", label="family arrival"),
            conditions=[],
            actions=[self._notify("Arrived home", "A family member arrived home.")],
            entities=snapshot.refs_for([person.entity_id if person else None]),
            missing_slots=missing,
            explanation="Notify when a selected person arrives home.",
        )

    def _offline_rule(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        entity = snapshot.find_one(text, {"camera", "sensor", "binary_sensor", "switch", "light"}, ["camera", "device"])
        missing = [] if entity else ["device entity to monitor"]
        return self._draft(
            text,
            confidence=0.72 if entity else 0.44,
            trigger=TriggerSpec("state", entity.entity_id if entity else None, "unavailable", label="device offline"),
            conditions=[],
            actions=[self._notify("Device offline", "A selected device became unavailable.")],
            entities=snapshot.refs_for([entity.entity_id if entity else None]),
            missing_slots=missing,
            explanation="Notify when a selected device becomes unavailable.",
        )

    def _clarify(self, text: str, explanation: str) -> RuleDraft:
        return self._draft(
            text,
            confidence=0.2,
            trigger=TriggerSpec("manual", label="needs clarification"),
            conditions=[],
            actions=[self._notify("Rule needs clarification", explanation)],
            entities=[],
            missing_slots=["trigger", "action"],
            explanation=explanation,
        )

    def _notify(self, title: str, message: str) -> ActionSpec:
        return ActionSpec("persistent_notification.create", data={"title": title, "message": message})

    def _draft(
        self,
        text: str,
        confidence: float,
        trigger: TriggerSpec,
        conditions: list[ConditionSpec],
        actions: list[ActionSpec],
        entities,
        missing_slots: list[str],
        explanation: str,
    ) -> RuleDraft:
        return RuleDraft(
            id=new_draft_id(),
            user_text=text,
            intent="create_rule",
            confidence=confidence,
            trigger=trigger,
            conditions=conditions,
            actions=actions,
            entities=list(entities),
            missing_slots=missing_slots,
            risk_level="low",
            requires_confirmation=True,
            explanation=explanation,
        )


class OpenAICompatibleParser(Parser):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def parse(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        entities = [
            {"entity_id": state.entity_id, "friendly_name": state.friendly_name, "state": state.state}
            for state in snapshot.states[:120]
        ]
        prompt = (
            "You are a local Home Assistant semantic parser. Return only JSON for a RuleDraft. "
            "Use only entity_id values from the provided list. If unsure, add missing_slots. "
            "Allowed action services: persistent_notification.create, notify.notify, light.turn_on, "
            "light.turn_off, switch.turn_on, switch.turn_off, scene.turn_on, script.turn_on.\n\n"
            f"User text: {text}\nEntities: {json.dumps(entities, ensure_ascii=False)}"
        )
        payload = {
            "model": self.settings.openai_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        req = urllib.request.Request(
            self.settings.openai_base_url.rstrip("/") + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`")
            content = content.removeprefix("json").strip()
        return RuleDraft.from_dict(json.loads(content), user_text=text)


def build_parser(settings: Settings) -> Parser:
    if settings.nsp_provider in {"openai", "openai-compatible", "llm"}:
        return OpenAICompatibleParser(settings)
    return RuleBasedParser()
