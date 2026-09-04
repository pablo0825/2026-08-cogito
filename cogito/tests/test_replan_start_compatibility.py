"""End-to-end compatibility for approved RP histories predating Start artifacts."""
from __future__ import annotations

import cogito_test_support
from cogito_common import canonical_json, hash_json
from cogito_events import read_events
from cogito_test_support import GitTestCase
import test_feature_multitask as feature_support
import test_replan_store as replan_support


class LegacyReplanStartCompatibilityTests(GitTestCase):
    fixture = feature_support.FeatureMultitaskTests.fixture
    result = staticmethod(feature_support.FeatureMultitaskTests.result)

    def legacy_reviewing(self):
        repo, worker, source, successor, rp, proposal = (
            replan_support.ReplanStoreTests.setup_replan(self))
        events = read_events(rp.events_path)
        prepared = events[-1]
        self.assertEqual(prepared["type"], "proposal-prepared")
        legacy = prepared["payload"]["proposal"]
        legacy.pop("start_artifact", None)
        legacy.pop("start_artifact_hash", None)
        prepared["payload"]["proposal_hash"] = hash_json(legacy)
        body = {key: value for key, value in prepared.items() if key != "event_hash"}
        prepared["event_hash"] = hash_json(body)
        rp.events_path.write_text(
            "".join(canonical_json(event) + "\n" for event in events), encoding="utf-8")
        return repo, successor, rp

    def test_legacy_proposal_completes_with_append_only_isolated_recovery(self) -> None:
        _, successor, rp = self.legacy_reviewing()
        state = rp.load()
        digest = state["proposal_hash"]
        rp.review({
            "proposal_hash": digest,
            "reviewer_id": "legacy-independent-reviewer",
            "findings": [],
            "assessment": {key: "Reviewed legacy approved controls"
                           for key in ("impact", "reuse", "revalidation", "handoff")},
        }, "legacy-review")
        rp.approve(digest, "legacy-approve")
        before_handoff = rp.events_path.read_bytes()
        self.assertEqual(rp.handoff("legacy-handoff")["state"], "completed")
        self.assertTrue(rp.events_path.read_bytes().startswith(before_handoff))
        rp_types = [event["type"] for event in read_events(rp.events_path)]
        run_types = [event["type"] for event in read_events(successor.events_path)]
        self.assertEqual(rp_types.count("handoff-start-isolated"), 1)
        self.assertEqual(rp_types.count("handoff-start-validated"), 1)
        self.assertEqual(run_types.count("start-gate-passed"), 1)
        recorded = rp.events_path.read_bytes()
        self.assertEqual(rp.handoff("legacy-handoff")["state"], "completed")
        self.assertEqual(rp.events_path.read_bytes(), recorded)
