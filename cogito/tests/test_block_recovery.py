"""Additional block reasons preserve the origin needed to resume a run."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from cogito_common import CogitoError
from cogito_projection import reduce_events
from cogito_workflow import load_workflow


def event(event_type: str, **payload) -> dict:
    return {"type": event_type, "payload": payload}


class BlockRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workflow = load_workflow()
        self.created = event("run-created", run_id="DEV-block", kind="feature")
        self.blocks = [event("block", reason="first finding"), event("block", reason="additional finding")]

    def test_replaying_existing_double_blocks_preserves_origin_and_allows_resume(self) -> None:
        for origin, prefix in (
            ("preparing", [self.created]),
            ("awaiting-shared-confirmation", [self.created, event("shared-understanding-ready", shared_understanding_hash="a" * 64)]),
        ):
            with self.subTest(origin=origin):
                history = [*prefix, *self.blocks]
                before = copy.deepcopy(history)
                blocked = reduce_events(history, self.workflow)
                self.assertEqual((blocked["state"], blocked["blocked_from"]), ("blocked", origin))
                self.assertEqual(history, before)
                resumed = reduce_events([*history, event("resume", target=origin, validated=True)], self.workflow)
                self.assertEqual(resumed["state"], origin)
                self.assertIsNone(resumed["blocked_from"])
                self.assertEqual(history, before)

    def test_a_new_block_cycle_records_the_new_origin_after_resume(self) -> None:
        history = [
            self.created, *self.blocks, event("resume", target="preparing", validated=True),
            event("shared-understanding-ready", shared_understanding_hash="a" * 64), *self.blocks,
        ]
        before = copy.deepcopy(history)
        state = reduce_events(history, self.workflow)
        self.assertEqual(state["blocked_from"], "awaiting-shared-confirmation")
        self.assertEqual(history, before)

    def test_additional_blocks_preserve_tasks_and_counters_but_terminal_runs_reject_them(self) -> None:
        prefix = [
            event("run-created", run_id="MNT-block", kind="maintenance"),
            event("mini-package-ready", package_valid=True, candidate_package_hash="a" * 64),
            event("package-approved", approved=True, package_path="package.json", package_hash="a" * 64,
                  tasks=[{"id": "T-1", "paths": ["src"]}], max_workers=3, project_graph_hash="b" * 64, limits={}),
            event("transient-retry", reason="temporary failure"),
        ]
        initial = reduce_events(prefix, self.workflow)
        history = [*prefix, *self.blocks]
        before = copy.deepcopy(history)
        blocked = reduce_events(history, self.workflow)
        self.assertEqual(blocked["blocked_from"], "start-gate")
        self.assertEqual(blocked["tasks"], initial["tasks"])
        self.assertEqual(blocked["counters"], {"transient_retries": 1})
        self.assertEqual(history, before)
        cancelled = [*history, event("cancel", authorized=True)]
        self.assertEqual(reduce_events(cancelled, self.workflow)["state"], "cancelled")
        with self.assertRaises(CogitoError):
            reduce_events([*cancelled, event("block", reason="too late")], self.workflow)


if __name__ == "__main__":
    unittest.main()
