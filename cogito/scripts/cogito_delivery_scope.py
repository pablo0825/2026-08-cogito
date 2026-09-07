"""Check actual committed delivery paths against the frozen Package."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable, Mapping, Sequence

from cogito_common import CogitoError, hash_json
from cogito_contracts import path_allowed


GitCommand = Callable[..., str]
BlobReader = Callable[[str, str], bytes]


def validate_committed_scope(
    package: Mapping[str, Any], base_commit: str, commit_id: str,
    git: GitCommand, control_paths: set[str], read_blob: BlobReader | None = None,
    *, graph_hash: str | None = None, approved_paths: Sequence[str] | None = None,
) -> None:
    """Validate effective product scope while preserving frozen control artifacts.

    Callers may supply paths from the validated effective contract. The original
    Package still owns all document hashes and committed Package identity.
    """
    product_paths = package["approved_paths"] if approved_paths is None else approved_paths
    changed = set(filter(None, git(
        "diff", "--name-only", "--no-renames", "--no-ext-diff", "--ignore-submodules=none",
        "-z", base_commit, commit_id, "--",
    ).split("\0")))
    package_path = f"docs/cogito/packages/{package['run_id']}.json"
    documents = {
        item[key]["path"] for item in package["slices"] for key in ("spec", "plan")
    }
    sources = {
        item["path"]: item["hash"] for item in package["source_registry"]
        if item["disposition"] in {"adopted", "updated"}
    }
    allowed_control = control_paths | documents | sources.keys() | {package_path}
    unexpected = sorted(
        path for path in changed
        if path not in allowed_control and not path_allowed(path, product_paths)
    )
    if unexpected:
        raise CogitoError(f"committed delivery exceeds approved paths: {unexpected}")
    if package_path in changed:
        try:
            content = (read_blob(commit_id, package_path).decode("utf-8") if read_blob
                       else git("show", f"{commit_id}:{package_path}"))
            committed_package = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CogitoError("committed Package is not valid JSON") from exc
        if hash_json(committed_package) != hash_json(package):
            raise CogitoError("committed delivery changes the frozen Package")
    for path in changed & sources.keys():
        # A source snapshot does not revoke an explicit product-path approval.
        if path_allowed(path, product_paths):
            continue
        if read_blob is None:
            raise CogitoError("committed source validation requires a raw Git blob reader")
        if hashlib.sha256(read_blob(commit_id, path)).hexdigest() != sources[path]:
            raise CogitoError(f"committed source no longer matches its frozen hash: {path}")
    graph_path = "docs/cogito/project-graph.json"
    if graph_hash is not None and graph_path in changed:
        try:
            content = (read_blob(commit_id, graph_path).decode("utf-8") if read_blob
                       else git("show", f"{commit_id}:{graph_path}"))
            graph = json.loads(content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CogitoError("committed Project Graph is not valid JSON") from exc
        if hash_json(graph) != graph_hash:
            raise CogitoError("integration changes the approved Project Graph")
