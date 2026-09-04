# RP isolated handoff and human acceptance simulation

Date: 2026-09-04

## Scenario

The simulation recreates an approved RP whose stop snapshot contains five
untracked files: the source Package, source Spec and Plan, plus two unrelated
FS-039 documents. The files remain byte-for-byte unchanged while the successor
reaches Start Gate. It also exercises a Gate-only commit made after
`handoff-started`, with an independent repair review and exact human approval.

## Observed workflow

1. The original delivery checkout and source Worker match the stop snapshot.
2. The Gate builds a detached temporary worktree and materializes only the
   successor's approved control manifest.
3. Start Gate passes in that isolated view. The five preserved files remain in
   the original checkout; the unrelated FS-039 files do not appear in the
   successor Worker or delivery scope.
4. Content, executable mode, index/stage state, and path drift are each rejected
   before handoff changes the Graph or appends `handoff-started`.
5. Crashes after isolation, validation, or the successor Start event recover
   with the same action ID and do not duplicate journal events.
6. A committed tool-only repair follows propose, independent review, and exact
   approval. RP remains `handing-off`; the approved product proposal, review,
   approval, and original handoff intent remain unchanged.
7. Resending the original handoff action completes the successor Start Gate and
   handoff. Mixed product commits, uncommitted repairs, pending review, existing
   transfers, and an already-started successor remain blocked.
8. The successor completes implementation, checks, independent review, and
   integration, then stops at `awaiting-human`. Only a fresh successor human
   approval moves it to `finalizing`; replaying handoff cannot supply approval.

## Results

- Focused acceptance simulation: 8 tests passed in 70.719 seconds.
- Complete regression suite: 595 tests passed in 484.131 seconds.
- Python compilation and `git diff --check`: passed.
- Static typing: not run because `mypy` is not installed in this environment
  (`python3: No module named mypy`).

The raw focused simulation output is stored in `acceptance.log`. The full-suite
summary is stored in `regression-summary.log`.
