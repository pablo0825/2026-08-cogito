"""Publish and verify an immutable, checkout-free RP successor Start artifact."""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from cogito_common import CogitoError, hash_json
from cogito_contracts import package_hash, validate_package_with_limits
from cogito_git_objects import HardenedObjectReader, TreeEntry
from cogito_planning import validate_snapshot
from cogito_project_graph import validate_project_graph
from cogito_replan_start import control_paths


MANIFEST_FIELDS = {
    "schema_version", "replan_id", "source_run_id", "successor_run_id",
    "source_snapshot_hash", "object_format", "baseline_commit", "baseline_tree",
    "result_start_tree", "package_path", "package_hash", "project_graph_path",
    "project_graph_hash", "effective_contract_hash", "controls", "policy_digest",
    "workflow_digest", "tool_digest", "verifier_digest",
}


@dataclass(frozen=True)
class PublishedStartArtifact:
    manifest: dict[str, Any]
    artifact_hash: str
    ref: str
    result_tree: str


def json_bytes(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _write_git(reader: HardenedObjectReader, index: Path, *args: str,
               data: bytes | None = None, allowed_codes: tuple[int, ...] = (0,)) -> bytes:
    env = reader._environment()
    env["GIT_INDEX_FILE"] = str(index)
    try:
        result = subprocess.run(
            reader._argv(*args), input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, timeout=reader.timeout, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise CogitoError(f"cannot publish Start artifact: {exc}") from exc
    if result.returncode not in allowed_codes:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise CogitoError(f"cannot publish Start artifact: {detail or 'Git command failed'}")
    return result.stdout


def _candidate_files(package: Mapping[str, Any], package_path: str,
                     graph: Mapping[str, Any],
                     snapshot: Mapping[str, Any]) -> dict[str, tuple[str, bytes]]:
    validate_snapshot(snapshot)
    if snapshot.get("unavailable"):
        raise CogitoError("Start artifact requires a complete successor candidate snapshot")
    if package_hash(snapshot.get("package", {})) != package_hash(package):
        raise CogitoError("Start artifact candidate differs from the RP successor Package")
    published = copy.deepcopy(dict(package))
    published["package_hash"] = package_hash(package)
    files = {package_path: ("100644", json_bytes(published)),
             "docs/cogito/project-graph.json": ("100644", json_bytes(dict(graph)))}
    for path, saved in snapshot.get("files", {}).items():
        try:
            content = base64.b64decode(saved["content_base64"], validate=True)
        except (KeyError, TypeError, ValueError) as exc:
            raise CogitoError("Start artifact contains an invalid candidate document") from exc
        if hashlib.sha256(content).hexdigest() != saved.get("hash"):
            raise CogitoError("Start artifact candidate document hash changed")
        # Historical candidate snapshots predate mode capture. They may enter a
        # newly reviewed proposal with the conservative regular-file mode.
        mode = saved.get("mode", "100644")
        if mode not in {"100644", "100755"}:
            raise CogitoError("Start artifact candidate snapshot contains an invalid document mode")
        files[path] = (mode, content)
    required = set(control_paths(package, package_path))
    if set(files) != required:
        missing = sorted(required - set(files))
        extra = sorted(set(files) - required)
        raise CogitoError(f"Start artifact controls differ from Package references: missing={missing}, extra={extra}")
    return files


def _publish_ref(reader: HardenedObjectReader, ref: str, tree: str) -> None:
    zero = "0" * reader.oid_chars
    result = _write_git(reader, Path(os.devnull), "update-ref", ref, tree, zero,
                        allowed_codes=(0, 128))
    if result is not None:
        try:
            reader.require_ref(ref, tree)
        except CogitoError as exc:
            raise CogitoError("Start artifact ref already exists with different content") from exc


def publish_start_artifact(root: str | Path, *, replan_id: str, source_run_id: str,
                           successor_run_id: str, source_snapshot_hash: str,
                           baseline_commit: str, package: Mapping[str, Any], package_path: str,
                           graph: Mapping[str, Any], candidate_snapshot: Mapping[str, Any],
                           workflow_digest: str, tool_digest: str,
                           verifier_digest: str) -> PublishedStartArtifact:
    """Write immutable blobs/tree/ref before proposal publication; create no checkout."""
    root = Path(root).resolve()
    reader = HardenedObjectReader(root)
    baseline_commit = reader.require_full_oid(baseline_commit, "baseline commit")
    baseline_tree = reader.commit_tree(baseline_commit)
    validate_project_graph(graph)
    files = _candidate_files(package, package_path, graph, candidate_snapshot)
    with tempfile.TemporaryDirectory(prefix="cogito-start-index-") as directory:
        index = Path(directory) / "index"
        _write_git(reader, index, "read-tree", baseline_tree)
        records = bytearray()
        controls: list[dict[str, Any]] = []
        for path, (mode, content) in sorted(files.items()):
            oid = _write_git(reader, index, "hash-object", "-w", "--no-filters", "--stdin",
                             data=content).decode("ascii").strip()
            reader.require_full_oid(oid, f"control blob {path}")
            records.extend(f"{mode} {oid}\t".encode("ascii") + path.encode("utf-8") + b"\0")
            controls.append({"path": path, "mode": mode, "type": "blob", "oid": oid,
                             "sha256": hashlib.sha256(content).hexdigest()})
        _write_git(reader, index, "update-index", "-z", "--index-info", data=bytes(records))
        result_tree = _write_git(reader, index, "write-tree").decode("ascii").strip()
    reader.require_full_oid(result_tree, "result Start tree")
    manifest = {
        "schema_version": 1,
        "replan_id": replan_id,
        "source_run_id": source_run_id,
        "successor_run_id": successor_run_id,
        "source_snapshot_hash": source_snapshot_hash,
        "object_format": reader.object_format,
        "baseline_commit": baseline_commit,
        "baseline_tree": baseline_tree,
        "result_start_tree": result_tree,
        "package_path": package_path,
        "package_hash": package_hash(package),
        "project_graph_path": "docs/cogito/project-graph.json",
        "project_graph_hash": hash_json(graph),
        "effective_contract_hash": package_hash(package),
        "controls": controls,
        "policy_digest": hash_json(package["policy_snapshot"]),
        "workflow_digest": workflow_digest,
        "tool_digest": tool_digest,
        "verifier_digest": verifier_digest,
    }
    artifact_hash = hash_json(manifest)
    ref = f"refs/cogito/start-artifacts/{artifact_hash}"
    _publish_ref(reader, ref, result_tree)
    validate_start_artifact(reader, manifest, workflow_limits=package["limits"])
    return PublishedStartArtifact(manifest, artifact_hash, ref, result_tree)


def _leaf_map(entries: tuple[TreeEntry, ...]) -> dict[bytes, tuple[str, str]]:
    return {entry.path: (entry.mode, entry.oid) for entry in entries if entry.type == "blob"}


def validate_start_artifact(reader: HardenedObjectReader, manifest: Mapping[str, Any], *,
                            workflow_limits: Mapping[str, Any],
                            expected_replan_id: str | None = None,
                            expected_source_run_id: str | None = None,
                            expected_successor_run_id: str | None = None) -> dict[str, Any]:
    if not isinstance(manifest, Mapping) or set(manifest) != MANIFEST_FIELDS or manifest.get("schema_version") != 1:
        raise CogitoError("invalid Start artifact manifest shape or version")
    if manifest["object_format"] != reader.object_format:
        raise CogitoError("Start artifact object format differs from repository")
    for expected, field in ((expected_replan_id, "replan_id"),
                            (expected_source_run_id, "source_run_id"),
                            (expected_successor_run_id, "successor_run_id")):
        if expected is not None and manifest[field] != expected:
            raise CogitoError(f"Start artifact {field} differs from approved context")
    commit = reader.require_full_oid(manifest["baseline_commit"], "baseline commit")
    baseline_tree = reader.require_full_oid(manifest["baseline_tree"], "baseline tree")
    result_tree = reader.require_full_oid(manifest["result_start_tree"], "result Start tree")
    if reader.commit_tree(commit) != baseline_tree:
        raise CogitoError("Start artifact baseline commit/tree binding is invalid")
    reader.require_ref(f"refs/cogito/start-artifacts/{hash_json(manifest)}", result_tree)
    baseline = _leaf_map(reader.walk_tree(baseline_tree))
    result = _leaf_map(reader.walk_tree(result_tree))
    controls = manifest["controls"]
    if not isinstance(controls, list) or not controls:
        raise CogitoError("Start artifact controls must be a nonempty list")
    paths: list[str] = []
    content: dict[str, bytes] = {}
    expected_result = dict(baseline)
    for item in controls:
        if (not isinstance(item, Mapping) or set(item) != {"path", "mode", "type", "oid", "sha256"}
                or item.get("mode") not in {"100644", "100755"} or item.get("type") != "blob"):
            raise CogitoError("Start artifact contains an invalid control entry")
        path = item.get("path")
        if not isinstance(path, str):
            raise CogitoError("Start artifact control path must be text")
        oid = reader.require_full_oid(item.get("oid"), f"control blob {path}")
        entry, data = reader.blob_at(result_tree, path)
        if entry.mode != item["mode"] or entry.oid != oid or hashlib.sha256(data).hexdigest() != item.get("sha256"):
            raise CogitoError("Start artifact control bytes or identity differ from manifest")
        raw_path = path.encode("utf-8")
        expected_result[raw_path] = (item["mode"], oid)
        paths.append(path)
        content[path] = data
    if paths != sorted(set(paths)) or expected_result != result:
        raise CogitoError("Start artifact result tree is not the exact approved control overlay")
    package_path = manifest["package_path"]
    graph_path = manifest["project_graph_path"]
    if not isinstance(package_path, str) or graph_path != "docs/cogito/project-graph.json":
        raise CogitoError("Start artifact publication paths are invalid")
    try:
        package = json.loads(content[package_path])
        graph = json.loads(content[graph_path])
    except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CogitoError("Start artifact Package or Graph is not valid JSON") from exc
    validate_package_with_limits(package, workflow_limits)
    validate_project_graph(graph)
    if (package_hash(package) != manifest["package_hash"]
            or package.get("package_hash") != manifest["package_hash"]
            or package.get("run_id") != manifest["successor_run_id"]
            or package.get("baseline_commit") != commit
            or set(paths) != set(control_paths(package, package_path))
            or hash_json(graph) != manifest["project_graph_hash"]
            or graph.get("active_run_id") != manifest["successor_run_id"]
            or manifest["effective_contract_hash"] != manifest["package_hash"]
            or manifest["policy_digest"] != hash_json(package["policy_snapshot"])):
        raise CogitoError("Start artifact semantic bindings are invalid")
    return {"delivery_head": commit, "delivery_tree": result_tree,
            "package_hash": manifest["package_hash"],
            "project_graph_hash": manifest["project_graph_hash"]}


def validate_live_publication(root: str | Path, manifest: Mapping[str, Any]) -> None:
    root = Path(root).resolve()
    for field, digest in (("package_path", manifest["package_hash"]),
                          ("project_graph_path", manifest["project_graph_hash"])):
        relative = Path(manifest[field])
        path = root / relative
        try:
            cursor = root
            for component in relative.parts:
                cursor = cursor / component
                if cursor.is_symlink():
                    raise CogitoError("approved Start publication must not traverse symlinks")
            if not path.is_file():
                raise CogitoError("approved Start publication must be a regular file")
            value = json.loads(path.read_bytes())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CogitoError(f"cannot read approved Start publication {path}: {exc}") from exc
        actual = package_hash(value) if field == "package_path" else hash_json(value)
        if actual != digest:
            raise CogitoError("live Start publication differs from approved artifact")
