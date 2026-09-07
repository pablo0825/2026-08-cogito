"""Isolated real-Git, real-runner fixture for the four accepted legacy Results."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cogito_common import hash_json
from cogito_contracts import package_hash, validate_package
from cogito_planning import capture_candidate
from cogito_project_graph import formalize_project_graph
from cogito_run_store import RunStore
from cogito_scheduler import tasks_with_dependencies
from cogito_workflow import load_workflow
from cogito_test_support import init_repo


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class FourTasks:
    def __init__(self, *, successor=False):
        self.directory = tempfile.TemporaryDirectory(prefix="cogito-result-metadata-")
        self.root = Path(self.directory.name).resolve()
        init_repo(self.root)
        (self.root / ".gitignore").write_text(".cogito/\n")
        (self.root / "spec.md").write_text("spec\n")
        (self.root / "plan.md").write_text("plan\n")
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "fixture base")
        base = git(self.root, "rev-parse", "HEAD")
        self.worker = self.root / ".cogito/worktrees/worker"
        doc = lambda name: {"path": name, "hash": hashlib.sha256((self.root / name).read_bytes()).hexdigest()}
        tasks = [{"id": f"T-{i:03}", "slice_id": "FS-001", "responsibility": f"Task {i}",
                  "paths": [f"task{i}.txt"], "check_ids": ["V-001"]} for i in range(1, 5)]
        self.package = {
            "schema_version": "3.0", "run_id": "DEV-test", "kind": "change", "task_delivery": "atomic",
            "delivery_branch": "main", "baseline_commit": base,
            "shared_understanding": {"hash": "a" * 64},
            "boundary": {"decision": "single-slice", "evidence": ["isolated fixture"]},
            "slices": [{"id": "FS-001", "type": "change", "spec": doc("spec.md"), "plan": doc("plan.md"),
                        "worker": {"branch": "codex/worker", "worktree": ".cogito/worktrees/worker",
                                   "allowed_paths": [f"task{i}.txt" for i in range(1, 5)]}}],
            "approved_paths": [f"task{i}.txt" for i in range(1, 5)],
            "execution_dag": {"tasks": tasks, "edges": [{"from": f"T-{i:03}", "to": f"T-{i+1:03}"} for i in range(1, 4)]},
            "checks": [{"id": "V-001", "argv": [sys.executable, "-c", "print('fixture passed')"], "phase": "integration"}],
            "human_gate": {"required": False, "predicates": [], "high_risk_hotspots": []},
            "policy_snapshot": {"max_workers": 1, "fetch_allowed": False},
            "limits": {key: value for key, value in load_workflow()["limits"].items() if key != "max_workers"},
            "source_registry": [], "stop_conditions": ["stop on drift"],
        }
        self.package["package_hash"] = package_hash(self.package)
        validate_package(self.package)
        package_path = "docs/cogito/packages/DEV-test.json"
        write_json(self.root / package_path, self.package)
        graph = formalize_project_graph(None, self.package, "DEV-test")
        write_json(self.root / "docs/cogito/project-graph.json", graph)
        git(self.root, "add", ".")
        git(self.root, "commit", "-m", "fixture package")
        git(self.root, "worktree", "add", "-b", "codex/worker", str(self.worker))
        self.store = RunStore(self.root, "DEV-test")
        self.store.create("change", task_delivery=None if successor else "atomic")
        for event, payload in [
            ("shared-understanding-ready", {"shared_understanding_hash": "a" * 64}),
            ("shared-understanding-confirmed", {"confirmed": True}),
            ("boundary-complete", self.package["boundary"]),
            ("package-ready", {"package_valid": True, "candidate_package_hash": self.package["package_hash"],
                               **({"candidate_snapshot": capture_candidate(self.root, self.package, 1)} if successor else {})}),
            ("package-approved", {"approved": True, "package_path": package_path,
                "package_hash": self.package["package_hash"], "max_workers": 1, "project_graph_hash": hash_json(graph),
                "limits": self.package["limits"], "tasks": tasks_with_dependencies(self.package["execution_dag"])}),
            ("start-gate-passed", {"baseline_valid": True, "contract_valid": True, "worktrees_valid": True}),
        ]:
            self.store._events.append({"type": event, "payload": payload})
        self.results = []
        self.events = []
        for i in range(1, 5):
            task_id = f"T-{i:03}"
            self.store.update_task(task_id, "leased", "worker", f"lease-{i}")
            self.store.update_task(task_id, "running", "worker", f"running-{i}")
            base = git(self.worker, "rev-parse", "HEAD")
            (self.worker / f"task{i}.txt").write_text(f"task {i}\n")
            self.store.run_controlled_check("V-001", self.worker, f"check-{i}")
            evidence = self.store._events.read()[-1]["payload"]["evidence_path"]
            git(self.worker, "add", f"task{i}.txt")
            git(self.worker, "commit", "-m", f"task {i}")
            result = {"schema_version": "3.0", "run_id": "DEV-test", "task_id": task_id,
                      "agent_id": "worker", "role": "implementer", "status": "complete",
                      "base_commit": base, "head_commit": git(self.worker, "rev-parse", "HEAD"),
                      "changed_paths": [f"task{i}.txt"], "evidence": [evidence], "risks": [],
                      "requested_transition": "executing"}
            # Emulate an accepted event written by the old CLI, never a production bypass.
            self.store._events.append({"type": "agent-result-recorded", "payload": {"result": result}})
            self.events.append(self.store._events.read()[-1])
            self.results.append(result)
            self.store._events.append({'type': 'task-updated', 'payload': {
                'task_id': task_id, 'status': 'complete', 'agent_id': 'worker'}})
        self.store.transition("block", {"reason": "legacy Result hints"}, "block")
        self.prefix = self.store.events_path.read_bytes()

    def request(self, index=0):
        event = self.events[index]
        return {"original_event_sequence": event["sequence"], "original_event_hash": event["event_hash"],
                "result": {**self.results[index], "requested_transition": "verifying"}}

    def close(self):
        self.directory.cleanup()
