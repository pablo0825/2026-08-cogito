"""CLI payloads accept inline JSON independently of filesystem name limits."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from cogito_test_support import COGITO, GitTestCase
from cogito_gate import _json_arg, parser


GATE = COGITO / "scripts" / "cogito_gate.py"


class GateJsonPayloadTests(GitTestCase):
    def setUp(self) -> None:
        super().setUp()
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.repo = Path(directory.name)

    def invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(GATE), "--repo", str(self.repo), *args],
            text=True, capture_output=True,
        )

    def create_run(self, run_id: str) -> Path:
        result = self.invoke("init", "--run-id", run_id, "--kind", "feature")
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.repo / ".cogito" / "runs" / run_id / "events.jsonl"

    def block(self, run_id: str, payload: str) -> subprocess.CompletedProcess[str]:
        return self.invoke(
            "transition", "--run-id", run_id, "--event", "block",
            "--payload-json", payload, "--action-id", f"block-{run_id}",
        )

    def assert_payload_round_trip(self, payload: dict, label: str) -> None:
        encoded = json.dumps(payload, ensure_ascii=False)
        path = self.repo / f"{label}.json"
        path.write_text(encoded, encoding="utf-8")
        recorded = []
        for form, argument in (("inline", encoded), ("file", str(path))):
            run_id = f"DEV-json-{label}-{form}"
            events = self.create_run(run_id)
            result = self.block(run_id, argument)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["data"]["state"], "blocked")
            blocks = [
                event for event in map(json.loads, events.read_text().splitlines())
                if event["type"] == "block"
            ]
            self.assertEqual(len(blocks), 1)
            self.assertEqual(blocks[0]["action_id"], f"block-{run_id}")
            recorded.append(blocks[0]["payload"])
        self.assertEqual(recorded, [payload, payload])

    def test_ten_kilobyte_inline_payload_matches_file_payload(self) -> None:
        self.assert_payload_round_trip(
            {"reason": "x" * 10_240, "evidence": {"count": 3, "verified": True}},
            "long",
        )

    def test_unicode_inline_payload_matches_file_payload(self) -> None:
        self.assert_payload_round_trip(
            {"reason": "等待確認，保留完整測試證據。" * 100, "details": ["修正", "驗收"]},
            "unicode",
        )

    def test_short_inline_payload_and_regular_file_remain_supported(self) -> None:
        self.assert_payload_round_trip({"reason": "pending"}, "short")

    def test_empty_and_default_payload_remain_empty_objects(self) -> None:
        self.assertEqual(_json_arg(None), {})
        self.assertEqual(_json_arg(""), {})
        args = parser().parse_args([
            "transition", "--run-id", "DEV-json-default", "--event", "block",
            "--action-id", "default",
        ])
        self.assertEqual(_json_arg(args.payload_json), {})

    def assert_structured_rejection(self, argument: str, label: str) -> None:
        run_id = f"DEV-json-invalid-{label}"
        events = self.create_run(run_id)
        before = events.read_bytes()
        result = self.block(run_id, argument)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(result.stdout, "")
        error = json.loads(result.stderr)
        self.assertFalse(error["ok"])
        self.assertTrue(error["error"])
        self.assertNotIn("Traceback", result.stderr)
        self.assertEqual(events.read_bytes(), before)

    def test_invalid_inline_payloads_return_structured_errors_without_mutation(self) -> None:
        for label, argument in (
            ("malformed", '{"reason":'),
            ("array", '["reason"]'),
            ("null", "null"),
            ("string", '"reason"'),
            ("number", "42"),
            ("boolean", "true"),
            ("long-invalid", "x" * 10_240),
        ):
            with self.subTest(label=label):
                self.assert_structured_rejection(argument, label)

    def test_invalid_file_payloads_return_structured_errors_without_mutation(self) -> None:
        for label, content in (("file-malformed", '{"reason":'), ("file-array", "[]")):
            with self.subTest(label=label):
                path = self.repo / f"{label}.json"
                path.write_text(content, encoding="utf-8")
                self.assert_structured_rejection(str(path), label)

    def test_missing_file_returns_structured_error_without_mutation(self) -> None:
        self.assert_structured_rejection(str(self.repo / "missing.json"), "missing")

    def test_invalid_utf8_file_returns_structured_error_without_mutation(self) -> None:
        path = self.repo / "invalid-utf8.json"
        path.write_bytes(b'{"reason":"\xff"}')
        self.assert_structured_rejection(str(path), "invalid-utf8")

    def test_explicit_path_accepts_a_json_like_filename(self) -> None:
        payload = {"reason": "JSON-like filename"}
        path = self.repo / "null"
        path.write_text(json.dumps(payload), encoding="utf-8")
        run_id = "DEV-json-named-null"
        events = self.create_run(run_id)
        result = self.block(run_id, str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(events.read_text().splitlines()[-1])["payload"], payload)


if __name__ == "__main__":
    import unittest

    unittest.main()
