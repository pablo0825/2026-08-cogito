"""Immutable Start artifact publication and semantic validation."""
from __future__ import annotations

import copy
import tempfile
from pathlib import Path

import cogito_test_support
from cogito_common import CogitoError, hash_json
from cogito_git_objects import HardenedObjectReader
from cogito_planning import capture_candidate
from cogito_project_graph import formalize_project_graph
from cogito_start_artifact import (
    publish_start_artifact, validate_live_publication, validate_start_artifact,
)
from cogito_test_support import GitTestCase, git, init_repo, package
from cogito_workflow import load_workflow


class StartArtifactTests(GitTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name).resolve()
        init_repo(self.repo)
        (self.repo / "src").mkdir()
        (self.repo / "src/product.py").write_text("answer = 42\n", encoding="utf-8")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "baseline")
        self.package = package("feature")
        self.package["run_id"] = "DEV-start-next"
        self.package["baseline_commit"] = git(self.repo, "rev-parse", "HEAD")
        self.package["delivery_branch"] = "main"
        self.package["slices"][0]["id"] = "FS-start-next"
        self.package["slices"][0]["spec"] = {"path": "docs/spec.md", "hash": ""}
        self.package["slices"][0]["plan"] = {"path": "docs/plan.md", "hash": ""}
        self.package["execution_dag"]["tasks"][0]["slice_id"] = "FS-start-next"
        (self.repo / "docs/cogito/packages").mkdir(parents=True)
        for name, text in (("spec.md", "approved spec\n"), ("plan.md", "approved plan\n")):
            path = self.repo / "docs" / name
            path.write_text(text, encoding="utf-8")
            import hashlib
            self.package["slices"][0][name.split(".")[0]]["hash"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.graph = formalize_project_graph(None, self.package, self.package["run_id"])
        self.snapshot = capture_candidate(self.repo, self.package, 1, strict=True)
        self.workflow = load_workflow()

    def publish(self):
        return publish_start_artifact(
            self.repo, replan_id="RP-start", source_run_id="DEV-source",
            successor_run_id=self.package["run_id"], source_snapshot_hash="a" * 64,
            baseline_commit=self.package["baseline_commit"], package=self.package,
            package_path=f"docs/cogito/packages/{self.package['run_id']}.json",
            graph=self.graph, candidate_snapshot=self.snapshot,
            workflow_digest=hash_json(self.workflow), tool_digest="b" * 64,
            verifier_digest="c" * 64,
        )

    def test_publish_is_idempotent_and_exact_overlay_validates(self) -> None:
        before_status = git(self.repo, "status", "--porcelain=v1", "-uall")
        first = self.publish()
        second = self.publish()
        self.assertEqual(first, second)
        self.assertEqual(git(self.repo, "status", "--porcelain=v1", "-uall"), before_status)
        result = validate_start_artifact(
            HardenedObjectReader(self.repo), first.manifest,
            workflow_limits=self.workflow["limits"], expected_replan_id="RP-start",
            expected_source_run_id="DEV-source", expected_successor_run_id="DEV-start-next",
        )
        self.assertEqual(result["delivery_head"], self.package["baseline_commit"])
        self.assertEqual(git(self.repo, "rev-parse", first.ref), first.result_tree)
        types = git(self.repo, "worktree", "list", "--porcelain")
        self.assertEqual(types.count("worktree "), 1)

    def test_manifest_tampering_and_extra_tree_delta_fail_closed(self) -> None:
        artifact = self.publish()
        invalid = copy.deepcopy(artifact.manifest)
        invalid["controls"][0]["sha256"] = "0" * 64
        with self.assertRaises(CogitoError):
            validate_start_artifact(HardenedObjectReader(self.repo), invalid,
                                    workflow_limits=self.workflow["limits"])

        extra = self.repo / "extra.txt"
        extra.write_text("not approved\n", encoding="utf-8")
        oid = git(self.repo, "hash-object", "-w", str(extra))
        result_tree = git(self.repo, "mktree", input="") if False else oid
        invalid = copy.deepcopy(artifact.manifest)
        invalid["result_start_tree"] = result_tree
        invalid_hash = hash_json(invalid)
        git(self.repo, "update-ref", f"refs/cogito/start-artifacts/{invalid_hash}", result_tree)
        with self.assertRaises(CogitoError):
            validate_start_artifact(HardenedObjectReader(self.repo), invalid,
                                    workflow_limits=self.workflow["limits"])

    def test_live_publication_must_match_artifact(self) -> None:
        artifact = self.publish()
        package_path = self.repo / artifact.manifest["package_path"]
        graph_path = self.repo / artifact.manifest["project_graph_path"]
        _, package_bytes = HardenedObjectReader(self.repo).blob_at(
            artifact.result_tree, artifact.manifest["package_path"])
        _, graph_bytes = HardenedObjectReader(self.repo).blob_at(
            artifact.result_tree, artifact.manifest["project_graph_path"])
        package_path.write_bytes(package_bytes)
        graph_path.write_bytes(graph_bytes)
        validate_live_publication(self.repo, artifact.manifest)
        graph_path.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(CogitoError, "differs"):
            validate_live_publication(self.repo, artifact.manifest)

    def test_incomplete_candidate_snapshot_cannot_publish(self) -> None:
        snapshot = copy.deepcopy(self.snapshot)
        missing = next(iter(snapshot["files"]))
        snapshot["unavailable"] = [{"path": missing, "hash": snapshot["files"][missing]["hash"]}]
        body = {key: value for key, value in snapshot.items() if key != "hash"}
        snapshot["hash"] = hash_json(body)
        with self.assertRaisesRegex(CogitoError, "complete"):
            publish_start_artifact(
                self.repo, replan_id="RP-start", source_run_id="DEV-source",
                successor_run_id=self.package["run_id"], source_snapshot_hash="a" * 64,
                baseline_commit=self.package["baseline_commit"], package=self.package,
                package_path=f"docs/cogito/packages/{self.package['run_id']}.json",
                graph=self.graph, candidate_snapshot=snapshot,
                workflow_digest=hash_json(self.workflow), tool_digest="b" * 64,
                verifier_digest="c" * 64,
            )
