from __future__ import annotations

from arw.kernel.artifacts.evidence_access import evaluate_claim_capability


def test_audit_blocker_scope_is_explicit_and_graph_loss_is_not_a_pass() -> None:
    blocked = evaluate_claim_capability(
        "audit_complete",
        {
            "schema_version": "arw.evidence-access-decision.v1",
            "decision_id": "decision.audit-access",
            "evidence_id": "run.audit-001",
            "subject_sha256": "a" * 64,
            "evidence_sha256": ["b" * 64],
            "source_manifest_sha256": ["c" * 64],
            "access_state": "publicly_verified",
            "license_status": "clear",
            "public_verification_receipt_sha256": "e" * 64,
            "accountable_actor_id": "operator.user",
            "accountable_role": "access_authority",
            "authority_sha256": "d" * 64,
            "rationale": "run audit evidence",
            "scope": "run.audit-001",
            "created_at": "2026-07-15T10:00:00Z",
        },
        run_replay_receipt={"receipt_sha256": "1" * 64},
        passport_receipts=({"passport_sha256": "2" * 64},),
        graph_projection_receipt=None,
        test_receipts=({"receipt_sha256": "4" * 64},),
        benchmark_receipts=({"receipt_sha256": "5" * 64},),
        build_receipt={"receipt_sha256": "6" * 64},
    )
    assert blocked.status == "BLOCKED"
    assert "missing_graph_projection_receipt" in blocked.reason_codes
    assert blocked.replacement_evidence == ("complete-audit-dossier-evidence",)
