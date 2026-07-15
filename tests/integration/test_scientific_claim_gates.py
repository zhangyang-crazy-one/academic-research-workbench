from __future__ import annotations

import json
from pathlib import Path

from arw.evidence_access import EVIDENCE_ACCESS_SCHEMA_VERSION, EvidenceAccessDecision, evaluate_claim_capability
from arw.integrity import IntegrityReceipt


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/phase6/representative-run/experiment/provenance.json"


def _public_decision() -> EvidenceAccessDecision:
    return EvidenceAccessDecision.model_validate(
        {
            "schema_version": EVIDENCE_ACCESS_SCHEMA_VERSION,
            "decision_id": "decision.access-public",
            "evidence_id": "source.paper-001",
            "subject_sha256": "a" * 64,
            "evidence_sha256": "b" * 64,
            "source_manifest_sha256": ["c" * 64],
            "access_state": "publicly_verified",
            "license_status": "clear",
            "public_verification_receipt_sha256": "e" * 64,
            "accountable_actor_id": "operator.user",
            "accountable_role": "access_authority",
            "authority_sha256": "d" * 64,
            "rationale": "public source receipt is current",
            "scope": "source.paper-001",
            "created_at": "2026-07-15T10:00:00Z",
        }
    )


def _integrity(decision: EvidenceAccessDecision, *, valid_until: str = "2026-07-15T11:00:00Z") -> IntegrityReceipt:
    return IntegrityReceipt.model_validate(
        {
            "schema_version": "arw.integrity-receipt.v1",
            "receipt_id": "receipt.citation-001",
            "subject_kind": "source",
            "subject_id": decision.evidence_id,
            "subject_sha256": decision.subject_sha256,
            "input_sha256": [decision.evidence_sha256],
            "method_id": "integrity.sha256",
            "method_version": "1.0.0",
            "tool_identity": {
                "name": "arw-integrity",
                "version": "0.1.0",
                "build_sha256": "f" * 64,
            },
            "observed_at": "2026-07-15T10:00:00Z",
            "freshness_policy": {"valid_until": valid_until, "clock_skew_seconds": 30},
            "verdict": "PASS",
            "reason_codes": ["verified"],
            "reason_text": "subject and input digests matched",
            "source_manifest_sha256": list(decision.source_manifest_sha256),
            "created_by": "parent.runtime",
        }
    )


def test_citation_requires_fresh_digest_bound_lifecycle_receipt() -> None:
    decision = _public_decision()
    result = evaluate_claim_capability(
        "citation_verified",
        decision,
        integrity_receipt=_integrity(decision),
        now="2026-07-15T10:30:00Z",
    )
    assert result.status == "PASS"

    stale = evaluate_claim_capability(
        "citation_verified",
        decision,
        integrity_receipt=_integrity(decision, valid_until="2026-07-15T10:01:00Z"),
        now="2026-07-15T10:30:00Z",
    )
    assert stale.status == "BLOCKED"
    assert "freshness_expired" in stale.reason_codes


def test_imported_external_metrics_never_claim_reproduction() -> None:
    decision = _public_decision()
    provenance = json.loads(FIXTURE.read_text(encoding="utf-8"))
    result = evaluate_claim_capability(
        "experiment_reproduced",
        decision,
        provenance=provenance,
        qualification_receipts=None,
        now="2026-07-15T10:30:00Z",
    )
    assert result.status == "BLOCKED"
    assert "controlled_execution_adapter_disabled" in result.reason_codes


def test_audit_requires_all_receipts_and_no_technical_blockers() -> None:
    decision = _public_decision()
    blocked = evaluate_claim_capability("audit_complete", decision)
    assert blocked.status == "BLOCKED"
    assert "missing_run_replay_receipt" in blocked.reason_codes
    valid = evaluate_claim_capability(
        "audit_complete",
        decision,
        run_replay_receipt={"receipt_sha256": "1" * 64},
        passport_receipts=({"passport_sha256": "2" * 64},),
        graph_projection_receipt={"receipt_sha256": "3" * 64},
        test_receipts=({"receipt_sha256": "4" * 64},),
        benchmark_receipts=({"receipt_sha256": "5" * 64},),
        build_receipt={"receipt_sha256": "6" * 64},
    )
    assert valid.status == "PASS"

