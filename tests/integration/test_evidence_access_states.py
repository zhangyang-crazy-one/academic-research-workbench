from __future__ import annotations

from arw.evidence_access import (
    EVIDENCE_ACCESS_SCHEMA_VERSION,
    EvidenceAccessDecision,
    EvidenceAccessState,
    evaluate_claim_capability,
)


def _decision(state: str, *, license_status: str = "clear", public: bool = False) -> EvidenceAccessDecision:
    value: dict[str, object] = {
        "schema_version": EVIDENCE_ACCESS_SCHEMA_VERSION,
        "decision_id": f"decision.access-{state}",
        "evidence_id": "source.paper-001",
        "subject_sha256": "a" * 64,
        "evidence_sha256": "b" * 64,
        "source_manifest_sha256": ["c" * 64],
        "access_state": state,
        "license_status": license_status,
        "accountable_actor_id": "operator.user",
        "accountable_role": "access_authority",
        "authority_sha256": "d" * 64,
        "rationale": "bounded access decision",
        "scope": "source.paper-001",
        "created_at": "2026-07-15T10:00:00Z",
    }
    if public:
        value["public_verification_receipt_sha256"] = "e" * 64
    return EvidenceAccessDecision.model_validate(value)


def test_every_access_state_is_visible_and_inaccessible_states_block_claims() -> None:
    for state in (
        "publicly_verified",
        "locally_supplied",
        "restricted",
        "unavailable",
        "human_review_required",
    ):
        license_status = "clear" if state in {"publicly_verified", "locally_supplied", "restricted"} else "ambiguous"
        decision = _decision(
            state,
            license_status=license_status,
            public=state == "publicly_verified",
        )
        result = evaluate_claim_capability("citation_verified", decision)
        assert result.status == "BLOCKED"
        assert result.human_review_required or "missing_fresh_integrity_receipt" in result.reason_codes
        assert result.scope == decision.scope
        assert decision.access_state in EvidenceAccessState


def test_caller_flags_and_projection_rows_do_not_upgrade_local_evidence() -> None:
    decision = _decision("locally_supplied")
    result = evaluate_claim_capability(
        "citation_verified",
        decision,
        claimed=True,
        markdown="citation verified",
        sqlite_row={"verified": True},
    )
    assert result.status == "BLOCKED"
    assert "evidence_access_requires_human_review" in result.reason_codes
    assert "caller_supplied_capability_flag" in result.reason_codes
