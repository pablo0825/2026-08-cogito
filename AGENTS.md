# Repository Guidelines

## Project Scope

Cogito is a Codex skill for Gate-managed multi-agent software development. Read the current version from `cogito/VERSION`; the 3.x workflow filename remains `cogito-v3.json`. This contributor guide uses English. Cogito project documents use Chinese, with English IDs, paths, APIs, commands, and state values.

This file governs maintenance of this repository. Activate or resume `cogito/SKILL.md` only when the user explicitly invokes `$cogito` or directly answers the preceding unresolved Cogito question or approval in the same active run. Ordinary code and documentation maintenance does not automatically create a run. During Cogito execution, load references as directed by `next_action`, rather than preloading every operating document.

## Project Structure and Sources of Truth

Implementation lives under `cogito/`:

- `SKILL.md`, `agents/openai.yaml`, and `VERSION`: invocation conditions, agent policies, skill metadata, and version.
- `scripts/cogito_gate.py`: CLI entry point; `cogito_runtime.py`, `cogito_run_store.py`, and lifecycle modules handle execution and storage.
- `scripts/cogito_contracts.py` and `cogito_*_contract.py`: Python executable contracts, the sole authority for data validation. Do not maintain parallel handwritten JSON schemas.
- `scripts/cogito_*_rules.py`, `cogito_projection.py`, and `cogito_runner_evidence.py`: pure decisions, event projection, and evidence assembly. `cogito_ports.py` defines adapter interfaces; dedicated modules handle Git, event storage, and subprocess operations.
- `scripts/cogito_state_types.py` and `cogito_event_types.py`: internal state and event types, which do not replace runtime validation.
- `workflows/cogito-v3.json`: legal states, transitions, guards, and retry limits.
- `references/`: operating procedures and templates, routed from `SKILL.md`. [Runtime internals](cogito/references/runtime-internals.md) explains runner and evidence implementation details for maintainers.
- `tests/`: standard-library `unittest` tests; `tests/typing/` holds static type examples, and `mypy.ini` defines the checked scope.
- `evals/reports/`: recorded simulations, acceptance exercises, and test reports. Some reports include runnable scripts; interpret each result within its recorded scope.
- `RP-SUBTRACTIVE-REDESIGN.md`: phased design and implementation history, not an active runtime contract or authorization to implement deferred phases.

For target-project artifact locations and operating rules, use [SKILL.md](cogito/SKILL.md). Repository maintenance follows this guide; reading the skill as source material does not activate it.

## Development Commands

Run commands from the repository root. Python scripts execute directly; no separate build step is configured.

- `python3 cogito/scripts/cogito_gate.py --help`: inspect the CLI; use subcommand help for arguments, such as `replan --help`.
- `python3 -m unittest discover -s cogito/tests -p 'test_human*.py' -v`: focused test example; adjust the pattern to the change.
- `python3 -m unittest discover -s cogito/tests -v`: full regression suite, subject to the testing scope below.
- `python3 -m mypy --config-file cogito/mypy.ini`: check configured core modules and type examples with mypy 1.20.2, targeting Python 3.10. mypy is a development tool, not a runtime dependency.

## Testing Scope and Compatibility

Run tests covering changed behavior and its affected dependencies, contracts, and recovery paths. Do not run unrelated tests or default to the full suite. Run the full suite only when the impact spans the system, an applicable delivery requirement mandates it, or the user requests it. Briefly explain test selection and report checks not run. After relevant checks pass, expand or repeat testing only when new changes, failures, or unresolved concerns justify it.

For Cogito Atomic Tasks, follow the stage-commit policy: run targeted checks locally and leave full regression to CI. Do not assume CI has run or passed. For documentation-only maintenance, verify content, paths, commands, and the diff; run relevant behavioral tests when executable behavior changes.

Name test files `test_*.py` and methods `test_*`. Cover normal behavior, malformed input, supported historical data, and relevant failure and recovery paths. There is no numeric coverage threshold. Changes to events or contracts should check projections, hashes, action replay, and related CLI or end-to-end behavior.

Git-backed tests must inherit `cogito_test_support.GitTestCase` and initialize repositories with `init_repo()`. Call `super().setUp()` when overriding setup so personal Git configuration, signing, hooks, and environment variables remain isolated.

Preserve explicitly supported compatibility. Do not restore retired RP Start or snapshot formats as part of refactoring. Retain historical records without fabricating approvals or evidence. For RP changes, consult current code, tests, and the design document's phase status.

Report automated tests, skill format validation, and agent behavioral evaluations separately. Scenario definitions are not passing results, and historical reports do not validate the current change. Clearly identify checks not run or unavailable.

## Sub-agent Delegation

The user authorizes sub-agent assistance for analysis, evaluation, simulation, and proposal revision without repeated confirmation. Use it when bounded, independent subtasks or independent review are likely to improve quality. Simple tasks do not require delegation.

The primary agent must verify findings, resolve disagreements, and own the final result. Delegation does not replace required tests or Gate review evidence.

## Coding and Architecture

Use four-space indentation, `snake_case` functions and variables, `PascalCase` classes, and `UPPER_CASE` constants. Follow neighboring imports, type annotations, and docstrings. No shared formatter or linter configuration is checked in.

Separate pure validation and decisions from filesystem, Git, and process operations. Pure entry points explicitly receive workflow or limits; adapters handle I/O. Python validators remain the contract authority, and internal type declarations do not replace runtime checks.

Preserve approved JSON and hashes, append-only events and amendments, immutable evidence, and user staging. Validation must not coerce, populate, sort, or strip input data; preserve each contract's defaults and unknown-field policy. When changing runtime behavior, consult its owning procedure and related tests rather than duplicating detailed workflow rules here.

## Maintaining Skill Documentation

Give each rule one complete explanation in its owning procedure. Other locations may retain a short reminder and a direct link when needed for safe local understanding. Place prerequisites before actions, keep each normal procedure in execution order, and separate conditional exceptions and maintainer internals from the main path.

Make one bounded documentation change at a time. For changes affecting workflow instructions, run relevant checks and a focused reading simulation before proceeding; distinguish synthetic agent decisions from actual Gate execution and user acceptance. Preserve operating semantics unless the user explicitly requests a behavior change.

## Versioning

Update `cogito/VERSION` once per completed delivery that fixes behavior or adds functionality, after relevant validation and before handoff. Increment PATCH for backward-compatible fixes, MINOR for backward-compatible features, and MAJOR for incompatible public interface or contract changes. Reset lower components when incrementing MINOR or MAJOR, and use the highest applicable level for mixed changes.

Do not bump versions for discussion, unfinished work, or changes limited to documentation, tests, or refactoring that preserve behavior. Skill instruction changes that alter behavior count as behavioral changes. Do not bump again for intermediate corrections within the same delivery. A version bump does not authorize tagging or publishing.

## Commits and Pull Requests

Use Conventional Commits, such as `feat(cogito): ...`, `fix(cogito): ...`, `docs(cogito): ...`, `test(cogito): ...`, and `chore(cogito): ...`, with concise summaries describing the concrete change.

PRs should explain the problem, resulting behavior, related issues, and actual validation results. Update affected references and skill documentation when changing CLI, workflow, or contract behavior, and describe compatibility implications for stored events, contracts, and recovery paths. Follow the versioning policy above; do not change version mentions only in prose.
