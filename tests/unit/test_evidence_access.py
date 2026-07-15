from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from arw.evidence_access import (
    EVIDENCE_ACCESS_SCHEMA_VERSION,
    EvidenceAccessDecision,
    EvidenceAccessError,
    EvidenceAccessState,
    load_evidence_access_decision,
    publish_evidence_access_decision,
    validate_access_transition,
)


def _decision(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": EVIDENCE_ACCESS_SCHEMA_VERSION,
        "decision_id": "decision.access-001",
        "evidence_id": "source.paper-001",
        "subject_sha256": "a" * 64,
        "evidence_sha256": ["b" * 64],
        "source_manifest_sha256": ["c" * 64],
        "access_state": "locally_supplied",
        "license_status": "clear",
        "accountable_actor_id": "operator.user",
        "accountable_role": "access_authority",
        "authority_sha256": "d" * 64,
        "rationale": "local source is bounded but not publicly verified",
        "scope": "source.paper-001",
        "created_at": "2026-07-15T00:00:00Z",
    }
    value.update(updates)
    return value


def test_exact_five_access_states_and_canonical_hash() -> None:
    for state in (
        "publicly_verified",
        "locally_supplied",
        "restricted",
        "unavailable",
        "human_review_required",
    ):
        payload = _decision(access_state=state)
        if state == "publicly_verified":
            payload.update(
                license_status="clear", public_verification_receipt_sha256="e" * 64
            )
        if state in {"unavailable", "human_review_required"}:
            payload["license_status"] = "unavailable"
        decision = EvidenceAccessDecision.model_validate(payload)
        assert decision.access_state.value == state
        assert len(decision.decision_sha256) == 64

    with pytest.raises((ValidationError, ValueError)):
        EvidenceAccessDecision.model_validate(_decision(access_state="private_cache"))


def test_unresolved_license_cannot_be_public() -> None:
    with pytest.raises((ValidationError, ValueError)):
        EvidenceAccessDecision.model_validate(
            _decision(
                access_state="publicly_verified",
                license_status="ambiguous",
                public_verification_receipt_sha256="e" * 64,
            )
        )


def test_predecessor_and_supersession_are_append_only(tmp_path: Path) -> None:
    first = EvidenceAccessDecision.model_validate(_decision())
    publish_evidence_access_decision(tmp_path, first)
    successor_payload = _decision(
        decision_id="decision.access-002",
        access_state="human_review_required",
        license_status="ambiguous",
        decision_kind="correction",
        predecessor_sha256=first.decision_sha256,
        supersedes_decision_id=first.decision_id,
        created_at="2026-07-15T00:01:00Z",
    )
    successor = EvidenceAccessDecision.model_validate(successor_payload)
    validate_access_transition(first, successor)
    publish_evidence_access_decision(tmp_path, successor)
    assert load_evidence_access_decision(tmp_path, first.decision_sha256) == first
    assert load_evidence_access_decision(tmp_path, successor.decision_sha256) == successor

    forged = successor.model_copy(update={"predecessor_sha256": "f" * 64})
    with pytest.raises(EvidenceAccessError):
        validate_access_transition(first, forged)


def test_local_evidence_cannot_promote_without_fresh_receipt() -> None:
    first = EvidenceAccessDecision.model_validate(_decision())
    promoted_payload = _decision(
        decision_id="decision.access-003",
        access_state="publicly_verified",
        public_verification_receipt_sha256="e" * 64,
        decision_kind="verification",
        predecessor_sha256=first.decision_sha256,
        supersedes_decision_id=first.decision_id,
        created_at="2026-07-15T00:01:00Z",
    )
    promoted = EvidenceAccessDecision.model_validate(promoted_payload)
    with pytest.raises(EvidenceAccessError):
        validate_access_transition(first, promoted, public_verification_receipt_sha256="f" * 64)
