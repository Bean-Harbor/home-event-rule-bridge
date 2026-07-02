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
        confirmed = bridge.handle_text("chat-1", f"CONFIRM {first.draft_id}", snapshot)
        self.assertIn("Dry-run mode", confirmed.text)

    def test_writer_only_writes_package_file(self) -> None:
        snapshot = fixture_snapshot()
        draft = RuleBasedParser().parse("If a package is delivered on the porch, message me.", snapshot)
        yaml_text = compile_package_yaml(draft).removeprefix("automation:\n")
        with tempfile.TemporaryDirectory() as temp:
            writer = AutomationWriter(True, Path(temp), None)
            result = writer.commit(draft, yaml_text)
            target = Path(temp) / "packages" / "home_event_rule_bridge.yaml"
            self.assertTrue(target.exists())
            self.assertIn("home_event_rule_bridge.yaml", result)
            self.assertIn("automation:", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

