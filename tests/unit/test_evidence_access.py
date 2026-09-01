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
from arw.integrity import IntegrityReceipt, publish_integrity_receipt
from arw.kernel.state.orchestration_models import HumanAuthority


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


@pytest.mark.parametrize("field,value", [("source_uri", "https://example.invalid?api_key=secret"), ("rationale", "private /home/user/paper"), ("scope", "/private/research")])
def test_access_decision_redacts_secret_and_private_text(field: str, value: str) -> None:
    with pytest.raises((ValidationError, ValueError)):
        EvidenceAccessDecision.model_validate(_decision(**{field: value}))


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


def test_public_promotion_loads_fresh_bound_receipt_and_parent_authority(tmp_path: Path) -> None:
    first = EvidenceAccessDecision.model_validate(_decision(access_state="human_review_required", license_status="ambiguous"))
    authority = HumanAuthority(
        schema_version="arw.human-authority.v1",
        authority_id="authority.access-001",
        authenticated_actor_id="operator.user",
        accountable_role="access_authority",
        validated_by_actor_id="parent.runtime",
        allowed_decision_kinds=("verification",),
        allowed_gate_ids=("gate.access-001",),
        allowed_scopes=(first.scope,),
        authenticated_at="2026-07-15T10:00:00Z",
        expires_at="2026-07-15T12:00:00Z",
        evidence_sha256=(first.decision_sha256,),
    )
    receipt = IntegrityReceipt.model_validate(
        {
            "schema_version": "arw.integrity-receipt.v1",
            "receipt_id": "receipt.access-001",
            "subject_kind": "source",
            "subject_id": first.evidence_id,
            "subject_sha256": first.subject_sha256,
            "input_sha256": list(first.evidence_sha256),
            "method_id": "integrity.sha256",
            "method_version": "1.0.0",
            "tool_identity": {"name": "arw-integrity", "version": "0.1.0", "build_sha256": "f" * 64},
            "observed_at": "2026-07-15T10:00:00Z",
            "freshness_policy": {"valid_until": "2026-07-15T11:00:00Z", "clock_skew_seconds": 30},
            "verdict": "PASS",
            "reason_codes": ["verified"],
            "reason_text": "subject and input digests matched",
            "source_manifest_sha256": list(first.source_manifest_sha256),
            "created_by": "parent.runtime",
        }
    )
    publish_integrity_receipt(tmp_path, receipt)
    promoted = EvidenceAccessDecision.model_validate(
        _decision(
            decision_id="decision.access-003",
            access_state="publicly_verified",
            public_verification_receipt_sha256=receipt.receipt_sha256,
            decision_kind="verification",
            predecessor_sha256=first.decision_sha256,
            supersedes_decision_id=first.decision_id,
            authority_sha256=authority.authority_sha256,
            created_at="2026-07-15T10:01:00Z",
            accountable_actor_id=authority.authenticated_actor_id,
        )
    )
    validate_access_transition(first, promoted, root=tmp_path, parent_authority=authority, now="2026-07-15T10:30:00Z")

    forged = promoted.model_copy(update={"public_verification_receipt_sha256": "e" * 64})
    with pytest.raises(EvidenceAccessError):
        validate_access_transition(first, forged, root=tmp_path, parent_authority=authority, now="2026-07-15T10:30:00Z")
