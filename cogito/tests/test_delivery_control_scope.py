"""Committed scope preserves exact bootstrap controls and raw source bytes."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

from cogito_test_support import GitTestCase, init_repo, package
from cogito_common import CogitoError, hash_json
from cogito_contracts import package_hash
from cogito_delivery_scope import validate_committed_scope
from cogito_git import GitRepository


class DeliveryControlScopeTests(GitTestCase):
    def setUp(self):
        super().setUp()
        temporary = tempfile.TemporaryDirectory(prefix="cogito-control-scope-")
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        init_repo(self.repo)
        self.repository = GitRepository(self.repo)
        self.git = self.repository.run
        (self.repo / "baseline.txt").write_text("baseline\n")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.base = self.git("rev-parse", "HEAD")
        self.binary = b"source\r\n\x00\xff\ntrailing whitespace \r\n"
        self.package = package("feature")
        self.package["baseline_commit"] = self.base
        self.package["source_registry"] = [{
            "path": "legacy/source.bin", "hash": hashlib.sha256(self.binary).hexdigest(),
            "relevance": "approved bootstrap source", "disposition": "adopted",
        }]
        self.package["package_hash"] = package_hash(self.package)
        self.package_path = f"docs/cogito/packages/{self.package['run_id']}.json"
        self.graph_path = "docs/cogito/project-graph.json"
        self.graph = {"schema_version": "3.0", "active_run_id": self.package["run_id"],
                      "slices": {}, "dependencies": []}
        self.write(self.package_path, json.dumps(self.package).encode())
        self.write(self.graph_path, json.dumps(self.graph).encode())
        self.write("docs/spec.md", b"necessary updated spec\r\n")
        self.write("docs/plan.md", b"necessary updated plan\n")
        self.write("legacy/source.bin", self.binary)
        self.write("src/value.txt", b"implemented\n")

    def write(self, relative, content):
        target = self.repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    def commit(self):
        self.git("add", "--all")
        self.git("commit", "-qm", "commit bootstrap and product")
        return self.git("rev-parse", "HEAD")

    def validate(self, final, approved_paths=None):
        index = self.repo / ".git/index"
        before = index.read_bytes()
        try:
            validate_committed_scope(
                self.package, self.base, final, self.git, {self.graph_path},
                self.repository.read_blob, graph_hash=hash_json(self.graph),
                approved_paths=approved_paths,
            )
        finally:
            self.assertEqual(index.read_bytes(), before)

    def test_exact_bootstrap_controls_and_binary_crlf_source_are_accepted(self):
        final = self.commit()
        self.assertEqual(self.repository.read_blob(final, "legacy/source.bin"), self.binary)
        self.assertEqual(self.repository.read_blob(final, "docs/spec.md"), b"necessary updated spec\r\n")
        self.validate(final)

    def test_other_document_does_not_inherit_control_directory_exception(self):
        self.write("docs/other.md", b"not approved\n")
        with self.assertRaisesRegex(CogitoError, "exceeds approved paths"):
            self.validate(self.commit())

    def test_effective_paths_allow_addition_without_rewriting_frozen_package(self):
        self.write("mappers/value.py", b"value = 1\n")
        final = self.commit()
        with self.assertRaisesRegex(CogitoError, "exceeds approved paths"):
            self.validate(final)
        self.validate(final, [*self.package["approved_paths"], "mappers/value.py"])

    def test_effective_exact_path_does_not_authorize_its_sibling(self):
        self.write("mappers/value.py", b"value = 1\n")
        self.write("mappers/other.py", b"not approved\n")
        with self.assertRaisesRegex(CogitoError, "exceeds approved paths"):
            self.validate(self.commit(), [*self.package["approved_paths"], "mappers/value.py"])

    def test_effective_paths_do_not_allow_replacing_committed_package(self):
        paths = [*self.package["approved_paths"], "mappers/value.py"]
        modified = {**self.package, "approved_paths": paths}
        modified["package_hash"] = package_hash(modified)
        self.write(self.package_path, json.dumps(modified).encode())
        with self.assertRaisesRegex(CogitoError, "frozen Package"):
            self.validate(self.commit(), paths)

    def test_effective_paths_preserve_unrelated_source_hash_checks(self):
        self.write("legacy/source.bin", self.binary + b"unapproved\n")
        with self.assertRaisesRegex(CogitoError, "frozen hash"):
            self.validate(self.commit(), [*self.package["approved_paths"], "mappers/value.py"])

    def test_committed_package_tamper_is_rejected_even_when_live_file_is_restored(self):
        modified = {**self.package, "stop_conditions": ["changed after approval"]}
        self.write(self.package_path, json.dumps(modified).encode())
        final = self.commit()
        self.write(self.package_path, json.dumps(self.package).encode())
        with self.assertRaisesRegex(CogitoError, "frozen Package"):
            self.validate(final)

    def test_committed_graph_tamper_is_rejected_even_when_live_file_is_restored(self):
        modified = {**self.graph, "active_run_id": "another-run"}
        self.write(self.graph_path, json.dumps(modified).encode())
        final = self.commit()
        self.write(self.graph_path, json.dumps(self.graph).encode())
        with self.assertRaisesRegex(CogitoError, "approved Project Graph"):
            self.validate(final)

    def test_committed_source_tamper_is_rejected_even_when_live_file_is_restored(self):
        self.write("legacy/source.bin", self.binary + b"unapproved\r\n")
        final = self.commit()
        self.write("legacy/source.bin", self.binary)
        with self.assertRaisesRegex(CogitoError, "frozen hash"):
            self.validate(final)

    def test_registered_source_inside_approved_product_paths_can_be_updated(self):
        # Registry hashes describe the source that existed at approval. An
        # explicit product path grant can authorize changing that source.
        self.package["approved_paths"].append("legacy/source.bin")
        self.package["package_hash"] = package_hash(self.package)
        self.write(self.package_path, json.dumps(self.package).encode())
        self.write("legacy/source.bin", self.binary + b"approved update\r\n")
        self.validate(self.commit())

    def test_frozen_package_bool_cannot_be_replaced_by_equal_python_integer(self):
        modified = json.loads(json.dumps(self.package))
        modified["human_gate"]["predicates"][0]["applicable"] = 1
        self.assertEqual(modified, self.package)  # Python equality loses JSON type identity.
        self.write(self.package_path, json.dumps(modified).encode())
        with self.assertRaisesRegex(CogitoError, "frozen Package"):
            self.validate(self.commit())

    def test_invalid_utf8_committed_package_returns_domain_error(self):
        self.write(self.package_path, b'{"invalid":"\xff"}')
        with self.assertRaisesRegex(CogitoError, "Package is not valid JSON"):
            self.validate(self.commit())

    def test_invalid_utf8_committed_graph_returns_domain_error(self):
        self.write(self.graph_path, b'{"invalid":"\xff"}')
        with self.assertRaisesRegex(CogitoError, "Graph is not valid JSON"):
            self.validate(self.commit())
