"""Compare atomic delivery with Git's merge of the reviewed Task contents."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from cogito_common import CogitoError
from cogito_contract_fields import GIT_OBJECT_RE


def validate_atomic_integration(
    results: Sequence[Mapping[str, Any]], task_ids: Sequence[str],
    source_heads: Sequence[str], previous_head: str, integration_head: str,
    control_paths: set[str], git: Callable[..., str],
) -> None:
    """Allow ordinary merges without allowing extra unreviewed product edits."""
    latest = {result["task_id"]: result for result in results
              if result.get("task_id") in task_ids and result.get("role") == "implementer"
              and result.get("status") == "complete"}
    if set(latest) != set(task_ids):
        raise CogitoError("atomic integration requires recorded Task Results")
    completed = [result for result in results
                 if result.get("task_id") in latest and result is latest[result["task_id"]]]
    tip = completed[-1]["head_commit"]
    for head in source_heads:
        git("merge-base", "--is-ancestor", head, tip)
    try:
        merge = git("merge-tree", "--write-tree", previous_head, tip)
    except CogitoError as exc:
        raise CogitoError(
            "atomic integration cannot establish a clean merge of reviewed Tasks; "
            "resolve the conflict through reviewed work before integrating"
        ) from exc
    tree = merge.splitlines()[0] if merge else ""
    if not GIT_OBJECT_RE.fullmatch(tree):
        raise CogitoError("atomic integration did not produce a valid expected merge tree")
    changed = set(filter(None, git(
        "diff", "--name-only", "--no-renames", "--no-ext-diff", "--ignore-submodules=none",
        "-z", tree, integration_head, "--",
    ).split("\0")))
    if changed - control_paths:
        raise CogitoError(
            "atomic integration changes product content outside the reviewed Task merge: "
            + ", ".join(sorted(changed - control_paths))
        )
