"""CLI contract for the read-only Slice inventory query."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import sys
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import cogito_gate
from cogito_common import CogitoError


class SliceInventoryCliTests(unittest.TestCase):
    def test_cli_passes_explicit_source_and_wraps_json(self) -> None:
        output = io.StringIO()
        inventory = {"schema_version": "1.0", "source": {"run_id": "DEV-old"}}
        with mock.patch(
            "cogito_slice_inventory.build_slice_inventory", return_value=inventory,
        ) as build, redirect_stdout(output):
            code = cogito_gate.main([
                "--repo", ".", "slice-inventory",
                "--source-run", "DEV-old", "--source-slice", "FS-039",
            ])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue()), {"ok": True, "data": inventory})
        self.assertEqual(build.call_args.args[1:], ("DEV-old", "FS-039"))

    def test_cli_returns_structured_error(self) -> None:
        error = io.StringIO()
        with mock.patch(
            "cogito_slice_inventory.build_slice_inventory",
            side_effect=CogitoError("source must be accepted"),
        ), redirect_stderr(error):
            code = cogito_gate.main([
                "slice-inventory", "--source-run", "DEV-old", "--source-slice", "FS-039",
            ])
        self.assertEqual(code, 2)
        self.assertEqual(
            json.loads(error.getvalue()), {"ok": False, "error": "source must be accepted"},
        )


if __name__ == "__main__":
    unittest.main()
