# Preapproval state-transition audit

Date: 2026-09-03. Scope: public CLI of current working copy, real disposable Git repository, Feature Package prepared but never approved; no product files or live run modified. No applicable AGENTS.md was found in repository/ancestor lookup. Completed within the assigned 8-minute target.

## Result

The reported missing return path exists. A run in `awaiting-package-approval` cannot record a new Shared Understanding, reconfirm one, or complete a new Boundary analysis. `block` followed by the dedicated `resume` Gate restores `awaiting-package-approval`, with the same candidate hash. The recently implemented independent RP lifecycle does not cover this case: its begin operation requires an approved source Package.

## Reproduction

Run from repository root:

```sh
python3 cogito/evals/reports/2026-09-03-preapproval-audit/transitions-probe.py
```

The probe uses the existing Feature fixture to pass init → shared-understanding-ready → shared-understanding-confirmed → boundary-complete → prepare-package. It invokes the real gate CLI for each following check and asserts observed status/ledger effects. Full commands, return codes, stdout and stderr are in `transitions-results.json`.

| Check | Result |
|---|---|
| Submit new shared-understanding-ready | Exit 2, event not legal from awaiting-package-approval |
| Submit shared-understanding-confirmed | Exit 2, event not legal from awaiting-package-approval |
| Submit boundary-complete | Exit 2, event not legal from awaiting-package-approval |
| Submit replan as ordinary workflow event | Exit 2, event not legal from awaiting-package-approval |
| replan begin with unapproved source and fresh successor ID | Exit 2: run has no approved Package; no RP event journal created |
| block | Succeeds; blocked_from = awaiting-package-approval |
| Submit generic resume with target preparing | Exit 2: resume requires its dedicated Gate operation |
| Dedicated resume | Succeeds; state = awaiting-package-approval; candidate hash unchanged |
| init same run ID | Exit 2: run already exists |
| Explicitly authorized cancel, then init different run ID | Succeeds; old run cancelled, new run preparing |
| New run shared-understanding-ready | Succeeds; new run awaiting-shared-confirmation; old ledger unchanged |

Every rejected operation was additionally checked to preserve the source event journal byte-for-byte. New independent run creation likewise preserved the old cancelled journal.

## Code evidence

- `cogito/workflows/cogito-v3.json:13-21`: preparation flows forward; awaiting-package-approval has Package candidate self-revisions and approval, but no transition to preparing, awaiting-shared-confirmation, or boundary-analysis.
- `cogito/scripts/cogito_workflow.py:81-98`: rejects events lacking a matching transition; terminal states cannot transition.
- `cogito/scripts/cogito_run_store.py:869-879`: dedicated resume derives its target from `blocked_from`; callers cannot choose it.
- `cogito/scripts/cogito_projection.py:188-192`: initial block preserves the actual preceding stage; additional blocks do not replace that origin.
- `cogito/scripts/cogito_replan_store.py:75-88`: RP begin reads `source.approved_package()` before creating its first RP event.
- `cogito/scripts/cogito_run_store.py:191-202`: approved Package retrieval rejects unapproved source with the exact observed message.
- `cogito/scripts/cogito_run_store.py:220-228`: Package candidate changes must bind to the already-recorded Shared Understanding hash and exact Boundary result. This does not provide a way to re-record either upstream input.

## Qualification

This is not a claim that the project can never proceed: explicit cancellation followed by a separately initialized run is possible and was tested. That is manual restart, not a first-class preapproval revision/lineage/invalidation/recovery operation. It must not be represented as the desired built-in revision flow. This probe did not modify source and did not attempt to inject ledger events or edit caches as a workaround.
