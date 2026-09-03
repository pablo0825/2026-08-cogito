# Preapproval resimulation — 2026-09-02

Source HEAD: `df2ee65842e417260e6f73e841ac6e3d75085ae7`.
Started around 14:55 UTC; completed before 15:01 UTC (under 10 minutes). Source was read only; only isolated temporary repos/scripts/logs were created.

## Passing evidence

- `targeted-tests.log`: **21/21 passing**, 7.275 seconds. Covers Shared Understanding revisions, confirmation hash binding and CAS races; package revisions for feature/maintenance/documentation, stale publication rollback; JSON payload round trips/rejections.
- `verified/results.json`: **5 positive scenario groups passing**. All operations invoke the real `cogito_gate.py` subprocess CLI in fresh isolated repos:
  - Shared A → blocked → resume → B; missing/old confirmation hash rejected without changing events; B confirmed; package A rejected, B prepared.
  - Feature, maintenance, documentation package v1 → v2; old approval rejected without changing events; latest approved; published package hash matches v2; new preparation after approval rejected without changing events.
  - More than 10KB Chinese inline JSON and file JSON record the exact same payload. Invalid UTF-8 payload file, 20KB invalid string and large array are rejected with exit 2, JSON error, no traceback and no event changes.
- `races/results.json`: **9/9 independent real CLI concurrency probes passing** (three per package kind). `approve(v1)` raced with `prepare(v2)`. Final state/publication/event consistency held; when revision won, latest v2 could subsequently be approved. `race-probe.log` records which contender won. Deterministic injected interleavings additionally pass in the targeted tests.

## New reproducible issue (P2)

**Invalid UTF-8 package files escape structured CLI error handling.**

`prepare-package --package invalid-utf8.json` with bytes `b'{"reason":"\xff"}'` prints a Python `UnicodeDecodeError` traceback and exits **1**. Other invalid inputs and `--payload-json` return `{ "ok": false, "error": ... }` and exit **2**. CLI consumers expecting the documented structured failure cannot parse the response. Events remain unchanged, so no corruption observed.

Root cause: `cogito/scripts/cogito_gate.py:35-36`, `_read_object()` catches `OSError` and `json.JSONDecodeError`, but not `UnicodeDecodeError`. This loader is also shared by other file-based CLI arguments; only prepare-package was directly probed for this failure.

Reproduce against preserved fixture:

```sh
python3 /Users/pablo/Documents/project/2026-08-cogito/cogito/scripts/cogito_gate.py --repo /tmp/cogito-resimulation-20260902/preapproval/verified/bad-package prepare-package --run-id DEV-bad-package --package /tmp/cogito-resimulation-20260902/preapproval/verified/invalid-utf8.json --action-id bad-utf8
```

Evidence: final scenario in `verified/results.json`, corresponding full argv/stdout/stderr in `verified/commands.jsonl`, and `probe-verified.log`. Repeated independently in initial and verified probe runs.

## Reproduction scripts and caveat

`probe-verified.py` creates fresh fixtures under `verified/`; `race-probe.py` creates `races/`. To rerun wholesale, change their output root to a fresh directory (they intentionally do not overwrite existing repo fixtures).

The initial `probe.py` incorrectly asserted raw equality between canonical package JSON and source JSON: canonical publication intentionally adds `package_hash`. Those three initial assertion failures were probe defects, not product failures. The verified probe compares semantic package hashes and then checks postapproval freezing. Use `verified/results.json` for final classification; initial evidence retained for transparency.

No source fixes and no commits were made. Human confirmation fields use simulated inputs; this does not evaluate real human interactions or agent reasoning quality.
