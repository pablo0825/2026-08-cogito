#!/usr/bin/env python3
"""Command-line interface for the Cogito 3.0 workflow gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from cogito_runtime import CogitoError, RunStore, effective_contract_hash, package_hash, render_project_graph_mermaid, render_workflow_mermaid, validate_agent_result, validate_package


def _json_arg(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            candidate = Path(value)
            if not candidate.is_file():
                raise
            parsed = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CogitoError(f"invalid JSON payload: {exc}") from exc
    if not isinstance(parsed, dict):
        raise CogitoError("JSON payload must be an object")
    return parsed


def _read_object(path: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CogitoError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CogitoError(f"{path} must contain a JSON object")
    return value


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("--repo", default=".", help="repository root")
    commands = top.add_subparsers(dest="command", required=True)
    replan = commands.add_parser("replan", help="independent replanning lifecycle")
    replan.add_argument("replan_args", nargs=argparse.REMAINDER)
    feedback = commands.add_parser("human", help="same-run human acceptance feedback")
    feedback.add_argument("operation", choices=["feedback", "triage", "start", "complete", "verify", "review", "escalate"])
    feedback.add_argument("--run-id", required=True)
    feedback.add_argument("--action-id", required=True)
    feedback.add_argument("--input")
    feedback.add_argument("--evidence", action="append")
    planning = commands.add_parser("planning", help="versioned preparation in the same run")
    planning.add_argument("operation", choices=["begin", "review", "withdraw", "history", "compare", "recover"])
    planning.add_argument("--run-id", required=True)
    planning.add_argument("--input")
    planning.add_argument("--action-id")
    planning.add_argument("--from-round", type=int)
    planning.add_argument("--to-round", type=int)
    init = commands.add_parser("init")
    init.add_argument("--stage-commits", action=argparse.BooleanOptionalAction, default=None, help="require stage checkpoints (default on, except frozen RP successors)")
    init.add_argument("--run-id", required=True)
    init.add_argument("--kind", required=True, choices=["feature", "change", "correction", "maintenance", "documentation"])
    for name in ("status", "next"):
        item = commands.add_parser(name)
        item.add_argument("--run-id", required=True)
    checkpoint = commands.add_parser("checkpoint", help="prepare or verify a confirmed stage commit")
    checkpoint.add_argument("operation", choices=["prepare", "record"])
    checkpoint.add_argument("--run-id", required=True)
    checkpoint.add_argument("--commit-id")
    checkpoint.add_argument("--action-id")
    transition = commands.add_parser("transition")
    transition.add_argument("--run-id", required=True)
    transition.add_argument("--event", required=True)
    transition.add_argument("--payload-json", default="{}")
    transition.add_argument("--action-id", required=True)
    approve = commands.add_parser("approve")
    approve.add_argument("--run-id", required=True)
    approve.add_argument("--package", required=True)
    approve.add_argument("--action-id", required=True)
    prepare = commands.add_parser("prepare-package")
    prepare.add_argument("--run-id", required=True)
    prepare.add_argument("--package", required=True)
    prepare.add_argument("--action-id", required=True)
    start = commands.add_parser("start")
    start.add_argument("--run-id", required=True)
    start.add_argument("--action-id", required=True)
    amend = commands.add_parser("amend")
    amend.add_argument("--run-id", required=True)
    amend.add_argument("--amendment", required=True)
    amend.add_argument("--action-id", required=True)
    task = commands.add_parser("task")
    task.add_argument("--run-id", required=True)
    task.add_argument("--task-id", required=True)
    task.add_argument("--status", required=True, choices=["leased", "running", "complete", "blocked", "pending"])
    task.add_argument("--agent-id", required=True)
    task.add_argument("--action-id", required=True)
    result = commands.add_parser("agent-result")
    result.add_argument("--run-id", required=True)
    result.add_argument("--input", required=True)
    result.add_argument("--action-id", required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--run-id", required=True)
    verify.add_argument("--evidence", action="append", required=True)
    verify.add_argument("--action-id", required=True)
    run_check = commands.add_parser("run-check")
    run_check.add_argument("--run-id", required=True)
    run_check.add_argument("--check-id", required=True)
    run_check.add_argument("--worktree", required=True)
    run_check.add_argument("--action-id", required=True)
    correction = commands.add_parser("correction-start")
    correction.add_argument("--run-id", required=True)
    correction.add_argument("--action-id", required=True)
    correction_done = commands.add_parser("correction-complete")
    correction_done.add_argument("--run-id", required=True)
    correction_done.add_argument("--amendment-id", required=True)
    correction_done.add_argument("--commit-id", required=True)
    correction_done.add_argument("--action-id", required=True)
    review_fix = commands.add_parser("review-fix-start")
    review_fix.add_argument("--run-id", required=True)
    review_fix.add_argument("--action-id", required=True)
    review_fix_done = commands.add_parser("review-fix-complete")
    review_fix_done.add_argument("--run-id", required=True)
    review_fix_done.add_argument("--amendment-id", required=True)
    review_fix_done.add_argument("--commit-id", required=True)
    review_fix_done.add_argument("--action-id", required=True)
    integrate = commands.add_parser("integrate")
    integrate.add_argument("--run-id", required=True)
    integrate.add_argument("--commit-id", required=True)
    integrate.add_argument("--slice-id")
    integrate.add_argument("--action-id", required=True)
    retry = commands.add_parser("retry")
    retry.add_argument("--run-id", required=True)
    retry.add_argument("--kind", required=True, choices=["transient", "format"])
    retry.add_argument("--reason", required=True)
    retry.add_argument("--action-id", required=True)
    resume = commands.add_parser("resume")
    resume.add_argument("--run-id", required=True)
    resume.add_argument("--action-id", required=True)
    post = commands.add_parser("post-verify")
    post.add_argument("--run-id", required=True)
    post.add_argument("--evidence", action="append", required=True)
    post.add_argument("--reviewer-escalation", action="store_true")
    post.add_argument("--action-id", required=True)
    human = commands.add_parser("human-approve")
    human.add_argument("--run-id", required=True)
    human.add_argument("--action-id", required=True)
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--run-id", required=True)
    finalize.add_argument("--result", required=True)
    finalize.add_argument("--project-graph", default="docs/cogito/project-graph.json")
    finalize.add_argument("--final-commit", required=True)
    finalize.add_argument("--action-id", required=True)
    report = commands.add_parser("report")
    report.add_argument("--run-id", required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("--type", required=True, choices=["package", "amendment", "agent-result"])
    validate.add_argument("--input", required=True)
    validate.add_argument("--package")
    validate.add_argument("--prior", action="append", default=[])
    render = commands.add_parser("render")
    render.add_argument("--type", required=True, choices=["workflow", "project"])
    return top


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    repo = Path(args.repo).resolve()
    try:
        if args.command == "human":
            store = RunStore(repo, args.run_id)
            if args.operation == "review":
                output = store.human_review(args.action_id)
            elif args.operation == "verify":
                if not args.evidence:
                    raise CogitoError("human verify requires --evidence")
                output = store.human_verify([_read_object(p) for p in args.evidence], args.action_id)
            else:
                if not args.input:
                    raise CogitoError("human mutation requires --input")
                operation = {"feedback": store.human_feedback, "triage": store.human_triage,
                             "start": store.human_correction_start, "complete": store.human_correction_complete,
                             "escalate": store.human_escalate}[args.operation]
                output = operation(_read_object(args.input), args.action_id)
        elif args.command == "planning":
            store = RunStore(repo, args.run_id)
            if args.operation == "history":
                output = store.planning_history()
            elif args.operation == "compare":
                if args.from_round is None or args.to_round is None:
                    raise CogitoError("planning compare requires --from-round and --to-round")
                output = store.planning_compare(args.from_round, args.to_round)
            elif args.operation == "recover":
                output = store.planning_recover()
            else:
                if not args.input or not args.action_id:
                    raise CogitoError("planning mutations require --input and --action-id")
                operation = {"begin": store.planning_begin, "review": store.planning_review,
                             "withdraw": store.planning_withdraw}[args.operation]
                output = operation(_read_object(args.input), args.action_id)
        elif args.command == "replan":
            from cogito_replan_cli import run as run_replan
            output = run_replan(repo, args.replan_args)
        elif args.command == "init":
            from cogito_checkpoints import is_frozen_successor
            stage_commits = args.stage_commits if args.stage_commits is not None else not is_frozen_successor(repo, args.run_id)
            output = RunStore(repo, args.run_id).create(args.kind, stage_commits=stage_commits)
        elif args.command == "checkpoint":
            store = RunStore(repo, args.run_id)
            if args.operation == "prepare":
                output = store.prepare_checkpoint()
            else:
                if not args.commit_id or not args.action_id:
                    raise CogitoError("checkpoint record requires --commit-id and --action-id")
                output = store.record_checkpoint(args.commit_id, args.action_id)
        elif args.command in {"status", "next"}:
            store = RunStore(repo, args.run_id)
            output = store.load() if args.command == "status" else store.next_action()
        elif args.command == "transition":
            output = RunStore(repo, args.run_id).transition(args.event, _json_arg(args.payload_json), args.action_id)
        elif args.command == "approve":
            output = RunStore(repo, args.run_id).approve_package(_read_object(args.package), args.action_id)
        elif args.command == "prepare-package":
            output = RunStore(repo, args.run_id).prepare_package(_read_object(args.package), args.action_id)
        elif args.command == "start":
            output = RunStore(repo, args.run_id).start_gate(args.action_id)
        elif args.command == "amend":
            store = RunStore(repo, args.run_id)
            amendment = _read_object(args.amendment)
            output = store.add_amendment(amendment, args.action_id)
        elif args.command == "task":
            output = RunStore(repo, args.run_id).update_task(args.task_id, args.status, args.agent_id, args.action_id)
        elif args.command == "agent-result":
            output = RunStore(repo, args.run_id).submit_agent_result(_read_object(args.input), args.action_id)
        elif args.command == "verify":
            output = RunStore(repo, args.run_id).complete_verification([_read_object(path) for path in args.evidence], args.action_id)
        elif args.command == "run-check":
            output = RunStore(repo, args.run_id).run_controlled_check(args.check_id, args.worktree, args.action_id)
        elif args.command == "correction-start":
            output = RunStore(repo, args.run_id).enter_correction(args.action_id)
        elif args.command == "correction-complete":
            output = RunStore(repo, args.run_id).complete_correction(args.amendment_id, args.commit_id, args.action_id)
        elif args.command == "review-fix-start":
            output = RunStore(repo, args.run_id).enter_review_fix(args.action_id)
        elif args.command == "review-fix-complete":
            output = RunStore(repo, args.run_id).complete_review_fix(args.amendment_id, args.commit_id, args.action_id)
        elif args.command == "integrate":
            output = RunStore(repo, args.run_id).complete_integration(args.commit_id, args.slice_id, args.action_id)
        elif args.command == "retry":
            output = RunStore(repo, args.run_id).record_retry(args.kind, args.reason, args.action_id)
        elif args.command == "resume":
            output = RunStore(repo, args.run_id).resume_gate(args.action_id)
        elif args.command == "post-verify":
            output = RunStore(repo, args.run_id).decide_post_verification(
                [_read_object(path) for path in args.evidence], args.reviewer_escalation, args.action_id
            )
        elif args.command == "human-approve":
            output = RunStore(repo, args.run_id).approve_human_gate(args.action_id)
        elif args.command == "finalize":
            output = RunStore(repo, args.run_id).finalize(args.result, args.project_graph, args.final_commit, args.action_id)
        elif args.command == "report":
            output = RunStore(repo, args.run_id).completion_report()
        elif args.command == "validate":
            value = _read_object(args.input)
            package = _read_object(args.package) if args.package else None
            if args.type == "package":
                validate_package(value)
                output = {"valid": True, "package_hash": package_hash(value)}
            elif args.type == "agent-result":
                validate_agent_result(value, package)
                output = {"valid": True}
            else:
                if not package:
                    raise CogitoError("--package is required for amendment validation")
                prior = [_read_object(path) for path in args.prior]
                output = {"valid": True, "effective_contract_hash": effective_contract_hash(package, prior + [value])}
        elif args.command == "render":
            if args.type == "workflow":
                output = {"format": "mermaid", "diagram": render_workflow_mermaid()}
            else:
                output = {"format": "mermaid", "diagram": render_project_graph_mermaid(_read_object(str(repo / "docs/cogito/project-graph.json")))}
        else:  # pragma: no cover
            raise CogitoError("unknown command")
    except CogitoError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "data": output}, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
