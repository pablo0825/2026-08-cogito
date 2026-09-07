"""Pure, non-mutating contract for the persisted final Result JSON.

Git ancestry and event-ledger agreement belong to finalization, not this shape
check. Review summaries may omit outcome, as existing v3 writers do.
"""

from __future__ import annotations

from typing import Any

from cogito_common import CogitoError
from cogito_delivery_summary import validate_delivery_summary
from cogito_contract_fields import (
    CONTENT_HASH_RE, GIT_OBJECT_RE, RUN_ID_RE,
    require_array, require_boolean, require_choice, require_id, require_object,
    require_string, require_strings,
)


def validate_result(result: Any) -> None:
    require_object(
        result, "Result", "schema_version", "run_id", "status", "package_hash",
        "effective_contract_hash", "integration_commits", "slice_dispositions",
        "checks", "reviews", "amendments", "human_gate", "remaining_risks",
    )
    require_choice(result["schema_version"], "Result.schema_version", {"3.0"})
    require_string(result["run_id"], "Result.run_id", RUN_ID_RE)
    require_choice(result["status"], "Result.status", {"accepted"})
    if any(key in result for key in ("final_commit", "result_commit", "finalization_commit")):
        raise CogitoError("Result must not self-reference its containing commit")
    for field in ("package_hash", "effective_contract_hash"):
        require_string(result[field], f"Result.{field}", CONTENT_HASH_RE)
    for commit in require_array(result["integration_commits"], "Result.integration_commits"):
        require_string(commit, "integration commit", GIT_OBJECT_RE)
    dispositions = require_object(result["slice_dispositions"], "Result.slice_dispositions")
    for slice_id, disposition in dispositions.items():
        require_id(slice_id, "Result Slice id")
        require_choice(disposition, "Slice disposition", {"accepted", "cancelled", "superseded"})
    for check in require_array(result["checks"], "Result.checks"):
        require_object(check, "Result check", "id", "status", "evidence")
        require_id(check["id"], "Result check.id")
        require_choice(check["status"], "Result check.status", {"passed", "failed", "blocked"})
        require_string(check["evidence"], "Result check.evidence")
    for review in require_array(result["reviews"], "Result.reviews"):
        require_object(review, "Result review", "reviewer")
        require_string(review["reviewer"], "reviewer")
        if "outcome" in review:
            require_choice(review["outcome"], "review outcome", {"approved", "fixed", "blocked", "exempt"})
        if "implementer" in review:
            require_string(review["implementer"], "review implementer")
        if "commit_id" in review:
            require_string(review["commit_id"], "review commit_id", GIT_OBJECT_RE)
    for amendment in require_array(result["amendments"], "Result.amendments"):
        require_object(amendment, "Result amendment", "id")
        require_id(amendment["id"], "Result amendment.id")
        if "proposal_hash" in amendment:
            if set(amendment) != {"id", "proposal_hash"}:
                raise CogitoError("Result path amendment must only identify its reviewed proposal")
            require_string(amendment["proposal_hash"], "Result amendment.proposal_hash", CONTENT_HASH_RE)
        elif "commit_id" in amendment:
            if "base_commit" in amendment or "content_tree" in amendment:
                raise CogitoError("Result amendment cannot mix commit and working-tree completion")
            require_string(amendment["commit_id"], "Result amendment.commit_id", GIT_OBJECT_RE)
        else:
            require_object(amendment, "Result working-tree amendment", "base_commit", "content_tree")
            require_string(amendment["base_commit"], "Result amendment.base_commit", GIT_OBJECT_RE)
            require_string(amendment["content_tree"], "Result amendment.content_tree", GIT_OBJECT_RE)
    human = require_object(result["human_gate"], "Result.human_gate", "required", "outcome")
    require_boolean(human["required"], "Result.human_gate.required")
    require_choice(human["outcome"], "Result.human_gate.outcome", {"approved", "not-required"})
    require_strings(result["remaining_risks"], "Result.remaining_risks")
    if "delivery_summary" in result:
        validate_delivery_summary(result["delivery_summary"])
