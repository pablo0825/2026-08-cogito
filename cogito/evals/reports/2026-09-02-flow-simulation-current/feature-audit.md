# Feature flow audit — current code

- Agent started: 2026-09-02 15:41:54 UTC; work completed: 2026-09-02 15:46:42 UTC; elapsed: 4 minutes 48 seconds (below 10-minute limit).
- Source HEAD: `72f9f263e445ec1f060b289c76da2f9020d83e4e`.
- Python 3.12.10; Git 2.50.1; macOS. Git tests isolate personal Git configuration, hooks, signing and inherited Git environment variables.
- All product repositories were isolated temporary repositories; no product code was changed. The new reproduction explicitly uses `/tmp`; existing tests use the operating system's temporary directory.
- Package approval and implementer/reviewer identities are synthetic fixture inputs, not a real user's approval or actual independent semantic product reviews.

## Result

38 existing tests passed. One additional valid Feature DAG scenario found a reproducible workflow deadlock: two sequential tasks in the same Slice, with separate owned paths and separate commits, cannot complete the first task's review after both implementations finish.

## Checks run

1. `python3 -B -m unittest discover -s cogito/tests -p 'test_feature_e2e.py' -v`
   - 4 tests passed in 4.037 seconds.
   - Two cross-Slice DAG workers, rejected premature dependent lease, verification, independent reviewer identity gates, serial integration, post-integration checks, finalization, immutable completion reporting, explicit workflow propagation, incorrect product rejection and unverified-final-content rejection.
   - Evidence: `feature-e2e.log`.
2. `PYTHONPATH=cogito/tests python3 -B -m unittest test_integration_scope test_delivery_control_scope test_finalization_rules test_integration_rules -v`
   - 34 tests passed in 8.289 seconds.
   - Revalidates `ca72258`: unapproved Feature/Change/Correction merge content rejected through the real CLI, including rename and Unicode/newline paths; package-wide approved integration corrections remain permitted; final delivery scope and precise control-document exceptions remain enforced.
   - Evidence: `feature-integration-regression.log`.
3. `python3 -B cogito/evals/reports/2026-09-02-flow-simulation-current/feature-multitask-probe.py`
   - New real Git reproduction; no mocked Gate operations.
   - Evidence: `feature-multitask-probe.log`, reproducible script, and `feature-multitask-evidence.tar.gz` containing the complete synthetic repository, Git objects, worktree, events, package and controlled-check evidence.
   - Original persistent repository: `/tmp/cogito-feature-multitask-cs_7y950`.

## F-1 — P1: normal same-Slice sequential tasks become stuck in reviewing

Policy explicitly permits same-Slice tasks to complete in sequence (`references/execution-policy.md`, dispatch and isolation section). The package contract and scheduler accept this graph:

```
FS-1
  T-1 owns src/a.txt -> T-2 owns src/b.txt
```

Reproduction:

1. Initialize and synthetically approve one Feature Slice with these two dependent tasks.
2. T-1 leases the Slice worktree, changes only `src/a.txt`, commits H1, registers its valid implementer result, and completes.
3. T-2 leases the same worktree at H1, changes only `src/b.txt`, commits H2, registers its valid implementer result, and completes.
4. `implementation-complete` succeeds. A real controlled check asserts both final file values; evidence passes and `complete_verification` enters `reviewing`.
5. Submit T-1 reviewer result using its implementer range base..H1: rejected with `Agent Result commits are not bound to the leased worktree` because current worktree HEAD is H2.
6. Submit T-1 reviewer result using base..H2: rejected with `Agent Result exceeds its task path responsibility`, because the cumulative range includes T-2's `src/b.txt`.
7. T-2 review succeeds, but `review-approved` still rejects closure because T-1 has no admissible reviewer result. State remains `reviewing`.

Both rejected submissions leave event history unchanged. Actual output:

```
check passed: True
state after verification: reviewing
T-1 review using original task head REJECTED: Agent Result commits are not bound to the leased worktree events unchanged: True
T-1 review using latest Slice head REJECTED: Agent Result exceeds its task path responsibility events unchanged: True
review closure REJECTED: every completed implementation task requires a Gate-recorded independent Reviewer Result
final state: reviewing
```

Cause: `scripts/cogito_run_store.py:264` applies current-worktree HEAD equality to reviewer results, while `:287` applies task path ownership to the whole submitted base-to-head range. These requirements become incompatible for an earlier task after a later, differently scoped task advances the shared Slice branch. The required per-task review closure then blocks integration.

Suggested correction: model the reviewed task implementation range separately from the current Slice verification snapshot. Bind each reviewer to that task's recorded implementer base/head and identity, preserve ancestry/current verified-Slice consistency, and validate task ownership on the task-specific implementation range. Do not simply remove HEAD or path validation; preserve rejection of unrelated/unverified branch advancement and falsified task ownership. Add an end-to-end regression with at least two differently scoped, sequential tasks per Slice and finish integration/post-verification/finalization.

Control scenario: reran the same script with `--same-implementer`, assigning both T-1 and T-2 to the same `slice-worker` agent ID. Both reviewer attempts fail identically and closure remains blocked. This confirms the issue also affects one stable Worker per Slice, and is not caused by changing implementer identities. Evidence: `feature-multitask-same-worker.log`; repository `/tmp/cogito-feature-multitask-dnfs7tzc`, included in the archive.

Why existing tests missed this: Feature E2E has one task per Slice. Pure integration-rule tests have multiple tasks, but do not exercise the Git-based reviewer submission boundary.

## Limits

This run verifies runtime contracts, actual Git operations and controlled checks. It does not establish the semantic quality of actual agent reviews, a real approval dialogue, or every agent-behavior eval scenario. No product repair was attempted by this audit agent. The independent scenario intentionally stops at the demonstrated failure, and its failing flow must not be described as an accepted delivery.
