#!/usr/bin/env python3
"""Stable public facade for deterministic Cogito 3.0 runtime primitives."""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from cogito_common import (
    ID_RE,
    CogitoError,
    atomic_write_json,
    canonical_json,
    hash_json,
    load_json,
)
from cogito_contracts import (
    effective_contract_hash,
    materialize_contract,
    package_hash,
    validate_agent_result,
    validate_amendment,
    validate_package,
    validate_project_policy,
)
from cogito_events import append_event, read_events
from cogito_evidence_contract import validate_check_evidence
from cogito_projection import reduce_events
from cogito_project_graph import render_project_graph_mermaid, validate_project_graph
from cogito_result_contract import validate_result
from cogito_run_store import RunStore
from cogito_scheduler import ready_tasks
from cogito_workflow import (
    DEFAULT_WORKFLOW,
    load_workflow,
    render_workflow_mermaid,
    validate_transition,
)

ROOT = SCRIPT_DIR.parent
# Retain the legacy direct-import alias for external facade consumers.
_load_json = load_json

__all__ = [
    "ID_RE",
    "CogitoError",
    "DEFAULT_WORKFLOW",
    "ROOT",
    "RunStore",
    "append_event",
    "atomic_write_json",
    "canonical_json",
    "effective_contract_hash",
    "hash_json",
    "load_workflow",
    "materialize_contract",
    "package_hash",
    "read_events",
    "ready_tasks",
    "reduce_events",
    "render_project_graph_mermaid",
    "render_workflow_mermaid",
    "validate_agent_result",
    "validate_amendment",
    "validate_check_evidence",
    "validate_package",
    "validate_project_graph",
    "validate_project_policy",
    "validate_result",
    "validate_transition",
]
