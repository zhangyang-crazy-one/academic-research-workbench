"""Strict observational hook and bounded-continuation contract tests."""

from __future__ import annotations

import pytest

from arw.hook_contracts import (
    HOOK_STATUSES,
    ContinuationBudget,
    ContinuationContractError,
    ContinuationRequest,
    HookContractError,
    HookObservation,
    HookParityMatrix,
)


HOOK_DIGEST = "a" * 64
OBSERVATION_DIGEST = "b" * 64
AUTHORITY_DIGEST = "c" * 64


def _observation(
    *,
    status: str = "trusted_enabled",
    continuation: ContinuationRequest | None = None,
    continuation_count: int = 0,
) -> HookObservation:
    return HookObservation(
        schema_version="arw.hook-observation-contract.v1",
        hook_name="SubagentStop",
        command_id="command.review-001",
        target_id="attempt.review-001",
        hook_definition_sha256=HOOK_DIGEST,
        status=status,
        observation_kind="proposal_incomplete",
        observation_sha256=OBSERVATION_DIGEST,
        redacted_error_code=None,
        failure_reason=None,
        continuation_request=continuation,
        continuation_count=continuation_count,
        parity=HookParityMatrix.for_status(status, authority_digest=AUTHORITY_DIGEST),
    )


def test_p04_03_t03_hook_status_cannot_be_authority_input() -> None:
    observations = tuple(
        _observation(status=status)
        for status in HOOK_STATUSES
    )
    for observation in observations:
        assert all(control.parent_enforced for control in observation.parity.controls)
        assert observation.parity.authority_normalized_digest == AUTHORITY_DIGEST
        assert not hasattr(observation, "canonical_event")
        assert not hasattr(observation, "acceptance_decision")
        assert not hasattr(observation, "state_mutation_request")

    with pytest.raises(HookContractError, match="privilege|canonical_event"):
        HookObservation.from_wire(
            b'{"schema_version":"arw.hook-observation-contract.v1",'
            b'"canonical_event":{"event_type":"gate.evaluated"}}'
        )
    with pytest.raises(HookContractError, match="malformed|JSON"):
        HookObservation.from_wire(b"not-json")
    with pytest.raises(Exception):
        HookObservation.model_validate(
            {
                **_observation().model_dump(mode="json"),
                "observation_sha256": None,
            }
        )


def test_p04_03_t03_continuation_is_at_most_once_per_key() -> None:
    request = ContinuationRequest(
        schema_version="arw.hook-continuation.v1",
        owner="SubagentStop",
        target_id="attempt.review-001",
        idempotency_key="attempt.review-001.subagent-stop.repair",
        reason_code="proposal_incomplete",
    )
    observation = _observation(continuation=request, continuation_count=1)
    budget = ContinuationBudget.initial(
        owner="SubagentStop",
        target_id="attempt.review-001",
        idempotency_key=request.idempotency_key,
    )

    consumed = budget.admit(observation)
    assert consumed.used_count == 1
    with pytest.raises(ContinuationContractError, match="at most one|exhausted"):
        consumed.admit(observation)

    with pytest.raises(ContinuationContractError, match="owner|SubagentStop"):
        ContinuationBudget.initial(
            owner="Stop",
            target_id="deliverable.review-001",
            idempotency_key="deliverable.review-001.stop.parent",
        ).admit(observation)

    with pytest.raises(Exception):
        ContinuationRequest(
            schema_version="arw.hook-continuation.v1",
            owner="SubagentStop",
            target_id="attempt.review-001",
            idempotency_key="attempt.review-001.bad",
            reason_code="retry_assignment",
        )
