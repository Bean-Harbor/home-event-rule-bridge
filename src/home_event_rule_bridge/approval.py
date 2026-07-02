from __future__ import annotations

import time
from dataclasses import dataclass

from .models import RuleDraft


@dataclass
class PendingDraft:
    chat_id: str
    draft: RuleDraft
    yaml_preview: str
    created_at: float
    expires_at: float


class ApprovalStore:
    def __init__(self, ttl_seconds: int = 1800) -> None:
        self.ttl_seconds = ttl_seconds
        self._drafts: dict[str, PendingDraft] = {}

    def put(self, chat_id: str, draft: RuleDraft, yaml_preview: str) -> PendingDraft:
        now = time.time()
        pending = PendingDraft(
            chat_id=chat_id,
            draft=draft,
            yaml_preview=yaml_preview,
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

    def cancel(self, draft_id: str, chat_id: str) -> bool:
        return self.pop(draft_id, chat_id) is not None

