# Repository Guidelines

## Project Structure & Module Organization

Cogito 3.0 is a Codex skill for Gate-managed software development. Its implementation lives under `cogito/`:

- `scripts/`: Python CLI, runtime, contract validators, event projections, and controlled runner; modules use the `cogito_` prefix.
- `tests/`: unit, integration, and end-to-end regression tests; `tests/typing/` holds static type examples.
- `workflows/cogito-v3.json`: states, transitions, guards, and retry limits.
- `references/`: operating rules and Markdown templates.
- `SKILL.md`, `agents/openai.yaml`, and `VERSION`: skill instructions, agent metadata, and version.
- `evals/`: behavioral scenarios, fixtures, and recorded evaluation reports.

## Build, Test, and Development Commands

Run commands from the repository root. The scripts run directly; no separate build step is configured.

- `python3 cogito/scripts/cogito_gate.py --help`: inspect the Gate CLI and available operations.
- `python3 -m unittest discover -s cogito/tests -v`: run the regression suite.
- `python3 -m unittest discover -s cogito/tests -p 'test_human*.py' -v`: run focused human-interaction tests; adjust the pattern for your change.
- `python3 -m mypy --config-file cogito/mypy.ini`: check configured core modules and type examples. Use mypy 1.20.2; the configuration targets Python 3.10.

## Coding Style & Naming Conventions

Use four-space indentation, `snake_case` functions and variables, `PascalCase` classes, and `UPPER_CASE` constants. Follow neighboring modules for imports, type annotations, and docstrings. No formatter or linter configuration is checked in.

Keep pure validation and decision rules separate from filesystem, Git, and process operations. Python validators are the contract authority; avoid duplicating rules in handwritten JSON schemas. Preserve approved JSON, hashes, and immutable evidence when changing validation or projections.

## Testing Guidelines

Use standard-library `unittest`, naming files `test_*.py` and methods `test_*`. Cover changed behavior, malformed input, compatibility, and relevant recovery paths. No numeric coverage threshold is configured.

Git-backed tests should inherit `cogito_test_support.GitTestCase`, initialize repositories with `init_repo()`, and call `super().setUp()` when overriding setup. Report automated tests and behavioral evaluations separately; scenario definitions alone are not passing results.

## Commit & Pull Request Guidelines

Follow the observed Conventional Commit style: `feat: ...`, `fix: ...`, or `docs(cogito): ...`, using concise imperative summaries.

PRs should describe the problem, resulting behavior, relevant issue links, and validation performed or unavailable. Update affected references when changing CLI or workflow behavior, and explain compatibility implications for stored events and contracts.
