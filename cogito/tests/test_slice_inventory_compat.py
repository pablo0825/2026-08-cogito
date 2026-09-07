"""Historical read-only compatibility used only by Slice inventory."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError, hash_json
from cogito_slice_inventory_compat import (
    EVENT, compatible_result, compatible_snapshot, validate_resolution_checks,
)


class SliceInventoryCompatibilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract_hash = "c" * 64
        self.request_hash = "a" * 64
        self.replacement = {
            "sequence": 4,
            "type": "check-evidence-recorded",
            "action_id": "replacement",
            "request_hash": self.request_hash,
            "payload": {
                "check_id": "C-1",
                "evidence_path": "/run/evidence.json",
                "evidence_hash": "e" * 64,
                "effective_contract_hash": self.contract_hash,
            },
        }
        self.payload = {
            "interrupted_action_id": "interrupted",
            "replacement_action_id": "replacement",
            "resolver_id": "user:reviewer",
            "reason": "confirmed no process or side effect remained",
            "request_hash": self.request_hash,
            "check_id": "C-1",
            "evidence_path": "/run/evidence.json",
            "evidence_hash": "e" * 64,
            "check_hash": hash_json({"id": "C-1", "argv": ["python3", "-V"]}),
            "effective_contract_hash": self.contract_hash,
        }
        self.resolution = {
            "sequence": 5, "type": EVENT, "payload": self.payload,
        }
        self.events = [
            {"sequence": 1, "type": "run-created", "payload": {}},
            self.replacement,
            self.resolution,
            {"sequence": 9, "type": "finalization-complete", "payload": {}},
        ]
        self.workflow = {"terminal_states": ["accepted"]}

    def test_compatible_snapshot_validates_then_filters_only_resolution_event(self) -> None:
        before = {"state": "executing", "effective_contract_hash": self.contract_hash}
        accepted = {"state": "accepted", "effective_contract_hash": self.contract_hash}
        with mock.patch(
            "cogito_slice_inventory_compat.project_events", side_effect=[before, accepted],
        ) as project:
            snapshot = compatible_snapshot(self.events, self.workflow)
        self.assertEqual(snapshot.state, accepted)
        self.assertEqual(snapshot.events, self.events)
        self.assertNotIn(self.resolution, project.call_args_list[-1].args[0])

    def test_result_receipt_must_exactly_match_the_resolution_event(self) -> None:
        receipt = {"event_sequence": 5, "event": EVENT, **self.payload}
        result = {"delivery_summary": {"verification": [receipt, {"event": "other"}]}}
        compatible = compatible_result(result, self.events)
        self.assertEqual(compatible["delivery_summary"]["verification"], [{"event": "other"}])
        self.assertEqual(result["delivery_summary"]["verification"][0], receipt)

        changed = {**result, "delivery_summary": {"verification": [{**receipt, "reason": "changed"}]}}
        with self.assertRaisesRegex(CogitoError, "does not match"):
            compatible_result(changed, self.events)

    def test_invalid_or_late_resolution_is_rejected(self) -> None:
        bad = [*self.events]
        bad[2] = {**self.resolution, "payload": {**self.payload, "evidence_hash": "d" * 64}}
        with self.assertRaises(CogitoError):
            compatible_snapshot(bad, self.workflow)

        late = [self.events[0], self.replacement, self.events[-1], self.resolution]
        with self.assertRaisesRegex(CogitoError, "after finalization"):
            compatible_snapshot(late, self.workflow)

    def test_replacement_is_unique_and_check_hash_matches_effective_contract(self) -> None:
        duplicate = {
            **self.resolution,
            "sequence": 6,
            "payload": {**self.payload, "interrupted_action_id": "other-interrupted"},
        }
        events = [*self.events[:-1], duplicate, self.events[-1]]
        before = {"state": "executing", "effective_contract_hash": self.contract_hash}
        with mock.patch("cogito_slice_inventory_compat.project_events", return_value=before):
            with self.assertRaisesRegex(CogitoError, "reused"):
                compatible_snapshot(events, self.workflow)

        effective = {"checks": [{"id": "C-1", "argv": ["python3", "-V"]}]}
        validate_resolution_checks(self.events, effective)
        changed = [
            event if event.get("type") != EVENT else {
                **event, "payload": {**event["payload"], "check_hash": "d" * 64},
            }
            for event in self.events
        ]
        with self.assertRaisesRegex(CogitoError, "check contract"):
            validate_resolution_checks(changed, effective)


if __name__ == "__main__":
    unittest.main()
