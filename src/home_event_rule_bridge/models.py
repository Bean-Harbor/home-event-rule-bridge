from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


def new_draft_id() -> str:
    return "draft_" + uuid.uuid4().hex[:10]


@dataclass(frozen=True)
class EntityRef:
    entity_id: str
    name: str | None = None
    domain: str | None = None


@dataclass(frozen=True)
class TriggerSpec:
    kind: str
    entity_id: str | None = None
    to_state: str | None = None
    event_type: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class ConditionSpec:
    kind: str
    entity_id: str | None = None
    state: str | None = None
    label: str | None = None


@dataclass(frozen=True)
class ActionSpec:
    service: str
    target: dict[str, Any] | None = None
    data: dict[str, Any] = field(default_factory=dict)
    label: str | None = None


@dataclass(frozen=True)
class RuleDraft:
    id: str
    user_text: str
    intent: str
    confidence: float
    trigger: TriggerSpec
    conditions: list[ConditionSpec]
    actions: list[ActionSpec]
    entities: list[EntityRef]
    missing_slots: list[str]
    risk_level: str
    requires_confirmation: bool
    explanation: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: dict[str, Any], user_text: str) -> "RuleDraft":
        trigger = TriggerSpec(**payload.get("trigger", {}))
        conditions = [ConditionSpec(**item) for item in payload.get("conditions", [])]
        actions = [ActionSpec(**item) for item in payload.get("actions", [])]
        entities = [EntityRef(**item) for item in payload.get("entities", [])]
        return cls(
            id=payload.get("id") or new_draft_id(),
            user_text=payload.get("user_text") or user_text,
            intent=payload.get("intent", "create_rule"),
            confidence=float(payload.get("confidence", 0.0)),
            trigger=trigger,
            conditions=conditions,
            actions=actions,
            entities=entities,
            missing_slots=list(payload.get("missing_slots", [])),
            risk_level=payload.get("risk_level", "low"),
            requires_confirmation=bool(payload.get("requires_confirmation", True)),
            explanation=payload.get("explanation", ""),
        )


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def success(cls, warnings: list[str] | None = None) -> "ValidationResult":
        return cls(ok=True, warnings=warnings or [])

    @classmethod
    def failure(cls, errors: list[str], warnings: list[str] | None = None) -> "ValidationResult":
        return cls(ok=False, errors=errors, warnings=warnings or [])


@dataclass(frozen=True)
class ManagedRule:
    rule_id: str
    draft_id: str
    chat_id: str
    user_text: str
    explanation: str
    yaml_preview: str
    status: str = "active"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    last_result: str = ""
