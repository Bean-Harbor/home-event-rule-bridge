from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from home_event_rule_bridge.approval import ApprovalStore
from home_event_rule_bridge.bridge import RuleBridge
from home_event_rule_bridge.compiler import compile_package_yaml, validate_draft
from home_event_rule_bridge.ha import EntitySnapshot
from home_event_rule_bridge.models import ActionSpec, RuleDraft, TriggerSpec, new_draft_id
from home_event_rule_bridge.nsp import RuleBasedParser
from home_event_rule_bridge.writer import AutomationWriter


def fixture_snapshot() -> EntitySnapshot:
    return EntitySnapshot.from_file(ROOT / "fixtures" / "ha_states.json")


class RuleBridgeTests(unittest.TestCase):
    def test_package_rule_generates_confirmable_yaml(self) -> None:
        snapshot = fixture_snapshot()
        draft = RuleBasedParser().parse("If a package is no longer visible on the porch, message me.", snapshot)
        result = validate_draft(draft, snapshot)
        yaml_text = compile_package_yaml(draft)
        self.assertTrue(result.ok)
        self.assertIn("binary_sensor.porch_package_visible", yaml_text)
        self.assertIn("persistent_notification.create", yaml_text)
        self.assertEqual(draft.trigger.to_state, "off")

    def test_driveway_rule_uses_nobody_home_condition(self) -> None:
        snapshot = fixture_snapshot()
        draft = RuleBasedParser().parse(
            "When driveway motion happens while nobody is home, send me a message.",
            snapshot,
        )
        result = validate_draft(draft, snapshot)
        self.assertTrue(result.ok)
        self.assertEqual(draft.trigger.entity_id, "binary_sensor.driveway_motion")
        self.assertEqual(draft.conditions[0].entity_id, "group.family")
        self.assertEqual(draft.conditions[0].state, "not_home")

    def test_unknown_entity_needs_review(self) -> None:
        snapshot = EntitySnapshot.empty()
        draft = RuleBasedParser().parse("If a package is missing, message me.", snapshot)
        result = validate_draft(draft, snapshot)
        self.assertFalse(result.ok)
        self.assertIn("package-visible sensor", draft.missing_slots)

    def test_high_risk_service_is_blocked(self) -> None:
        snapshot = fixture_snapshot()
        draft = RuleDraft(
            id=new_draft_id(),
            user_text="Unlock the door when Alex is home",
            intent="create_rule",
            confidence=0.9,
            trigger=TriggerSpec("state", "person.alex", "home"),
            conditions=[],
            actions=[ActionSpec("lock.unlock", target={"entity_id": "lock.front_door"})],
            entities=[],
            missing_slots=[],
            risk_level="high",
            requires_confirmation=True,
            explanation="Unsafe test.",
        )
        result = validate_draft(draft, snapshot)
        self.assertFalse(result.ok)
        self.assertIn("service is not allowlisted: lock.unlock", result.errors)

    def test_confirm_dry_run_does_not_write(self) -> None:
        snapshot = fixture_snapshot()
        bridge = RuleBridge(RuleBasedParser(), ApprovalStore(), AutomationWriter(False, None))
        first = bridge.handle_text("chat-1", "If driveway motion happens when nobody is home, message me.", snapshot)
        self.assertIsNotNone(first.draft_id)
        self.assertNotIn("YAML preview", first.text)
        confirmed = bridge.handle_text("chat-1", f"CONFIRM {first.draft_id}", snapshot)
        self.assertIn("Dry-run mode", confirmed.text)
        self.assertIn("Rule: rule_", confirmed.text)

    def test_help_and_status_are_human_readable(self) -> None:
        snapshot = fixture_snapshot()
        bridge = RuleBridge(RuleBasedParser(), ApprovalStore(), AutomationWriter(False, None))
        help_reply = bridge.handle_text("chat-1", "help", snapshot)
        self.assertIn("Home Event Rule Bridge", help_reply.text)
        self.assertIn("dry-run mode", help_reply.text)
        status_reply = bridge.handle_text("chat-1", "status", snapshot)
        self.assertIn("HA snapshot:", status_reply.text)

    def test_show_yaml_is_explicit(self) -> None:
        snapshot = fixture_snapshot()
        bridge = RuleBridge(RuleBasedParser(), ApprovalStore(), AutomationWriter(False, None))
        first = bridge.handle_text("chat-1", "If driveway motion happens when nobody is home, message me.", snapshot)
        yaml_reply = bridge.handle_text("chat-1", "show yaml", snapshot)
        self.assertIn(f"YAML preview for {first.draft_id}", yaml_reply.text)
        self.assertIn("binary_sensor.driveway_motion", yaml_reply.text)

    def test_simple_confirm_uses_latest_draft_for_same_chat(self) -> None:
        snapshot = fixture_snapshot()
        bridge = RuleBridge(RuleBasedParser(), ApprovalStore(), AutomationWriter(False, None))
        first = bridge.handle_text("chat-1", "If driveway motion happens when nobody is home, message me.", snapshot)
        self.assertIsNotNone(first.draft_id)
        confirmed = bridge.handle_text("chat-1", "Confirmed", snapshot)
        self.assertIn(f"Confirmed {first.draft_id}", confirmed.text)
        self.assertIn("Dry-run mode", confirmed.text)

    def test_simple_confirm_does_not_cross_chat_scope(self) -> None:
        snapshot = fixture_snapshot()
        bridge = RuleBridge(RuleBasedParser(), ApprovalStore(), AutomationWriter(False, None))
        bridge.handle_text("chat-1", "If driveway motion happens when nobody is home, message me.", snapshot)
        confirmed = bridge.handle_text("chat-2", "yes", snapshot)
        self.assertIn("I could not find an active draft", confirmed.text)

    def test_missing_entity_goes_to_clarification(self) -> None:
        snapshot = fixture_snapshot()
        bridge = RuleBridge(RuleBasedParser(), ApprovalStore(), AutomationWriter(False, None))
        reply = bridge.handle_text("chat-1", "Let me know if a mystery device goes offline", snapshot)
        self.assertIn("I need a little more detail", reply.text)
        self.assertIn("Which entity should I use?", reply.text)

    def test_clarification_number_updates_latest_draft(self) -> None:
        snapshot = fixture_snapshot()
        bridge = RuleBridge(RuleBasedParser(), ApprovalStore(), AutomationWriter(False, None))
        bridge.handle_text("chat-1", "Let me know if a mystery device goes offline", snapshot)
        updated = bridge.handle_text("chat-1", "1", snapshot)
        self.assertIn("Draft ready", updated.text)
        self.assertIn("Confidence:", updated.text)

    def test_list_and_show_confirmed_rules(self) -> None:
        snapshot = fixture_snapshot()
        bridge = RuleBridge(RuleBasedParser(), ApprovalStore(), AutomationWriter(False, None))
        first = bridge.handle_text("chat-1", "If driveway motion happens when nobody is home, message me.", snapshot)
        confirmed = bridge.handle_text("chat-1", f"CONFIRM {first.draft_id}", snapshot)
        rule_id = [part for part in confirmed.text.split() if part.startswith("rule_")][0]
        listed = bridge.handle_text("chat-1", "list rules", snapshot)
        self.assertIn(rule_id, listed.text)
        shown = bridge.handle_text("chat-1", f"show rule {rule_id}", snapshot)
        self.assertIn("Status: active", shown.text)

    def test_writer_only_writes_package_file(self) -> None:
        snapshot = fixture_snapshot()
        draft = RuleBasedParser().parse("If a package is delivered on the porch, message me.", snapshot)
        yaml_text = compile_package_yaml(draft).removeprefix("automation:\n")
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "configuration.yaml").write_text(
                "homeassistant:\n  packages: !include_dir_named packages\n",
                encoding="utf-8",
            )
            writer = AutomationWriter(True, Path(temp), None)
            result = writer.commit(draft, yaml_text)
            target = Path(temp) / "packages" / "home_event_rule_bridge.yaml"
            self.assertTrue(target.exists())
            self.assertIn("home_event_rule_bridge.yaml", result)
            self.assertIn("automation:", target.read_text(encoding="utf-8"))

    def test_writer_refuses_when_packages_are_not_enabled(self) -> None:
        snapshot = fixture_snapshot()
        draft = RuleBasedParser().parse("If a package is delivered on the porch, message me.", snapshot)
        yaml_text = compile_package_yaml(draft).removeprefix("automation:\n")
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "configuration.yaml").write_text("default_config:\n", encoding="utf-8")
            writer = AutomationWriter(True, Path(temp), None)
            with self.assertRaises(RuntimeError):
                writer.commit(draft, yaml_text)


if __name__ == "__main__":
    unittest.main()
