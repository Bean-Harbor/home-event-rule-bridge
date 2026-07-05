from __future__ import annotations

import json
import urllib.request
from abc import ABC, abstractmethod

from .config import Settings
from .ha import EntitySnapshot, HomeAssistantState, normalize_entity_text
from .models import ActionSpec, ConditionSpec, RuleDraft, TriggerSpec, new_draft_id


class Parser(ABC):
    @property
    def display_name(self) -> str:
        return self.__class__.__name__

    @abstractmethod
    def parse(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        raise NotImplementedError


class RuleBasedParser(Parser):
    @property
    def display_name(self) -> str:
        return "rules-only"

    def parse(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        lower = text.lower()
        if "package" in lower or "parcel" in lower:
            return self._package_rule(text, snapshot)
        if "pet" in lower or "dog" in lower or "cat" in lower:
            return self._pet_rule(text, snapshot)
        if "driveway" in lower or "garage" in lower:
            return self._driveway_rule(text, snapshot)
        if self._has_occupancy_trigger(lower):
            return self._occupancy_rule(text, snapshot)
        if "run" in lower and ("scene" in lower or "script" in lower):
            return self._manual_scene_rule(text, snapshot)
        if "arriv" in lower or "gets home" in lower or "come home" in lower:
            return self._arrival_rule(text, snapshot)
        if "offline" in lower or "unavailable" in lower:
            return self._offline_rule(text, snapshot)
        return self._clarify(text, "I need a clearer trigger and action before creating a Home Assistant rule.")

    def _package_rule(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        entity = self._find_specific(text, snapshot, {"binary_sensor", "sensor"}, ["package", "porch"])
        actions, action_missing, action_entities = self._actions_from_text(
            text,
            snapshot,
            default_title="Package visibility changed",
            default_message="Package state changed near the porch.",
        )
        to_state = "off" if "no longer" in text.lower() or "missing" in text.lower() else "on"
        missing = [] if entity else ["package-visible sensor"]
        missing.extend(action_missing)
        return self._draft(
            text,
            confidence=self._confidence(missing, 0.84),
            trigger=TriggerSpec("state", entity.entity_id if entity else None, to_state, label="package visibility changed"),
            conditions=[],
            actions=actions,
            entities=snapshot.refs_for([entity.entity_id if entity else None, *action_entities]),
            missing_slots=missing,
            explanation="Notify when package visibility changes.",
        )

    def _pet_rule(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        entity = self._find_specific(text, snapshot, {"camera", "binary_sensor", "sensor"}, ["pet", "dog", "cat", "living"])
        actions, action_missing, action_entities = self._actions_from_text(
            text,
            snapshot,
            default_title="Pet activity",
            default_message="Pet activity may be worth checking.",
        )
        missing = [] if entity else ["pet camera or pet activity sensor"]
        missing.extend(action_missing)
        return self._draft(
            text,
            confidence=self._confidence(missing, 0.74),
            trigger=TriggerSpec("state", entity.entity_id if entity else None, None, label="pet activity event"),
            conditions=[],
            actions=actions,
            entities=snapshot.refs_for([entity.entity_id if entity else None, *action_entities]),
            missing_slots=missing,
            explanation="Notify when pet activity looks unusual.",
        )

    def _driveway_rule(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        lower = text.lower()
        place = "garage" if "garage" in lower else "driveway"
        trigger = self._find_specific(text, snapshot, {"binary_sensor"}, [place, "motion"])
        family = snapshot.find_one(text, {"group", "person"}, ["family", "home", "occupancy"])
        if family is None and ("nobody" in text.lower() or "no one" in text.lower() or "away" in text.lower()):
            family = snapshot.by_id.get("group.family")
            if family is None:
                family = next((state for state in snapshot.states if state.domain == "group"), None)
        actions, action_missing, action_entities = self._actions_from_text(
            text,
            snapshot,
            default_title=f"{place.title()} motion",
            default_message=f"{place.title()} motion matched your rule.",
        )
        missing = []
        if not trigger:
            missing.append(f"{place} motion sensor")
        conditions = []
        if "nobody" in text.lower() or "no one" in text.lower() or "away" in text.lower():
            if family:
                conditions.append(ConditionSpec("state", family.entity_id, "not_home", "nobody home"))
            else:
                missing.append("home occupancy entity")
        missing.extend(action_missing)
        entity_ids = [trigger.entity_id if trigger else None, family.entity_id if family else None, *action_entities]
        return self._draft(
            text,
            confidence=self._confidence(missing, 0.86),
            trigger=TriggerSpec("state", trigger.entity_id if trigger else None, "on", label=f"{place} motion"),
            conditions=conditions,
            actions=actions,
            entities=snapshot.refs_for(entity_ids),
            missing_slots=missing,
            explanation=f"Notify on {place} motion with optional occupancy context.",
        )

    def _arrival_rule(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        person = self._find_person_or_single(text, snapshot)
        actions, action_missing, action_entities = self._actions_from_text(
            text,
            snapshot,
            default_title="Arrived home",
            default_message="A family member arrived home.",
        )
        missing = [] if person else ["person or device tracker entity"]
        missing.extend(action_missing)
        return self._draft(
            text,
            confidence=self._confidence(missing, 0.78),
            trigger=TriggerSpec("state", person.entity_id if person else None, "home", label="family arrival"),
            conditions=[],
            actions=actions,
            entities=snapshot.refs_for([person.entity_id if person else None, *action_entities]),
            missing_slots=missing,
            explanation=self._explain_action(actions, "when a selected person arrives home"),
        )

    def _offline_rule(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        entity = self._find_specific(
            text,
            snapshot,
            {"camera", "sensor", "binary_sensor", "switch", "light"},
            ["camera", "device", "switch", "light"],
        )
        actions, action_missing, action_entities = self._actions_from_text(
            text,
            snapshot,
            default_title="Device offline",
            default_message="A selected device became unavailable.",
        )
        missing = [] if entity else ["device entity to monitor"]
        missing.extend(action_missing)
        return self._draft(
            text,
            confidence=self._confidence(missing, 0.76),
            trigger=TriggerSpec("state", entity.entity_id if entity else None, "unavailable", label="device offline"),
            conditions=[],
            actions=actions,
            entities=snapshot.refs_for([entity.entity_id if entity else None, *action_entities]),
            missing_slots=missing,
            explanation="Notify when a selected device becomes unavailable.",
        )

    def _occupancy_rule(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        family = snapshot.by_id.get("group.family") or next((state for state in snapshot.states if state.domain == "group"), None)
        actions, action_missing, action_entities = self._actions_from_text(
            text,
            snapshot,
            default_title="Nobody home",
            default_message="Nobody is home.",
        )
        missing = [] if family else ["home occupancy entity"]
        missing.extend(action_missing)
        return self._draft(
            text,
            confidence=self._confidence(missing, 0.82),
            trigger=TriggerSpec("state", family.entity_id if family else None, "not_home", label="nobody home"),
            conditions=[],
            actions=actions,
            entities=snapshot.refs_for([family.entity_id if family else None, *action_entities]),
            missing_slots=missing,
            explanation=self._explain_action(actions, "when nobody is home"),
        )

    def _manual_scene_rule(self, text: str, snapshot: EntitySnapshot) -> RuleDraft:
        actions, action_missing, action_entities = self._actions_from_text(
            text,
            snapshot,
            default_title="Manual scene request",
            default_message="Manual phrase matched this rule.",
        )
        missing = list(action_missing)
        return self._draft(
            text,
            confidence=self._confidence(missing, 0.76),
            trigger=TriggerSpec("manual", label="manual phrase: movie time" if "movie time" in text.lower() else "manual phrase"),
            conditions=[],
            actions=actions,
            entities=snapshot.refs_for(action_entities),
            missing_slots=missing,
            explanation=self._explain_action(actions, "when the phrase is used"),
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

    def _actions_from_text(
        self,
        text: str,
        snapshot: EntitySnapshot,
        default_title: str,
        default_message: str,
    ) -> tuple[list[ActionSpec], list[str], list[str | None]]:
        lower = text.lower()
        if "turn on" in lower or "turn off" in lower:
            service_name = "turn_on" if "turn on" in lower else "turn_off"
            target = self._find_specific(text, snapshot, {"light", "switch"}, ["light", "switch"])
            if not target:
                return [ActionSpec(f"light.{service_name}", label=f"{service_name.replace('_', ' ')} selected device")], [
                    "action target"
                ], []
            return [
                ActionSpec(
                    f"{target.domain}.{service_name}",
                    target={"entity_id": target.entity_id},
                    label=f"{service_name.replace('_', ' ')} {target.friendly_name or target.entity_id}",
                )
            ], [], [target.entity_id]

        if "run" in lower and ("scene" in lower or "script" in lower):
            domains = {"scene"} if "scene" in lower and "script" not in lower else {"scene", "script"}
            target = self._find_specific(text, snapshot, domains, ["scene", "script", "evening", "movie"])
            if not target:
                return [ActionSpec("scene.turn_on", label="run selected scene or script")], ["scene or script"], []
            service = "scene.turn_on" if target.domain == "scene" else "script.turn_on"
            return [ActionSpec(service, target={"entity_id": target.entity_id}, label=f"run {target.friendly_name or target.entity_id}")], [], [
                target.entity_id
            ]

        return [self._notify(default_title, default_message)], [], []

    def _find_person_or_single(self, text: str, snapshot: EntitySnapshot) -> HomeAssistantState | None:
        person = self._find_specific(text, snapshot, {"person", "device_tracker"}, ["kid", "family", "alex", "member"])
        if person:
            return person
        people = [state for state in snapshot.states if state.domain in {"person", "device_tracker"}]
        return people[0] if len(people) == 1 else None

    def _find_specific(
        self,
        text: str,
        snapshot: EntitySnapshot,
        domains: set[str],
        hints: list[str],
    ) -> HomeAssistantState | None:
        matches = snapshot.find(text, domains=domains, hints=hints)
        if not matches:
            return None
        query_tokens = set(normalize_entity_text(text).split())
        generic = {
            "a",
            "an",
            "the",
            "if",
            "when",
            "me",
            "my",
            "notify",
            "message",
            "tell",
            "let",
            "know",
            "turn",
            "on",
            "off",
            "go",
            "goes",
            "going",
            "offline",
            "unavailable",
            "happen",
            "happens",
            "happened",
            "became",
            "becomes",
            "please",
            "should",
            "run",
            "device",
            "devices",
            "sensor",
            "binary",
            "motion",
            "camera",
            "light",
            "switch",
            "scene",
            "script",
            "home",
            "nobody",
            "everyone",
            "away",
            "someone",
            "family",
            "member",
            "arrives",
            "arrive",
            "arrived",
            "when",
            "while",
            "say",
            "time",
            *domains,
        }
        specific_query_tokens = query_tokens - generic
        if len(matches) == 1:
            if not specific_query_tokens:
                return matches[0]
            state_tokens = set(matches[0].search_text.split()) - generic
            return matches[0] if state_tokens & specific_query_tokens else None
        for state in matches:
            specific_tokens = set(state.search_text.split()) - generic
            if specific_tokens & specific_query_tokens:
                return state
        return None

    def _has_occupancy_trigger(self, lower: str) -> bool:
        return ("nobody is home" in lower or "nobody home" in lower or "no one is home" in lower) and (
            "turn on" in lower or "turn off" in lower
        )

    def _confidence(self, missing_slots: list[str], ready_score: float) -> float:
        if not missing_slots:
            return ready_score
        if len(missing_slots) == 1:
            return min(0.58, ready_score - 0.24)
        return 0.42

    def _explain_action(self, actions: list[ActionSpec], suffix: str) -> str:
        if not actions:
            return f"Take an action {suffix}."
        action = actions[0]
        if action.service == "persistent_notification.create":
            return f"Notify you {suffix}."
        if action.label:
            return f"{action.label.capitalize()} {suffix}."
        return f"Run {action.service} {suffix}."

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

    @property
    def display_name(self) -> str:
        if self.settings.nsp_profile == "remote-dev":
            return f"remote-dev model ({self.settings.openai_model})"
        return f"{self.settings.nsp_profile} local model ({self.settings.openai_model})"

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
    if settings.uses_model:
        return OpenAICompatibleParser(settings)
    return RuleBasedParser()
