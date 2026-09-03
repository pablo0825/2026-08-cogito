# Final resimulation regression report

## Version and execution

- HEAD: `a056941551c68f380078491809ff5ede5f48ea48`.
- Started: 2026-09-02 15:15:48 UTC.
- Darwin 25.5.0 arm64, Python 3.12.10.
- `python3 -m unittest discover -s cogito/tests -v`: **340 tests in 41.166s, OK, exit 0**.
- No source changes or commits by this workstream; before/after status remains `main...origin/main [ahead 48]` plus existing untracked `cogito/evals/reports/`.
- No mypy invocation. Passing expected-negative tests are not counted as bugs.

## Confirmed intermittent positive-test failure

`repeat_review_fix.py` repeated only the existing positive test `MaintenanceReviewFixTests.test_review_fix_records_snapshot_and_reverifies_added_task`, at most 30 iterations / 120 seconds. It wraps the original runtime call solely to copy the produced runner evidence before temporary-directory cleanup. The product behavior is not mocked.

- 30 iterations took **14.090 seconds**; 29 passed and iteration 30 failed on `first-check`.
- Iteration 30's check is read-only: it asserts `note.txt` stripped text equals `after`.
- The process exited **0**, had empty stderr, did not time out or exceed output limits, but runner set `passed=false` because `worktree_changed_during_check=true`.
- Failed repo, authoritative events and runner evidence are preserved under `review-fix-repeat/30/failed-repo-first-check/`; standalone evidence and test traceback are in the parent directory.
- The original file contains `after\n\n`, while baseline contains `before\n`; both are 7 bytes.

### Proven snapshot inconsistency

The evidence stores the full post-binding and pre-binding hash. `analyze_failed_binding.py` enumerates already existing Git trees, reconstructs candidate pre-bindings and verifies the original hash exactly. There is one matching candidate:

| Field | Pre-check | Post-check |
| --- | --- | --- |
| content_tree | `8fdc2665d7718a8a04ff79f73df3514c35ff2753` | `6f507e4bb4771fb977119478e7b79a91413a401c` |
| note.txt in tree | `after\n\n` (correct) | `before\n` (stale baseline) |
| tracked_diff_sha256 | `8c84aff73d1ce79af6fffdc04dbf81d5d9d6e0d6675f71ec56c0b09346b56086` | identical |
| HEAD, HEAD tree, untracked files and hashes | unchanged | unchanged |

Only `content_tree` changed. Thus the failure is a confirmed content snapshot inconsistency; the check itself succeeded, and the retained working file agrees with the pre-check tree. No product fix is included, and no false acceptance has been demonstrated.

### Minimal reproduction and timestamp control

`reproduce_racy_snapshot.py` creates one small real Git repo, commits `before\n`, writes the same-length `after\n\n` in the same second, then waits until the next second before calling the unmodified `working_tree_content_tree()`. Original-index `git diff HEAD` correctly reports the edit; the product snapshot incorrectly contains `before\n`. This reproduced on the first attempt, independently of the review-fix loop.

`compare_index_timestamp.py` uses that retained repo and repeats only the index-copy/stage/write-tree operations with one difference: it restores the copied index modification timestamp to the original index's timestamp using `os.utime`. The resulting tree correctly contains `after\n\n`. These controls support the mechanism: `shutil.copyfile` gives the copied index a new mtime, losing Git's protection for an equal-size file changed within the index timestamp's second; preserving that timestamp makes Git detect the change. The unchanged source is `cogito/scripts/cogito_evidence_binding.py:working_tree_content_tree`.

Complete outputs and timestamps are in `racy-snapshot-reproduction.json`; the minimal repo is retained at `racy-index-su0p8bhv/`. These are a minimal snapshot experiment and timestamp control, not additional iterations of the 30-run review-fix probe.

Evidence: `review-fix-repeat/30/first-check.json`, `binding-analysis.json`, `unittest.log`, `failed-repo-first-check/`. All successful iteration evidence is also retained. Reproduction commands: run `python3 repeat_review_fix.py` from anywhere (paths are explicit), then `python3 analyze_failed_binding.py` to analyze the captured iteration 30. The repeat script is intentionally timing-sensitive; it need not fail on every run. Copy existing evidence before rerunning if preserving this exact failure.

## Agent eval coverage audit

The 14 records in `cogito/evals/evals.json` are natural-language Agent behavior scenarios. **They were inspected, not executed or scored as 14 successful evals.** The table lists related runtime coverage exercised by the full test suite, not a claim that the behavior scenario passed.

| Eval | Related exercised coverage | Remaining limitation |
| --- | --- | --- |
| 1 ordinary request | None directly | Whether an Agent avoids starting Cogito without invocation is untested. |
| 2 shared confirmation | `test_runtime_contract.py`, `test_shared_revisions.py` | Human wording interpretation and spontaneous preparation behavior untested. |
| 3 package approval | Gate CLI, approval publication/recovery, package revisions | Genuine approval identity and avoiding unnecessary conversational approvals untested. |
| 4 technical correction | Maintenance correction E2E, amendment contracts/budgets | Agent classification of a defect as contract-preserving untested. |
| 5 semantic conflict | Amendment contract cannot widen paths/acceptance/dependencies | Recognizing “5 attempts → 3 attempts” as behavior change needs Agent judgment; runtime does not infer semantics. |
| 6 three-worker DAG | Runtime scheduler and cross-slice feature E2E, Gate CLI capacity | Actual simultaneous independent Agent scheduling is not an Agent eval here. |
| 7 independent review | Review identity/budget rules and review-fix paths | Reviewer effectiveness is untested; the positive Maintenance review-fix path has the intermittent snapshot failure above. |
| 8 persistent retry budget | Event replay, projection/counters, blocked resume tests | Natural-language interrupted-session orchestration untested. |
| 9 controlled runner | Shell-free argv, timeout, cwd, evidence bindings, process termination | Runtime exercised; Agent interpretation/reporting of failed evidence untested. |
| 10 automatic finalization | Feature E2E and staged/ordinary Maintenance accepted paths | Genuine agent decision/reporting and real external reviewer behavior untested. |
| 11 frozen human gate | Frozen predicate cannot be disabled; finalization requires approval event | Eval expectation conflicts with workflow ordering; see below. |
| 12 lazy legacy adoption | Contract/source shapes only indirectly | No real legacy project adoption simulation, document preservation audit or Agent migration decision test. |
| 13 maintenance mini package | Same engine, mini guards, staged path scope, one-commit finalization | Coordinator semantic-equivalence judgment not proven by guard booleans or checks. |
| 14 crash window idempotency | Action replay input binding and runner evidence publication recovery | Related tests do not establish full Agent-driven integrate-commit-before-event crash recovery; no claim of automatic trailer recovery. |

### Known Eval 11 contradiction

Eval 11 expects “Does not merge before approval.” The committed workflow transitions `integrating -> post-integration-verification -> awaiting-human`, i.e. integration happens before the final Human Gate. This order is also documented in `cogito/SKILL.md` lines 36–40 and encoded in `cogito/workflows/cogito-v3.json` lines 32 and 35. The eval wording must distinguish final acceptance from integration, or the intended workflow must be changed; this workstream does neither.

## Handoff

This workstream is complete within the 8-minute handoff threshold (about 5 minutes). Main suite is green but the 30-run positive probe gives a real intermittent issue that must not be hidden by the green suite. A minimal timestamp control supports the root cause; a future fix should be independently reviewed and regression-tested. No more than 30 review-fix iterations were run here.
