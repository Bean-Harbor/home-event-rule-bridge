from __future__ import annotations

from dataclasses import dataclass

from .approval import ApprovalStore, PendingDraft
from .audit import AuditLogger
from .compiler import compile_automation_yaml, validate_draft
from .ha import EntitySnapshot, HomeAssistantState
from .models import ActionSpec, ConditionSpec, EntityRef, RuleDraft, TriggerSpec
from .nsp import Parser
from .writer import AutomationWriter


@dataclass(frozen=True)
class BridgeReply:
    text: str
    draft_id: str | None = None
    yaml_preview: str | None = None


class RuleBridge:
    SIMPLE_CONFIRMATIONS = {"CONFIRM", "CONFIRMED", "YES", "Y", "OK", "APPROVE", "APPROVED"}
    CLARIFICATION_THRESHOLD = 0.60
    FIND_DOMAIN_PRIORITY = {
        "switch": 0,
        "light": 1,
        "input_boolean": 2,
        "scene": 3,
        "script": 4,
        "person": 5,
        "device_tracker": 6,
        "camera": 7,
        "binary_sensor": 8,
        "sensor": 9,
        "group": 10,
        "weather": 20,
        "zone": 21,
    }

    def __init__(
        self,
        parser: Parser,
        approvals: ApprovalStore,
        writer: AutomationWriter,
        audit: AuditLogger | None = None,
    ) -> None:
        self.parser = parser
        self.approvals = approvals
        self.writer = writer
        self.audit = audit or AuditLogger()

    def handle_text(self, chat_id: str, text: str, snapshot: EntitySnapshot) -> BridgeReply:
        stripped = text.strip()
        if not stripped:
            return BridgeReply(self._help_text(snapshot))

        lower = stripped.lower()
        upper = stripped.upper()

        if lower in {"help", "/help"}:
            return BridgeReply(self._help_text(snapshot))
        if lower in {"status", "/status"}:
            return BridgeReply(self._status_text(snapshot))
        if lower in {"devices", "what devices do you know about?", "what devices do you know about"}:
            return BridgeReply(self._devices_text(snapshot))
        if lower.startswith("find "):
            return BridgeReply(self._find_text(stripped[5:].strip(), snapshot))
        if lower in {"list rules", "rules"}:
            return BridgeReply(self._list_rules(chat_id))
        if lower.startswith("show rule "):
            return BridgeReply(self._show_rule(chat_id, stripped.split(maxsplit=2)[2].strip()))
        if lower.startswith("show yaml"):
            return BridgeReply(self._show_yaml(chat_id, stripped))
        if lower.startswith("edit"):
            return self._edit(chat_id, stripped, snapshot)
        if upper.startswith("CONFIRM DISABLE "):
            return self._confirm_management(chat_id, stripped.split(maxsplit=2)[2].strip(), "disabled")
        if upper.startswith("CONFIRM DELETE "):
            return self._confirm_management(chat_id, stripped.split(maxsplit=2)[2].strip(), "deleted")
        if lower.startswith("disable rule "):
            return BridgeReply(self._request_management(chat_id, stripped.split(maxsplit=2)[2].strip(), "disable"))
        if lower.startswith("delete rule "):
            return BridgeReply(self._request_management(chat_id, stripped.split(maxsplit=2)[2].strip(), "delete"))
        if upper.startswith("CONFIRM "):
            return self._confirm(chat_id, stripped.split(maxsplit=1)[1].strip())
        if upper in self.SIMPLE_CONFIRMATIONS:
            return self._confirm_latest(chat_id)
        if upper.startswith("CANCEL "):
            draft_id = stripped.split(maxsplit=1)[1].strip()
            if self.approvals.cancel(draft_id, chat_id):
                self.audit.append("draft_canceled", {"chat_id": chat_id, "draft_id": draft_id})
                return BridgeReply(f"Canceled {draft_id}.")
            return BridgeReply(f"I could not find an active draft named {draft_id}.")
        if lower == "cancel":
            latest = self.approvals.latest_for_chat(chat_id)
            if latest and self.approvals.cancel(latest.draft.id, chat_id):
                self.audit.append("draft_canceled", {"chat_id": chat_id, "draft_id": latest.draft.id})
                return BridgeReply(f"Canceled {latest.draft.id}.")
            return BridgeReply("I could not find an active draft to cancel.")

        clarification = self._try_clarification_reply(chat_id, stripped, snapshot)
        if clarification:
            return clarification
        return self._create_draft(chat_id, stripped, snapshot)

    def _create_draft(self, chat_id: str, text: str, snapshot: EntitySnapshot) -> BridgeReply:
        draft = self.parser.parse(text, snapshot)
        validation = validate_draft(draft, snapshot)
        yaml_preview = compile_automation_yaml(draft)
        suggestions = self._entity_suggestions(draft, text, snapshot)
        self.approvals.put(chat_id, draft, yaml_preview, validation, suggestions=suggestions)
        self.audit.append(
            "draft_created",
            {
                "chat_id": chat_id,
                "draft_id": draft.id,
                "confidence": draft.confidence,
                "missing_slots": draft.missing_slots,
                "ok": validation.ok,
            },
        )

        if self._needs_clarification(draft, validation_ok=validation.ok):
            return BridgeReply(self._clarification_card(draft, suggestions, snapshot), draft.id, yaml_preview)
        return BridgeReply(self._draft_card(draft, validation.errors, validation.warnings), draft.id, yaml_preview)

    def _try_clarification_reply(
        self,
        chat_id: str,
        text: str,
        snapshot: EntitySnapshot,
    ) -> BridgeReply | None:
        pending = self.approvals.latest_for_chat(chat_id)
        if not pending or not self._needs_clarification(pending.draft, validation_ok=pending.validation.ok):
            return None
        if self._looks_like_new_rule_request(text):
            return None

        entity_id = self._resolve_clarification_entity(text, pending, snapshot)
        if not entity_id:
            return None
        self.approvals.cancel(pending.draft.id, chat_id)
        return self._create_draft(chat_id, f"{pending.draft.user_text} {entity_id}", snapshot)

    def _looks_like_new_rule_request(self, text: str) -> bool:
        lower = text.strip().lower()
        starters = ("if ", "when ", "let me know", "tell me", "notify me", "turn on", "turn off", "run ")
        return lower.startswith(starters) or " when " in lower or " if " in lower

    def _resolve_clarification_entity(self, text: str, pending: PendingDraft, snapshot: EntitySnapshot) -> str | None:
        cleaned = text.strip()
        if cleaned.isdigit():
            index = int(cleaned) - 1
            if 0 <= index < len(pending.suggestions):
                return pending.suggestions[index]
        if snapshot.exists(cleaned):
            return cleaned
        match = snapshot.find_one(cleaned, {"binary_sensor", "sensor", "switch", "light", "camera", "person", "group"})
        return match.entity_id if match else None

    def _confirm(self, chat_id: str, draft_id: str) -> BridgeReply:
        pending = self.approvals.get(draft_id, chat_id)
        if not pending:
            return BridgeReply(f"I could not find an active draft named {draft_id}.")
        if self._needs_clarification(pending.draft, validation_ok=pending.validation.ok):
            return BridgeReply(self._clarification_card(pending.draft, pending.suggestions))
        self.approvals.pop(draft_id, chat_id)
        try:
            result = self.writer.commit(pending.draft, pending.yaml_preview)
        except Exception as exc:
            self.audit.append("commit_failed", {"chat_id": chat_id, "draft_id": draft_id, "error": str(exc)})
            return BridgeReply(f"I could not commit {draft_id}.\n{exc}")
        rule = self.approvals.remember_rule(chat_id, pending.draft, pending.yaml_preview, result)
        self.audit.append(
            "draft_confirmed",
            {
                "chat_id": chat_id,
                "draft_id": draft_id,
                "rule_id": rule.rule_id,
                "write_mode": self.writer.allow_write,
                "result": result,
            },
        )
        return BridgeReply(
            f"Confirmed {draft_id}.\n"
            f"Rule: {rule.rule_id}\n"
            f"{result}\n\n"
            f"Use `show rule {rule.rule_id}` or `show yaml {rule.rule_id}` to review it."
        )

    def _confirm_latest(self, chat_id: str) -> BridgeReply:
        pending = self.approvals.latest_for_chat(chat_id)
        if not pending:
            return BridgeReply("I could not find an active draft to confirm.")
        return self._confirm(chat_id, pending.draft.id)

    def _show_yaml(self, chat_id: str, text: str) -> str:
        parts = text.split()
        target = parts[2] if len(parts) >= 3 else None
        if target:
            pending = self.approvals.get(target, chat_id)
            if pending:
                return f"YAML preview for {target}:\n```yaml\n{pending.yaml_preview}```"
            rule = self.approvals.get_rule(chat_id, target)
            if rule:
                return f"YAML for {target}:\n```yaml\n{rule.yaml_preview}```"
            return f"I could not find a draft or rule named {target}."
        pending = self.approvals.latest_for_chat(chat_id)
        if pending:
            return f"YAML preview for {pending.draft.id}:\n```yaml\n{pending.yaml_preview}```"
        return "I could not find an active draft. Create a rule first, then ask `show yaml`."

    def _edit(self, chat_id: str, text: str, snapshot: EntitySnapshot) -> BridgeReply:
        replacement = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) == 2 else ""
        if not replacement:
            return BridgeReply("Tell me the correction after `edit`, or just send a clearer rule sentence.")
        latest = self.approvals.latest_for_chat(chat_id)
        if latest:
            self.approvals.cancel(latest.draft.id, chat_id)
        return self._create_draft(chat_id, replacement, snapshot)

    def _list_rules(self, chat_id: str) -> str:
        rules = self.approvals.list_rules(chat_id)
        if not rules:
            return "No confirmed bridge rules in this chat yet."
        lines = ["Bridge-managed rules:"]
        for rule in rules[:12]:
            lines.append(f"- {rule.rule_id} [{rule.status}] {rule.explanation}")
        return "\n".join(lines)

    def _show_rule(self, chat_id: str, rule_id: str) -> str:
        rule = self.approvals.get_rule(chat_id, rule_id)
        if not rule:
            return f"I could not find a bridge-managed rule named {rule_id}."
        return (
            f"Rule {rule.rule_id}\n"
            f"Status: {rule.status}\n"
            f"Draft: {rule.draft_id}\n"
            f"Request: {rule.user_text}\n"
            f"Meaning: {rule.explanation}\n"
            f"Last result: {rule.last_result}\n\n"
            f"Use `show yaml {rule.rule_id}` to inspect the automation."
        )

    def _request_management(self, chat_id: str, rule_id: str, action: str) -> str:
        rule = self.approvals.get_rule(chat_id, rule_id)
        if not rule:
            return f"I could not find a bridge-managed rule named {rule_id}."
        verb = "DISABLE" if action == "disable" else "DELETE"
        mode = "dry-run management" if not self.writer.allow_write else "managed package update"
        return (
            f"{action.title()} request ready for {rule_id}.\n"
            f"Mode: {mode}.\n"
            f"Reply with `CONFIRM {verb} {rule_id}` or `cancel`."
        )

    def _confirm_management(self, chat_id: str, rule_id: str, status: str) -> BridgeReply:
        updated = self.approvals.update_rule_status(chat_id, rule_id, status)
        if not updated:
            return BridgeReply(f"I could not find a bridge-managed rule named {rule_id}.")
        self.audit.append("rule_status_updated", {"chat_id": chat_id, "rule_id": rule_id, "status": status})
        result = "Dry-run mode: no Home Assistant files were changed."
        if self.writer.allow_write:
            result = "Marked in bridge memory. Package editing for disable/delete is not enabled yet."
        return BridgeReply(f"{updated.rule_id} is now {updated.status}.\n{result}")

    def _help_text(self, snapshot: EntitySnapshot) -> str:
        return (
            "Home Event Rule Bridge drafts Home Assistant rules from normal chat.\n"
            f"{self._status_text(snapshot)}\n\n"
            "First run:\n"
            "1. `devices` - see what Home Assistant entities I can read.\n"
            "2. `find <thing>` - narrow the list, for example `find camera`.\n"
            "3. Describe one rule in a sentence.\n"
            "4. Use `show yaml` if you want the automation preview.\n"
            "5. Use `confirm` / `ok`, `edit <clearer rule>`, or `cancel`.\n\n"
            "Example rules:\n"
            "- Let me know if the HarborDock test switch goes offline\n"
            "- If a package is no longer visible on the porch, message me\n"
            "- When driveway motion happens while nobody is home, notify me\n\n"
            "Other commands: `status`, `list rules`, `show rule <id>`."
        )

    def _status_text(self, snapshot: EntitySnapshot) -> str:
        connection = f"HA snapshot: {len(snapshot.states)} entities" if snapshot.states else "HA snapshot: empty or unavailable"
        write_mode = "write mode" if self.writer.allow_write else "dry-run mode"
        return f"Status: {connection}; {write_mode}; parser={self.parser.display_name}."

    def _needs_clarification(self, draft: RuleDraft, validation_ok: bool) -> bool:
        return bool(draft.missing_slots) or draft.confidence < self.CLARIFICATION_THRESHOLD or not validation_ok

    def _clarification_card(
        self,
        draft: RuleDraft,
        suggestions: list[str],
        snapshot: EntitySnapshot | None = None,
    ) -> str:
        lines = [
            self._clarification_question(draft),
            f"Draft: {draft.id}",
            f"Confidence: {draft.confidence:.2f}",
            f"Reason: {draft.explanation}",
        ]
        if draft.missing_slots:
            lines.append("Missing: " + ", ".join(draft.missing_slots))
        note = self._clarification_note(draft, has_suggestions=bool(suggestions))
        if note:
            lines.append(note)
        if suggestions:
            lines.append("\nCandidates:")
            for index, entity_id in enumerate(suggestions, start=1):
                lines.append(f"{index}. {self._format_suggestion(entity_id, snapshot)}")
            lines.append("\nReply with a number, an entity id, `edit <clearer rule>`, or `cancel`.")
        else:
            find_hint = self._clarification_find_hint(draft)
            lines.append(
                f"\nTry `devices` to see the snapshot, `find {find_hint}` to search, "
                "or `edit <clearer rule>`."
            )
            lines.append("You can also reply `cancel`.")
        return "\n".join(lines)

    def _draft_card(self, draft: RuleDraft, errors: list[str], warnings: list[str]) -> str:
        lines = [
            "Draft ready.",
            f"Draft: {draft.id}",
            f"Meaning: {draft.explanation}",
            f"When: {self._trigger_text(draft.trigger)}",
            f"If: {self._conditions_text(draft.conditions)}",
            f"Do: {self._actions_text(draft.actions)}",
            f"Matched: {self._entities_text(draft.entities)}",
            "Safety: dry-run until confirmed",
            f"Risk: {draft.risk_level}",
            f"Confidence: {draft.confidence:.2f}",
        ]
        if warnings:
            lines.append("Warnings: " + "; ".join(warnings))
        if errors:
            lines.append("Blocked: " + "; ".join(errors))
        lines.append("\nReply with `confirm`, `edit <clearer rule>`, `cancel`, or `show yaml`.")
        return "\n".join(lines)

    def _entity_suggestions(self, draft: RuleDraft, text: str, snapshot: EntitySnapshot) -> list[str]:
        if not draft.missing_slots and draft.confidence >= self.CLARIFICATION_THRESHOLD:
            return []
        missing = " ".join(draft.missing_slots).lower()
        lower_text = text.lower()
        allow_fallback = True
        if "scene" in missing or "script" in missing:
            domains = {"scene", "script"}
        elif "action target" in missing:
            domains = {"light", "switch"}
        elif "person" in missing or "tracker" in missing:
            domains = {"person", "device_tracker"}
        elif "motion" in missing:
            domains = {"binary_sensor"}
        elif "package" in missing:
            domains = {"binary_sensor", "sensor"}
        elif "device entity" in missing or "device" in missing:
            domains, allow_fallback = self._monitor_domains_for_text(lower_text)
        else:
            domains = {"binary_sensor", "sensor", "switch", "light", "camera", "person", "group", "scene", "script"}
        matches = snapshot.find(text, domains=domains)
        if not matches:
            matches = [state for state in snapshot.states if state.domain in domains] if allow_fallback else []
        return [state.entity_id for state in matches[:5]]

    def _monitor_domains_for_text(self, lower_text: str) -> tuple[set[str], bool]:
        if "camera" in lower_text:
            return {"camera"}, False
        if "switch" in lower_text:
            return {"switch"}, False
        if "light" in lower_text:
            return {"light"}, False
        if "sensor" in lower_text:
            return {"binary_sensor", "sensor"}, False
        return {"binary_sensor", "sensor", "switch", "light", "camera", "input_boolean"}, True

    def _devices_text(self, snapshot: EntitySnapshot) -> str:
        if not snapshot.states:
            return "I do not have a Home Assistant entity snapshot yet."
        order = ["binary_sensor", "camera", "light", "switch", "scene", "script", "person", "group", "sensor"]
        grouped: dict[str, list[str]] = {}
        for state in snapshot.states:
            grouped.setdefault(state.domain, []).append(self._format_entity(state.entity_id, state.friendly_name))
        lines = [f"I can see {len(snapshot.states)} Home Assistant entities:"]
        for domain in order + sorted(set(grouped) - set(order)):
            items = sorted(grouped.get(domain, []))
            if not items:
                continue
            visible = items[:6]
            suffix = f" (+{len(items) - len(visible)} more)" if len(items) > len(visible) else ""
            lines.append(f"- {domain}: " + ", ".join(visible) + suffix)
        lines.append("\nUse `find <text>` to narrow this down.")
        return "\n".join(lines)

    def _find_text(self, query: str, snapshot: EntitySnapshot) -> str:
        cleaned = self._clean_find_query(query)
        if not cleaned:
            return "Tell me what to find, for example `find switch` or `find harbordock`."
        matches = snapshot.find(cleaned)
        if not matches:
            return f"I could not find anything matching `{cleaned}`. Try `devices` to see what I know."
        matches = self._rank_find_matches(cleaned, matches)
        lines = [f"Matches for `{cleaned}`:"]
        for state in matches[:8]:
            lines.append(f"- {self._format_entity(state.entity_id, state.friendly_name)} [{state.state}]")
        if len(matches) > 8:
            lines.append(f"...and {len(matches) - 8} more.")
        return "\n".join(lines)

    def _clean_find_query(self, query: str) -> str:
        lowered = query.strip().lower()
        prefixes = [
            "devices related to ",
            "device related to ",
            "entities related to ",
            "entity related to ",
            "related to ",
        ]
        for prefix in prefixes:
            if lowered.startswith(prefix):
                return query.strip()[len(prefix) :].strip()
        return query.strip()

    def _format_entity(self, entity_id: str, friendly_name: str | None) -> str:
        return f"{entity_id} ({friendly_name})" if friendly_name else entity_id

    def _rank_find_matches(self, query: str, matches: list[HomeAssistantState]) -> list[HomeAssistantState]:
        requested_domains = self._requested_find_domains(query)
        indexed = list(enumerate(matches))
        indexed.sort(key=lambda item: (self._find_domain_rank(item[1], requested_domains), item[0]))
        return [state for _, state in indexed]

    def _requested_find_domains(self, query: str) -> set[str]:
        tokens = {token.strip().lower() for token in query.replace("_", " ").split()}
        aliases = {
            "switches": "switch",
            "lights": "light",
            "scenes": "scene",
            "scripts": "script",
            "cameras": "camera",
            "sensors": "sensor",
            "people": "person",
            "persons": "person",
        }
        normalized = {aliases.get(token, token) for token in tokens}
        return {domain for domain in self.FIND_DOMAIN_PRIORITY if domain in normalized}

    def _find_domain_rank(self, state: HomeAssistantState, requested_domains: set[str]) -> int:
        if requested_domains and state.domain in requested_domains:
            return -1
        return self.FIND_DOMAIN_PRIORITY.get(state.domain, 50)

    def _clarification_question(self, draft: RuleDraft) -> str:
        missing = " ".join(draft.missing_slots).lower()
        if "action" in missing and "target" not in missing:
            return "What should happen: notify you, turn something on/off, or run a scene?"
        if "action target" in missing:
            return "Which device should I control?"
        if "scene" in missing or "script" in missing:
            return "Which scene or script should I run?"
        if "condition" in missing:
            return "Should this always run, or only when nobody is home / after sunset?"
        return "Which device should I watch?"

    def _clarification_note(self, draft: RuleDraft, has_suggestions: bool) -> str | None:
        missing = " ".join(draft.missing_slots).lower()
        lower_text = draft.user_text.lower()
        if "action target" in missing:
            requested = self._requested_device_phrase(lower_text, ["light", "switch"])
            if requested:
                if has_suggestions:
                    return f"I could not find an exact match for `{requested}`. I found this controllable candidate:"
                return f"I do not see a {requested} in this Home Assistant snapshot."
        if "scene" in missing or "script" in missing:
            requested = self._requested_device_phrase(lower_text, ["scene", "script"])
            if requested:
                if has_suggestions:
                    return f"I could not find an exact match for `{requested}`. I found these scene/script candidates:"
                return f"I do not see a {requested} in this Home Assistant snapshot."
        if "device entity" in missing or "device" in missing:
            requested = self._requested_device_phrase(lower_text, ["camera", "light", "switch", "sensor", "device"])
            if requested:
                if has_suggestions:
                    return f"I could not find an exact match for `{requested}`. I found this possible match:"
                return f"I do not see a {requested} in this Home Assistant snapshot."
        return None

    def _clarification_find_hint(self, draft: RuleDraft) -> str:
        missing = " ".join(draft.missing_slots).lower()
        lower_text = draft.user_text.lower()
        for domain in ["camera", "light", "switch", "scene", "script", "sensor"]:
            if domain in missing or domain in lower_text:
                return domain
        if "person" in missing or "tracker" in missing:
            return "person"
        return "device"

    def _format_suggestion(self, entity_id: str, snapshot: EntitySnapshot | None) -> str:
        if not snapshot:
            return entity_id
        state = snapshot.by_id.get(entity_id)
        if not state:
            return entity_id
        return f"{self._format_entity(state.entity_id, state.friendly_name)} [{state.state}]"

    def _requested_device_phrase(self, lower_text: str, nouns: list[str]) -> str | None:
        words = [word.strip(".,!?;:()[]{}\"'`") for word in lower_text.split()]
        stop_words = {
            "a",
            "an",
            "the",
            "my",
            "me",
            "if",
            "when",
            "while",
            "someone",
            "nobody",
            "everyone",
            "turn",
            "on",
            "off",
            "run",
            "say",
            "message",
            "notify",
            "tell",
            "let",
            "know",
        }
        for index, word in enumerate(words):
            if word not in nouns:
                continue
            start = index
            while start > 0 and words[start - 1] and words[start - 1] not in stop_words:
                start -= 1
            phrase = " ".join(words[start : index + 1]).strip()
            return phrase if phrase and phrase != word else word
        return None

    def _trigger_text(self, trigger: TriggerSpec) -> str:
        if trigger.kind == "state":
            target = trigger.entity_id or "unknown entity"
            suffix = f" -> {trigger.to_state}" if trigger.to_state is not None else ""
            return f"{target}{suffix}"
        return trigger.label or trigger.kind

    def _conditions_text(self, conditions: list[ConditionSpec]) -> str:
        if not conditions:
            return "none"
        rendered = []
        for condition in conditions:
            if condition.kind == "state":
                rendered.append(f"{condition.entity_id} == {condition.state}")
            else:
                rendered.append(condition.label or condition.kind)
        return "; ".join(rendered)

    def _actions_text(self, actions: list[ActionSpec]) -> str:
        if not actions:
            return "none"
        rendered = []
        for action in actions:
            title = action.data.get("title") if action.data else None
            target = (action.target or {}).get("entity_id")
            label = action.label or title
            detail = label or target
            rendered.append(f"{action.service}" + (f" ({detail})" if detail else ""))
        return "; ".join(rendered)

    def _entities_text(self, entities: list[EntityRef]) -> str:
        if not entities:
            return "none matched"
        return ", ".join(self._format_entity(entity.entity_id, entity.name) for entity in entities)
