# Batch 3：結案正向模擬

Reading order: `cogito/SKILL.md` → `references/finalization.md` → `references/runtime-interface.md` → `references/execution-policy.md`. Only instructions/references were read; no code, Git history, prior reports, mutations to runs, or approvals.

## A — Feature finalization with a late Spec edit

The existing evidence cannot cover the proposed Spec edit. First assess whether the edit stays within the approved contract and permitted Spec path. Stop finalization; query Gate and follow an existing legal correction route, or record a block if no route is available. Contract changes require RP. Do not assume `finalizing` allows backward transitions.

Complete the legal Spec update in the appropriate product/task/correction commit before the new final verification. Rerun necessary controlled checks for changed HEAD/content/contract; obtain fresh applicable review and human closure through Gate. Then fetch `delivery-summary`, copy its JSON unchanged into Result, update Result/Graph, and make the final commit containing only this run’s canonical Result and Project Graph. Recheck the entire Start-to-final scope, not just content-tree equality. Register the actual commit with stable action ID; report accepted only after Gate confirmation. Put the final ID in the derived report, never inside Result or an amended self-referential commit.

Missing context/backtracking: the Spec diff and legal outgoing action are unspecified. Finalization routed me to Runtime Interface, then Execution Policy; neither authorizes an invented rollback.

## B — Maintenance, two tasks and one amendment

Create exactly one new commit after Start Gate HEAD, with that HEAD as its sole parent. Two completed tasks and an amendment do not imply three commits: verified product changes remain uncommitted until the single final commit atomically saves product content, Result, and Project Graph. Include all applicable `Cogito-Amendment: <ID>` trailers; preparation checkpoints precede Start and do not count against this limit.

Result’s amendment entry is `{id, base_commit, content_tree}`, matching its completion event; `base_commit` is Start HEAD. Do not use `commit_id` or embed the final commit ID. Fetch `delivery-summary` and copy its JSON unchanged; record final integration checks, reviews, risks and known history. Graph records final disposition and clears this run’s `active_run_id`.

Ensure the product tree still matches controlled evidence and all Start-to-final changes satisfy approved paths/exact control exceptions. Finalize with the actual commit ID and stable action ID; only Gate success establishes accepted. `report` adds the final ID and amendment commit IDs.

Missing context: actual events/evidence and human applicability cannot be independently confirmed in this synthetic scenario; `finalizing` presupposes applicable prior closure.

## C — Error after commit versus accepted with retained worktree

After a finalize error, stop and query Gate plus the existing commit to establish whether the event landed. If the commit exists but registration did not finish, replay `finalize` with that exact commit ID, original parameters and action ID. Do not create another commit, amend Result, or expect `resume` to discover/register the commit. If identity or evidence cannot be reconciled, preserve the scene and block where possible; an error alone does not establish blocked status.

If accepted already succeeded, cleanup retention does not undo acceptance. An ignored `.env` must retain the worktree; report the reason and preserve its data. After safely resolving the retention reason, replay the identical finalize request only to retry cleanup, without repeating acceptance or appending another finalization event. Already removed worktrees are skipped.

Never force removal, globally prune, delete branches/runtime history, or rewrite events/evidence/Result/report. Cleanup protects referenced Git objects under `refs/cogito/cleanup/<run-id>/` and retains its receipt in `cleanup.json`.

Missing context: the failed response alone cannot reveal event persistence; actual reconciliation is required. No additional reference backtracking was necessary beyond Runtime Interface recovery.
