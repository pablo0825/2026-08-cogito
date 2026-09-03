"""Confirmed planning stages must have separately verified Git commits."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path

from cogito_actions import request_fingerprint
from cogito_common import CogitoError, atomic_create_json
from cogito_contracts import safe_repo_path
from cogito_replan_lock import run_mutation


STAGES = {
    "shared-understanding-confirmed": "shared-understanding",
    "boundary-complete": "boundary",
    "package-approved": "package",
}


def is_frozen_successor(root, run_id):
    from cogito_replan_lock import replans
    return any(rp['successor_run_id'] == run_id and rp['state'] not in {'completed', 'abandoned'}
               for rp in replans(root))


def guard_checkpoint(state, event):
    if state.get("pending_checkpoint") and event not in {
        "stage-committed", "block", "resume", "cancel", "run-superseded",
    }:
        raise CogitoError("confirmed stage is not committed; run checkpoint prepare, commit its paths, then checkpoint record")


def project_checkpoint(state, event):
    kind, payload = event["type"], event.get("payload", {})
    if kind == "stage-committed":
        pending = state.get("pending_checkpoint")
        if (not pending or payload.get("stage_sequence") != pending["sequence"]
                or payload.get("base_commit") != state["checkpoint_head"]
                or payload.get("branch") != state["checkpoint_branch"]
                or not re.fullmatch(r"[0-9a-f]{40,64}", payload.get("commit_id", ""))
                or not payload.get("files")):
            raise CogitoError("stage commit does not match the pending checkpoint")
        state["checkpoints"].append(dict(payload))
        state["checkpoint_head"] = payload["commit_id"]
        state["pending_checkpoint"] = None
    elif state.get("stage_commits") and kind in STAGES:
        state["pending_checkpoint"] = {
            "sequence": event.get("sequence", state["sequence"] + 1), "stage": STAGES[kind],
        }


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


class CheckpointMixin:
    def _checkpoint_document_path(self, document):
        path = document.get("path") if isinstance(document, dict) else None
        if (not safe_repo_path(path) or Path(path).parts[0] in {".cogito", ".git"}):
            raise CogitoError("stage documents require a versioned repository path outside .cogito and .git")
        target = self.root / path
        try:
            target.resolve().relative_to(self.root)
        except ValueError as exc:
            raise CogitoError("stage document escapes the repository") from exc
        if any(parent.is_symlink() for parent in [target, *target.parents] if parent != self.root):
            raise CogitoError("stage documents cannot use symlinks")
        return path

    def _checkpoint_baseline(self, state):
        if state.get("stage_commits") and (
            self._git("rev-parse", "HEAD") != state["checkpoint_head"]
            or self._git("branch", "--show-current") != state["checkpoint_branch"]
        ):
            raise CogitoError("delivery changed since the last stage checkpoint")

    def _checkpoint_artifacts(self):
        state = self.load()
        pending = state.get("pending_checkpoint")
        if not pending or state["state"] in {"blocked", "cancelled", "superseded"}:
            raise CogitoError("no active confirmed stage awaits a commit")
        events = self._events.read()
        event = events[pending["sequence"] - 1]
        files = {}
        evidence = [event]
        if pending["stage"] == "shared-understanding":
            ready = next(e for e in reversed(events[:pending["sequence"]])
                         if e["type"] == "shared-understanding-ready")
            document = ready["payload"]["document"]
            files[document["path"]] = base64.b64decode(ready["payload"]["document_snapshot"]["content_base64"], validate=True)
            evidence.insert(0, ready)
        elif pending["stage"] == "package":
            package = self.approved_package()
            candidate = state["planning"]["candidate"]
            if candidate["unavailable"]:
                raise CogitoError("Package checkpoint requires complete document snapshots")
            paths = {d[key]["path"] for d in package["slices"] for key in ("spec", "plan")}
            paths.update(s["path"] for s in package["source_registry"] if s["disposition"] in {"adopted", "updated"})
            if "path" in package["shared_understanding"]:
                paths.add(package["shared_understanding"]["path"])
            for path in paths:
                files[path] = base64.b64decode(candidate["files"][path]["content_base64"], validate=True)
            files[state["package_path"]] = json_bytes(package)
            files["docs/cogito/project-graph.json"] = json_bytes(event["payload"]["project_graph_snapshot"])
        manifest_path = f"docs/cogito/checkpoints/{self.run_id}/{pending['sequence']:04d}-{pending['stage']}.json"
        if manifest_path in files:
            raise CogitoError("stage document collides with its checkpoint manifest")
        manifest = {
            "run_id": self.run_id, "stage": pending["stage"], "stage_sequence": pending["sequence"],
            "base_commit": state["checkpoint_head"], "branch": state["checkpoint_branch"],
            "events": evidence, "files": {p: digest(data) for p, data in files.items()},
        }
        files[manifest_path] = json_bytes(manifest)
        for path in files:
            self._checkpoint_document_path({"path": path})
        return state, manifest_path, manifest, files

    @run_mutation
    def prepare_checkpoint(self):
        state, path, manifest, files = self._checkpoint_artifacts()
        if self._git("branch", "--show-current") != state["checkpoint_branch"]:
            raise CogitoError("checkpoint must use the frozen delivery branch")
        # Check original files before publishing the manifest. Never overwrite a
        # user's edits or substitute a new document for confirmed bytes.
        for relative, data in files.items():
            if relative == path:
                continue
            try:
                actual = (self.root / relative).read_bytes()
            except OSError as exc:
                raise CogitoError(f"stage artifact unavailable: {relative}") from exc
            if actual != data:
                raise CogitoError(f"stage artifact drifted: {relative}")
        target = self.root / path
        if not atomic_create_json(target, manifest) and target.read_bytes() != files[path]:
            raise CogitoError("existing checkpoint manifest differs from the confirmed stage")
        return {
            "stage": manifest["stage"], "paths": sorted(files),
            "base_commit": manifest["base_commit"], "branch": manifest["branch"],
            "commit_message": f"docs(cogito): record {self.run_id} {manifest['stage']}",
            "next_action": "commit-listed-paths-and-record-checkpoint",
        }

    @run_mutation
    def record_checkpoint(self, commit_id: str, action_id: str):
        fingerprint = request_fingerprint("checkpoint-record", commit_id=commit_id)
        replay = self._replay(action_id, "stage-committed", fingerprint)
        if replay is not None:
            return replay
        state, _, manifest, files = self._checkpoint_artifacts()
        if (self._git("rev-parse", "HEAD") != commit_id
                or self._git("branch", "--show-current") != state["checkpoint_branch"]):
            raise CogitoError("stage commit must be current HEAD on its delivery branch")
        parents = self._git("rev-list", "--parents", "-n", "1", commit_id).split()[1:]
        if parents != [state["checkpoint_head"]]:
            raise CogitoError("each stage requires one separate commit directly after the previous checkpoint")
        changed = set(filter(None, self._git(
            "diff", "--name-only", "--no-renames", "--no-ext-diff", "-z",
            state["checkpoint_head"], commit_id, "--",
        ).split("\0")))
        if changed - files.keys():
            raise CogitoError(f"stage commit includes unrelated paths: {sorted(changed - files.keys())}")
        for path, expected in files.items():
            if self._git_repo.read_blob(commit_id, path) != expected:
                raise CogitoError(f"committed stage artifact differs from confirmed bytes: {path}")
            if self._git("ls-tree", commit_id, "--", path).split()[0] not in {"100644", "100755"}:
                raise CogitoError(f"stage artifact must be a regular file: {path}")
        return self.record("stage-committed", {
            "stage_sequence": manifest["stage_sequence"], "stage": manifest["stage"],
            "commit_id": commit_id, "base_commit": state["checkpoint_head"],
            "branch": state["checkpoint_branch"], "files": {p: digest(data) for p, data in files.items()},
        }, action_id, self._GATE_AUTHORITY, request_hash=fingerprint,
            expected_previous_hash=state["last_event_hash"])

    def validate_stage_commits(self):
        state = self.load()
        if not state.get("stage_commits"):
            return
        guard_checkpoint(state, "start-gate-passed")
        self._checkpoint_baseline(state)
        latest = {}
        for checkpoint in state["checkpoints"]:
            self._git("merge-base", "--is-ancestor", checkpoint["commit_id"], "HEAD")
            latest.update(checkpoint["files"])
        for path, expected in latest.items():
            if digest(self._git_repo.read_blob("HEAD", path)) != expected:
                raise CogitoError(f"committed stage artifact was changed or omitted: {path}")
