"""Preapproval planning rounds, stored in the run's single event journal."""
from __future__ import annotations

import base64
import copy
import difflib
import hashlib
from typing import Any, Mapping

from cogito_actions import request_fingerprint
from cogito_common import CogitoError, hash_json
from cogito_contracts import package_hash, safe_repo_path, package_document_refs
from cogito_replan_lock import run_mutation

PLANNING_EVENTS = {"planning-begun", "planning-reviewed", "planning-withdrawn"}
PREPARATION_EVENTS = {"shared-understanding-ready", "shared-understanding-confirmed", "boundary-complete"}
IMPACT_FIELDS = {"requirements", "boundary", "spec", "plan", "dag", "acceptance"}


def require_text(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CogitoError(f"{name} must be nonempty text")


def read_document(root, relative):
    if not safe_repo_path(relative):
        raise CogitoError("planning document requires a safe repository path")
    try:
        path = (root / relative).resolve()
        path.relative_to(root)
        return path.read_bytes()
    except (OSError, ValueError) as exc:
        raise CogitoError(f"cannot read planning document {relative}: {exc}") from exc


def document_snapshot(root, document):
    if not isinstance(document, dict) or not {"path", "hash"} <= document.keys():
        raise CogitoError("planning document requires path and hash")
    data = read_document(root, document["path"])
    digest = hashlib.sha256(data).hexdigest()
    if digest != document["hash"]:
        raise CogitoError(f"planning document hash drifted: {document['path']}")
    path = (root / document["path"]).resolve()
    mode = "100755" if path.stat().st_mode & 0o111 else "100644"
    return {"hash": digest, "content_base64": base64.b64encode(data).decode("ascii"),
            "mode": mode}


def capture_candidate(root, package, round_number, *, strict=False):
    """Keep exact bytes in the same atomic journal entry as candidate identity.

    Legacy callers may prepare before files exist. Preserve that fact explicitly;
    revising such a candidate requires completing its source snapshots first.
    """
    refs = package_document_refs(package, include_sources=True)
    files, unavailable, expected = {}, [], {}
    for ref in refs:
        path = ref["path"]
        if path in expected and expected[path] != ref["hash"]:
            raise CogitoError(f"conflicting planning document hashes: {path}")
        expected[path] = ref["hash"]
        try:
            files[path] = document_snapshot(root, ref)
        except CogitoError:
            if strict:
                raise
            unavailable.append({"path": path, "hash": ref["hash"]})
    body = {"round": round_number, "package": copy.deepcopy(package),
            "files": files, "unavailable": unavailable}
    return {**body, "hash": hash_json(body)}


def validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get("hash") != hash_json({k: v for k, v in snapshot.items() if k != "hash"}):
        raise CogitoError("invalid planning snapshot")
    for saved in snapshot["files"].values():
        try:
            data = base64.b64decode(saved["content_base64"], validate=True)
        except (ValueError, TypeError) as exc:
            raise CogitoError("invalid planning document snapshot") from exc
        if hashlib.sha256(data).hexdigest() != saved["hash"]:
            raise CogitoError("planning snapshot content does not match hash")
        if saved.get("mode") not in {None, "100644", "100755"}:
            raise CogitoError("planning snapshot contains an invalid document mode")


def assert_files(root, snapshot, *, strict=True):
    validate_snapshot(snapshot)
    if strict and snapshot["unavailable"]:
        raise CogitoError("source planning snapshot is incomplete; supply the original Package and matching files")
    for path, saved in snapshot["files"].items():
        if hashlib.sha256(read_document(root, path)).hexdigest() != saved["hash"]:
            raise CogitoError(f"planning document drifted: {path}; reconcile before continuing")


def validate_impact(request):
    if not isinstance(request, Mapping):
        raise CogitoError("planning request must be an object")
    if type(request.get("round")) is not int or request["round"] < 1:
        raise CogitoError("round must be a positive integer")
    candidate_hash = request.get("candidate_hash")
    if not isinstance(candidate_hash, str) or len(candidate_hash) != 64 or any(c not in "0123456789abcdef" for c in candidate_hash):
        raise CogitoError("candidate_hash must identify the source candidate")
    level = request.get("level")
    if level not in {"plan", "boundary", "requirements"}:
        raise CogitoError("planning level must be plan, boundary or requirements")
    for key in ("reason", "author_id"):
        require_text(request.get(key), key)
    impact = request.get("impact")
    if not isinstance(impact, dict) or set(impact) != IMPACT_FIELDS:
        raise CogitoError("impact must cover requirements, boundary, spec, plan, dag and acceptance")
    for key, item in impact.items():
        if not isinstance(item, dict) or item.get("disposition") not in {"reuse", "redo"}:
            raise CogitoError(f"invalid impact disposition for {key}")
        require_text(item.get("reason"), f"impact.{key}.reason")
    reuse = {"requirements", "acceptance"} if level == "boundary" else {"requirements", "boundary", "spec", "acceptance"} if level == "plan" else set()
    redo = {"requirements", "boundary"} if level == "requirements" else {"boundary"} if level == "boundary" else set()
    if any(impact[k]["disposition"] != "reuse" for k in reuse) or any(impact[k]["disposition"] != "redo" for k in redo):
        raise CogitoError("impact declarations contradict the selected planning level")


def proposal_hash(planning, candidate):
    return hash_json({"round": planning["round"], "snapshot_hash": candidate["hash"],
                      "revision": planning["revision"]["request"]})


def project_planning(state, event, payload):
    """Pure reducer. Returns True for dedicated planning events."""
    if event not in PLANNING_EVENTS:
        return False
    if state.get("package_hash") or state["state"] in {"accepted", "cancelled", "superseded"}:
        raise CogitoError("planning rounds require an unapproved active run")
    planning = state.get("planning")
    if event == "planning-begun":
        request = payload["request"]
        validate_impact(request)
        origin = state["blocked_from"] if state["state"] == "blocked" else state["state"]
        unfinished = bool(planning and planning["revision"] and not planning["candidate"])
        levels = {"plan": 0, "boundary": 1, "requirements": 2}
        if unfinished and levels[request["level"]] < levels[planning["revision"]["request"]["level"]]:
            raise CogitoError("unfinished planning cannot lower its impact level; finish the candidate or explicitly withdraw first")
        expected_hash = (package_hash(planning["revision"]["source"]["candidate"]["package"])
                         if unfinished else state["candidate_package_hash"])
        allowed = {"preparing", "awaiting-shared-confirmation", "boundary-analysis", "package-preparing"} if unfinished else set()
        if origin not in allowed | {"awaiting-package-approval"} or request["candidate_hash"] != expected_hash:
            raise CogitoError("planning must begin from the current unapproved candidate")
        old = payload["source"]
        validate_snapshot(old["candidate"])
        if package_hash(old["candidate"]["package"]) != expected_hash:
            raise CogitoError("planning source differs from current candidate")
        current_round = planning["round"] if planning else 1
        next_round = planning["next_round"] if planning else 2
        if type(request["round"]) is not int or request["round"] != current_round or payload["round"] != next_round:
            raise CogitoError("planning round changed; inspect current round")
        level = request["level"]
        if state["kind"] in {"maintenance", "documentation"} and level != "plan":
            raise CogitoError("Mini Package rounds only support unchanged-scope plan revisions")
        state["planning"] = {"round": next_round, "next_round": next_round + 1,
                             "revision": copy.deepcopy(payload), "candidate": None,
                             "review": None, "proposal_hash": None}
        shared = old["candidate"]["package"]["shared_understanding"]
        if level != "requirements" and "path" in shared:
            state["planning"]["shared_document"] = copy.deepcopy(shared)
        state["candidate_package_hash"] = None
        state["blocked_from"] = None
        if level == "requirements":
            state["shared_understanding_hash"] = None
            state["shared_understanding_revised"] = True
            state["boundary"] = None
            state["state"] = "preparing"
        elif level == "boundary":
            state["boundary"] = None
            state["state"] = "boundary-analysis"
        else:
            state["state"] = "preparing" if state["kind"] in {"maintenance", "documentation"} else "package-preparing"
    elif event == "planning-reviewed":
        if not planning or not planning["revision"] or state["state"] != "awaiting-package-approval":
            raise CogitoError("planning review requires a revised candidate")
        if type(payload.get("round")) is not int or payload["round"] != planning["round"] or payload.get("proposal_hash") != planning["proposal_hash"]:
            raise CogitoError("review does not name the current planning proposal")
        require_text(payload.get("reviewer_id"), "reviewer_id")
        if payload["reviewer_id"] == planning["revision"]["request"]["author_id"]:
            raise CogitoError("planning review requires an independent reviewer")
        if payload.get("findings") != []:
            raise CogitoError("resolve planning review findings before approval")
        assessment = payload.get("assessment", {})
        if not isinstance(assessment, dict):
            raise CogitoError("planning review assessment must be an object")
        for key in ("consistency", "impact", "reuse"):
            require_text(assessment.get(key), f"assessment.{key}")
        planning["review"] = copy.deepcopy(payload)
    else:
        if not planning or not planning["revision"] or type(payload.get("round")) is not int or payload["round"] != planning["round"]:
            raise CogitoError("withdrawal requires the current planning revision")
        if payload.get("authorized") is not True:
            raise CogitoError("withdrawing a revision requires explicit user authorization")
        require_text(payload.get("reason"), "reason")
        source = planning["revision"]["source"]
        old = copy.deepcopy(source["planning"])
        old["next_round"] = planning["next_round"]
        state["planning"] = old
        state["candidate_package_hash"] = package_hash(old["candidate"]["package"])
        state["shared_understanding_hash"] = source["shared_understanding_hash"]
        if state.get("stage_commits") and "path" in old["candidate"]["package"]["shared_understanding"]:
            state["shared_document"] = copy.deepcopy(old["candidate"]["package"]["shared_understanding"])
        state["shared_understanding_revised"] = source["shared_understanding_revised"]
        state["boundary"] = copy.deepcopy(source["boundary"])
        state["state"] = "awaiting-package-approval"
        state["blocked_from"] = None
    return True


def guard_preparation(state, event, payload):
    planning = state.get("planning")
    if not planning or not planning.get("revision"):
        return
    if event in PREPARATION_EVENTS:
        if type(payload.get("planning_round")) is not int or payload["planning_round"] != planning["round"]:
            raise CogitoError("preparation must name the current planning_round")
        if event == "shared-understanding-ready":
            if planning["revision"]["request"]["level"] != "requirements":
                raise CogitoError("this planning level must reuse the confirmed requirements")
            if payload.get("shared_understanding_hash") == planning["revision"]["source"]["shared_understanding_hash"]:
                raise CogitoError("requirements revision requires a new Shared Understanding")
            if not payload.get("document_snapshot"):
                raise CogitoError("revised Shared Understanding requires a frozen document")
    if event in {"package-ready", "mini-package-ready"}:
        snapshot = payload.get("candidate_snapshot")
        if not snapshot:
            raise CogitoError("revised candidate requires a complete planning snapshot")
        validate_revision_candidate(state, snapshot["package"])
        if snapshot["unavailable"]:
            raise CogitoError("revised planning documents must be available")
    if event == "package-approved":
        if not planning.get("candidate") or not planning.get("review"):
            raise CogitoError("revised Package requires independent planning review")
        binding = {"round": planning["round"], "proposal_hash": planning["proposal_hash"]}
        if payload.get("planning_approval") != binding or planning["review"]["proposal_hash"] != binding["proposal_hash"]:
            raise CogitoError("approval must bind the current reviewed planning proposal")
        if payload.get("package_hash", state["candidate_package_hash"]) != state["candidate_package_hash"]:
            raise CogitoError("approval Package differs from the reviewed candidate")


def project_candidate(state, payload):
    snapshot = payload.get("candidate_snapshot")
    if snapshot is None:  # Historical events remain readable.
        return
    validate_snapshot(snapshot)
    planning = state.setdefault("planning", {"round": 1, "next_round": 2, "revision": None,
                                            "candidate": None, "review": None, "proposal_hash": None})
    if snapshot["round"] != planning["round"] or package_hash(snapshot["package"]) != payload["candidate_package_hash"]:
        raise CogitoError("candidate snapshot does not match the planning round")
    planning["candidate"] = copy.deepcopy(snapshot)
    planning["review"] = None
    planning["proposal_hash"] = proposal_hash(planning, snapshot) if planning["revision"] else None


def validate_revision_candidate(state, package):
    planning = state.get("planning")
    if not planning or not planning["revision"]:
        return
    if type(package.get("planning_round")) is not int or package["planning_round"] != planning["round"]:
        raise CogitoError("Package must name the current planning_round")
    if package["kind"] not in {"maintenance", "documentation"}:
        decision, count = package["boundary"]["decision"], len(package["slices"])
        if (decision == "single-slice" and count != 1) or (decision == "split-required" and count < 2):
            raise CogitoError("Boundary decision does not match the revised Slice structure")
    old = planning["revision"]["source"]["candidate"]["package"]
    impact = planning["revision"]["request"]["impact"]
    comparable = {
        "requirements": (old["shared_understanding"], package["shared_understanding"]),
        "boundary": (old.get("boundary"), package.get("boundary")),
        "spec": ([s["spec"] for s in old["slices"]], [s["spec"] for s in package["slices"]]),
        "plan": ([s["plan"] for s in old["slices"]], [s["plan"] for s in package["slices"]]),
        "dag": (old["execution_dag"], package["execution_dag"]),
        "acceptance": ((old["checks"], old["human_gate"]), (package["checks"], package["human_gate"])),
    }
    for key, (before, after) in comparable.items():
        if impact[key]["disposition"] == "reuse" and before != after:
            raise CogitoError(f"{key} changed despite reuse declaration; revise the impact level")
    if planning["revision"]["request"]["level"] == "plan":
        before = [{k: v for k, v in s.items() if k != "plan"} for s in old["slices"]]
        after = [{k: v for k, v in s.items() if k != "plan"} for s in package["slices"]]
        if before != after or old["approved_paths"] != package["approved_paths"] or old["source_registry"] != package["source_registry"]:
            raise CogitoError("Slice or path boundary changed; boundary or requirements round required")


class PlanningMixin:
    @run_mutation
    def planning_begin(self, request: Mapping[str, Any], action_id: str):
        fingerprint = request_fingerprint("planning-begin", request=request)
        replay = self._replay(action_id, "planning-begun", fingerprint)
        if replay is not None:
            return replay
        current = self.load()
        validate_impact(request)
        planning = current.get("planning")
        snapshot = planning.get("candidate") if planning else None
        unfinished = bool(planning and planning["revision"] and not snapshot)
        previous_source = planning["revision"]["source"] if unfinished else None
        if unfinished:
            self._planning_environment(current, documents=False)
            snapshot = previous_source["candidate"]
        if not snapshot or snapshot["unavailable"]:
            source_package = request.get("source_package")
            if not isinstance(source_package, Mapping) or package_hash(source_package) != current["candidate_package_hash"]:
                raise CogitoError("original candidate snapshot unavailable; provide source_package with its recorded hash")
            snapshot = capture_candidate(self.root, source_package, planning["round"] if planning else 1, strict=True)
        if unfinished:
            validate_snapshot(snapshot)
        else:
            assert_files(self.root, snapshot)
        if planning is None:
            planning = {"round": 1, "next_round": 2, "revision": None, "review": None, "proposal_hash": None}
        source_planning = previous_source["planning"] if unfinished else {**planning, "candidate": snapshot}
        package = snapshot["package"]
        self._validate_policy(package)
        head = self._git("rev-parse", "HEAD")
        branch = self._git("branch", "--show-current")
        if branch != package["delivery_branch"]:
            raise CogitoError("planning must use the Package delivery branch")
        self._git("merge-base", "--is-ancestor", package["baseline_commit"], head)
        payload = {"round": planning["next_round"], "request": dict(request),
                   "delivery_head": head, "delivery_branch": branch,
                   "source": (copy.deepcopy(previous_source) if unfinished else {"planning": source_planning, "candidate": snapshot,
                              "shared_understanding_hash": current["shared_understanding_hash"],
                              "shared_understanding_revised": current.get("shared_understanding_revised", False),
                              "boundary": current["boundary"]})}
        return self.record("planning-begun", payload, action_id, self._GATE_AUTHORITY,
                           request_hash=fingerprint, expected_previous_hash=current["last_event_hash"])

    def _planning_environment(self, current, *, documents=True):
        planning = current.get("planning")
        if planning and planning["revision"]:
            revision = planning["revision"]
            expected_head = current.get("checkpoint_head", revision["delivery_head"])
            if self._git("rev-parse", "HEAD") != expected_head or self._git("branch", "--show-current") != revision["delivery_branch"]:
                raise CogitoError("delivery changed during planning; reconcile before continuing")
            if documents and planning.get("shared_document"):
                document_snapshot(self.root, planning["shared_document"])
            if documents:
                source = revision["source"]["candidate"]["package"]
                for role in ("spec", "plan"):
                    if revision["request"]["impact"][role]["disposition"] == "reuse":
                        for sl in source["slices"]:
                            document_snapshot(self.root, sl[role])

    def _planning_approval_binding(self, current):
        self._planning_environment(current)
        planning = current.get("planning")
        if planning and planning.get("candidate"):
            assert_files(self.root, planning["candidate"], strict=bool(planning["revision"]))
        binding = ({"round": planning["round"], "proposal_hash": planning["proposal_hash"]}
                   if planning and planning["revision"] else None)
        guard_preparation(current, "package-approved", {"planning_approval": binding})
        return binding

    @run_mutation
    def planning_review(self, request: Mapping[str, Any], action_id: str):
        fingerprint = request_fingerprint("planning-review", request=request)
        replay = self._replay(action_id, "planning-reviewed", fingerprint)
        if replay is not None:
            return replay
        current = self.load()
        self._planning_environment(current)
        planning = current.get("planning")
        if not planning or not planning.get("candidate"):
            raise CogitoError("prepare the revised candidate before review")
        assert_files(self.root, planning["candidate"])
        return self.record("planning-reviewed", request, action_id, self._GATE_AUTHORITY,
                           request_hash=fingerprint, expected_previous_hash=current["last_event_hash"])

    @run_mutation
    def planning_withdraw(self, request: Mapping[str, Any], action_id: str):
        fingerprint = request_fingerprint("planning-withdraw", request=request)
        replay = self._replay(action_id, "planning-withdrawn", fingerprint)
        if replay is not None:
            return replay
        current = self.load()
        # Only the restored source documents matter. When both rounds used
        # the same path, old and new content cannot match simultaneously.
        self._planning_environment(current, documents=False)
        planning = current.get("planning")
        if not planning or not planning["revision"]:
            raise CogitoError("there is no planning revision to withdraw")
        source = planning["revision"]["source"]["candidate"]
        assert_files(self.root, source)
        self._validate_policy(source["package"])
        return self.record("planning-withdrawn", request, action_id, self._GATE_AUTHORITY,
                           request_hash=fingerprint, expected_previous_hash=current["last_event_hash"])

    def planning_history(self):
        current = self.load()
        versions = []
        for event in self._events.read():
            snapshot = event["payload"].get("candidate_snapshot")
            if event["type"] == "planning-begun":
                snapshot = event["payload"]["source"]["candidate"]
                if any(v["snapshot_hash"] == snapshot["hash"] for v in versions):
                    continue
            if snapshot:
                validate_snapshot(snapshot)
                versions.append({"round": snapshot["round"], "candidate_hash": package_hash(snapshot["package"]),
                                 "snapshot_hash": snapshot["hash"], "package": snapshot["package"],
                                 "documents": {path: self._planning_document_view(value) for path, value in snapshot["files"].items()},
                                 "unavailable": snapshot["unavailable"],
                                 "current": current.get("planning", {}).get("candidate", {}).get("hash") == snapshot["hash"]
                                 if current.get("planning", {}).get("candidate") else False})
        return {"run_id": self.run_id, "planning": current.get("planning"), "versions": versions, "history": [
            {"sequence": e["sequence"], "type": e["type"], "payload": e["payload"]}
            for e in self._events.read() if e["type"] in PLANNING_EVENTS | PREPARATION_EVENTS | {"package-ready", "mini-package-ready", "package-approved"}
        ]}

    @staticmethod
    def _planning_document_view(saved):
        raw = base64.b64decode(saved["content_base64"])
        try:
            return {"hash": saved["hash"], "text": raw.decode("utf-8")}
        except UnicodeDecodeError:
            return {"hash": saved["hash"], "content_base64": saved["content_base64"]}

    def planning_compare(self, from_round: int, to_round: int):
        versions = self.planning_history()["versions"]
        selected = []
        for number in (from_round, to_round):
            matches = [v for v in versions if v["round"] == number]
            if not matches:
                raise CogitoError(f"round {number} has no saved candidate yet")
            selected.append(matches[-1])
        old, new = selected
        fields = sorted(set(old["package"]) | set(new["package"]))
        changes = {key: {"before": old["package"].get(key), "after": new["package"].get(key)}
                   for key in fields if old["package"].get(key) != new["package"].get(key)}
        documents = {}
        for path in sorted(set(old["documents"]) | set(new["documents"])):
            before, after = old["documents"].get(path), new["documents"].get(path)
            if before != after:
                documents[path] = {"before": before, "after": after}
                if (before is None or "text" in before) and (after is None or "text" in after):
                    documents[path]["diff"] = "".join(difflib.unified_diff(
                        (before or {}).get("text", "").splitlines(True), (after or {}).get("text", "").splitlines(True),
                        fromfile=f"round-{from_round}/{path}", tofile=f"round-{to_round}/{path}"))
        return {"run_id": self.run_id, "from_round": from_round, "to_round": to_round,
                "package_changes": changes, "document_changes": documents}

    @run_mutation
    def planning_recover(self):
        current = self.load()
        self._planning_environment(current)
        planning = current.get("planning")
        if planning and planning.get("candidate"):
            assert_files(self.root, planning["candidate"], strict=bool(planning["revision"]))
            self._validate_policy(planning["candidate"]["package"])
        return self.next_action()
