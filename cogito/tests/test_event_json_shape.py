"""Non-object event JSON is rejected without mutating run or Git state."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from cogito_test_support import GitTestCase, SCRIPTS, git, init_repo
from cogito_events import read_events


class EventJsonShapeTests(GitTestCase):
    def setUp(self) -> None:
        super().setUp()
        temporary = tempfile.TemporaryDirectory(prefix="cogito-event-shape-")
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name).resolve()
        init_repo(self.repo)
        (self.repo / ".gitignore").write_text(".cogito/\n", encoding="utf-8")
        git(self.repo, "add", ".gitignore")
        git(self.repo, "commit", "-qm", "baseline")
        self.run_id = "DEV-event-json-shape"
        initialized = self.gate("init", "--no-stage-commits", "--run-id", self.run_id, "--kind", "feature")
        self.assertEqual(initialized.returncode, 0, initialized.stderr)
        self.events = self.repo / ".cogito/runs" / self.run_id / "events.jsonl"
        self.cache = self.events.with_name("state.json")
        self.index = self.repo / ".git/index"
        self.initial_events = self.events.read_bytes()
        self.initial_cache = self.cache.read_bytes()
        self.initial_index = self.index.read_bytes()

    def gate(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPTS / "cogito_gate.py"),
             "--repo", str(self.repo), *arguments],
            capture_output=True, text=True, timeout=20,
        )

    def assert_rejected_without_mutation(self, damaged: bytes, line: int, diagnostic: str) -> None:
        self.events.write_bytes(damaged)
        for command in ("status", "next"):
            with self.subTest(command=command):
                result = self.gate(command, "--run-id", self.run_id)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("Traceback", result.stderr)
                response = json.loads(result.stderr)
                self.assertIs(response["ok"], False)
                self.assertIn(f"line {line}", response["error"])
                self.assertIn(diagnostic, response["error"])
                self.assertEqual(self.events.read_bytes(), damaged)
                self.assertEqual(self.cache.read_bytes(), self.initial_cache)
                self.assertEqual(self.index.read_bytes(), self.initial_index)

    def test_nonobject_event_values_on_first_and_second_lines_return_structured_errors(self) -> None:
        for label, value in (
            ("array", []), ("null", None), ("string", "event"),
            ("number", 42), ("boolean", True),
        ):
            encoded = json.dumps(value).encode("utf-8") + b"\n"
            for line, prefix in ((1, b""), (2, self.initial_events)):
                with self.subTest(value=label, line=line):
                    self.assert_rejected_without_mutation(prefix + encoded, line, "object")

    def test_invalid_json_syntax_still_reports_the_affected_line(self) -> None:
        for line, prefix in ((1, b""), (2, self.initial_events)):
            with self.subTest(line=line):
                self.assert_rejected_without_mutation(prefix + b'{"type":\n', line, "invalid event JSON")

    def test_valid_event_objects_replay_and_rebuild_the_cache(self) -> None:
        arguments = (
            "transition", "--run-id", self.run_id, "--event", "block",
            "--payload-json", json.dumps({"reason": "等待補齊資料"}, ensure_ascii=False),
            "--action-id", "block-shape-test",
        )
        blocked = self.gate(*arguments)
        self.assertEqual(blocked.returncode, 0, blocked.stderr)
        receipt = json.loads(blocked.stdout)["data"]
        self.assertEqual(receipt["state"], "blocked")
        events_before = self.events.read_bytes()
        decoded = read_events(self.events)
        self.assertEqual(len(decoded), 2)
        self.assertEqual(decoded[-1]["payload"]["reason"], "等待補齊資料")
        self.cache.unlink()
        restored = self.gate("status", "--run-id", self.run_id)
        self.assertEqual(restored.returncode, 0, restored.stderr)
        expected = json.loads(restored.stdout)["data"]
        self.assertEqual(expected["blocked_from"], "preparing")
        self.assertEqual(json.loads(self.cache.read_text(encoding="utf-8")), expected)
        next_action = self.gate("next", "--run-id", self.run_id)
        self.assertEqual(next_action.returncode, 0, next_action.stderr)
        self.assertEqual(json.loads(next_action.stdout)["data"]["state"], "blocked")
        replayed = self.gate(*arguments)
        self.assertEqual(replayed.returncode, 0, replayed.stderr)
        self.assertEqual(json.loads(replayed.stdout)["data"], receipt)
        self.assertEqual(self.events.read_bytes(), events_before)
        self.assertEqual(self.index.read_bytes(), self.initial_index)


if __name__ == "__main__":
    unittest.main()
