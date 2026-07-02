from __future__ import annotations

import time
from dataclasses import dataclass

from .models import ManagedRule, RuleDraft, ValidationResult


@dataclass
class PendingDraft:
    chat_id: str
    draft: RuleDraft
    yaml_preview: str
    validation: ValidationResult
    suggestions: list[str]
    created_at: float
    expires_at: float
    status: str = "draft"


class ApprovalStore:
    def __init__(self, ttl_seconds: int = 1800) -> None:
        self.ttl_seconds = ttl_seconds
        self._drafts: dict[str, PendingDraft] = {}
        self._rules: dict[str, ManagedRule] = {}

    def put(
        self,
        chat_id: str,
        draft: RuleDraft,
        yaml_preview: str,
        validation: ValidationResult,
        suggestions: list[str] | None = None,
    ) -> PendingDraft:
        now = time.time()
        pending = PendingDraft(
            chat_id=chat_id,
            draft=draft,
            yaml_preview=yaml_preview,
            validation=validation,
            suggestions=suggestions or [],
            created_at=now,
            expires_at=now + self.ttl_seconds,
        )
        self._drafts[draft.id] = pending
        return pending

    def get(self, draft_id: str, chat_id: str) -> PendingDraft | None:
        pending = self._drafts.get(draft_id)
        if not pending or pending.chat_id != chat_id:
            return None
        if pending.expires_at < time.time():
            self._drafts.pop(draft_id, None)
            return None
        return pending

    def pop(self, draft_id: str, chat_id: str) -> PendingDraft | None:
        pending = self.get(draft_id, chat_id)
        if pending:
            self._drafts.pop(draft_id, None)
        return pending

    def active_drafts_for_chat(self, chat_id: str) -> list[PendingDraft]:
        active = []
        now = time.time()
        for draft_id, pending in list(self._drafts.items()):
            if pending.expires_at < now:
                pending.status = "expired"
                self._drafts.pop(draft_id, None)
                continue
            if pending.chat_id == chat_id:
                active.append(pending)
        active.sort(key=lambda draft: draft.created_at, reverse=True)
        return active

    def latest_for_chat(self, chat_id: str) -> PendingDraft | None:
        active = self.active_drafts_for_chat(chat_id)
        return active[0] if active else None

    def pop_latest_for_chat(self, chat_id: str) -> PendingDraft | None:
        pending = self.latest_for_chat(chat_id)
        if pending:
            self._drafts.pop(pending.draft.id, None)
        return pending

    def cancel(self, draft_id: str, chat_id: str) -> bool:
        pending = self.get(draft_id, chat_id)
        if not pending:
            return False
        pending.status = "canceled"
        self._drafts.pop(draft_id, None)
        return True

    def remember_rule(self, chat_id: str, draft: RuleDraft, yaml_preview: str, result: str) -> ManagedRule:
        rule_id = "rule_" + draft.id.removeprefix("draft_")
        now = time.time()
        rule = ManagedRule(
            rule_id=rule_id,
            draft_id=draft.id,
            chat_id=chat_id,
            user_text=draft.user_text,
            explanation=draft.explanation,
            yaml_preview=yaml_preview,
            created_at=now,
            updated_at=now,
            last_result=result,
        )
        self._rules[rule.rule_id] = rule
        return rule

    def list_rules(self, chat_id: str) -> list[ManagedRule]:
        rules = [rule for rule in self._rules.values() if rule.chat_id == chat_id and rule.status != "deleted"]
        rules.sort(key=lambda rule: rule.created_at, reverse=True)
        return rules

    def get_rule(self, chat_id: str, rule_id: str) -> ManagedRule | None:
        rule = self._rules.get(rule_id)
        if not rule or rule.chat_id != chat_id or rule.status == "deleted":
            return None
        return rule

    def update_rule_status(self, chat_id: str, rule_id: str, status: str) -> ManagedRule | None:
        rule = self.get_rule(chat_id, rule_id)
        if not rule:
            return None
        updated = ManagedRule(
            rule_id=rule.rule_id,
            draft_id=rule.draft_id,
            chat_id=rule.chat_id,
            user_text=rule.user_text,
            explanation=rule.explanation,
            yaml_preview=rule.yaml_preview,
            status=status,
            created_at=rule.created_at,
            updated_at=time.time(),
            last_result=rule.last_result,
        )
        self._rules[rule_id] = updated
        return updated
