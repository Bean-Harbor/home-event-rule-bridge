from __future__ import annotations

from dataclasses import dataclass

from .approval import ApprovalStore
from .compiler import compile_automation_yaml, validate_draft
from .ha import EntitySnapshot
from .nsp import Parser
from .writer import AutomationWriter


@dataclass(frozen=True)
class BridgeReply:
    text: str
    draft_id: str | None = None
    yaml_preview: str | None = None


class RuleBridge:
    SIMPLE_CONFIRMATIONS = {"CONFIRM", "CONFIRMED", "YES", "Y", "OK", "APPROVE", "APPROVED"}

    def __init__(
        self,
        parser: Parser,
        approvals: ApprovalStore,
        writer: AutomationWriter,
    ) -> None:
        self.parser = parser
        self.approvals = approvals
        self.writer = writer

    def handle_text(self, chat_id: str, text: str, snapshot: EntitySnapshot) -> BridgeReply:
        stripped = text.strip()
        upper = stripped.upper()
        if upper.startswith("CONFIRM "):
            return self._confirm(chat_id, stripped.split(maxsplit=1)[1].strip())
        if upper in self.SIMPLE_CONFIRMATIONS:
            return self._confirm_latest(chat_id)
        if upper.startswith("CANCEL "):
            draft_id = stripped.split(maxsplit=1)[1].strip()
            if self.approvals.cancel(draft_id, chat_id):
                return BridgeReply(f"Canceled {draft_id}.")
            return BridgeReply(f"I could not find an active draft named {draft_id}.")

        draft = self.parser.parse(stripped, snapshot)
        validation = validate_draft(draft, snapshot)
        yaml_preview = compile_automation_yaml(draft)
        self.approvals.put(chat_id, draft, yaml_preview)

        if validation.ok:
            status = "Draft ready."
        else:
            status = "Draft needs review before it can be used."
        warning_text = "\n".join(f"- {item}" for item in validation.warnings)
        error_text = "\n".join(f"- {item}" for item in validation.errors)
        details = []
        if warning_text:
            details.append("Warnings:\n" + warning_text)
        if error_text:
            details.append("Blocked:\n" + error_text)
        detail_block = "\n\n".join(details)
        if detail_block:
            detail_block = "\n\n" + detail_block

        reply = (
            f"{status}\n"
            f"Draft: {draft.id}\n"
            f"Confidence: {draft.confidence:.2f}\n"
            f"{draft.explanation}{detail_block}\n\n"
            f"Reply with CONFIRM {draft.id} or CANCEL {draft.id}.\n\n"
            f"YAML preview:\n```yaml\n{yaml_preview}```"
        )
        return BridgeReply(reply, draft_id=draft.id, yaml_preview=yaml_preview)

    def _confirm(self, chat_id: str, draft_id: str) -> BridgeReply:
        pending = self.approvals.pop(draft_id, chat_id)
        if not pending:
            return BridgeReply(f"I could not find an active draft named {draft_id}.")
        result = self.writer.commit(pending.draft, pending.yaml_preview)
        return BridgeReply(f"Confirmed {draft_id}.\n{result}\n\nYAML:\n```yaml\n{pending.yaml_preview}```")

    def _confirm_latest(self, chat_id: str) -> BridgeReply:
        pending = self.approvals.pop_latest_for_chat(chat_id)
        if not pending:
            return BridgeReply("I could not find an active draft to confirm.")
        result = self.writer.commit(pending.draft, pending.yaml_preview)
        return BridgeReply(f"Confirmed {pending.draft.id}.\n{result}\n\nYAML:\n```yaml\n{pending.yaml_preview}```")
