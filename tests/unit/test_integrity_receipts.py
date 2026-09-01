from __future__ import annotations

from datetime import UTC, datetime

import pytest


def _payload() -> dict[str, object]:
    return {
        "schema_version": "arw.integrity-receipt.v1",
        "receipt_id": "receipt.integrity-001",
        "subject_kind": "artifact",
        "subject_id": "artifact.result-001",
        "subject_sha256": "a" * 64,
        "input_sha256": ["b" * 64, "c" * 64],
        "method_id": "integrity.sha256",
        "method_version": "1.0.0",
        "tool_identity": {
            "name": "arw-integrity",
            "version": "0.1.0",
            "build_sha256": "d" * 64,
        },
        "observed_at": "2026-07-15T10:00:00Z",
        "freshness_policy": {
            "valid_until": "2026-07-15T11:00:00Z",
            "clock_skew_seconds": 30,
        },
        "verdict": "PASS",
        "reason_codes": ["verified"],
        "reason_text": "subject and inputs matched",
        "source_manifest_sha256": ["e" * 64],
        "created_by": "parent.runtime",
    }


def test_seal_recomputes_receipt_hash_and_rejects_supplied_hash() -> None:
    from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
    from arw.integrity import IntegrityReceipt, seal_integrity_receipt

    receipt = seal_integrity_receipt(_payload())
    unsigned = receipt.model_dump(mode="json")
    unsigned.pop("receipt_sha256")
    assert receipt.receipt_sha256 == sha256_hex(canonical_json_bytes(unsigned))
    with pytest.raises(ValueError, match="receipt_sha256"):
        seal_integrity_receipt({**_payload(), "receipt_sha256": "f" * 64})
    assert isinstance(receipt, IntegrityReceipt)


def test_receipt_rejects_invalid_timestamp_and_skew_bounds() -> None:
    from arw.integrity import IntegrityReceipt

    with pytest.raises(ValueError):
        IntegrityReceipt.model_validate({**_payload(), "observed_at": "not-a-time"})
    with pytest.raises(ValueError):
        IntegrityReceipt.model_validate(
            {
                **_payload(),
                "freshness_policy": {"valid_until": "2026-07-15T11:00:00Z", "clock_skew_seconds": 301},
            }
        )


def test_evaluate_integrity_receipt_is_pure_and_fail_closed() -> None:
    from arw.integrity import IntegrityEvaluation, evaluate_integrity_receipt, seal_integrity_receipt

    receipt = seal_integrity_receipt(_payload())
    now = datetime(2026, 7, 15, 10, 30, tzinfo=UTC)
    result = evaluate_integrity_receipt(receipt, "a" * 64, ["b" * 64, "c" * 64], now)
    assert isinstance(result, IntegrityEvaluation)
    assert result.verdict == "PASS"
    assert result.reason_codes == ()
    assert evaluate_integrity_receipt(receipt, "f" * 64, ["b" * 64, "c" * 64], now).reason_codes == (
        "subject_digest_mismatch",
    )
    assert evaluate_integrity_receipt(receipt, "a" * 64, ["b" * 64], now).reason_codes == (
        "input_digest_mismatch",
    )
    assert evaluate_integrity_receipt(
        receipt,
        "a" * 64,
        ["b" * 64, "c" * 64],
        datetime(2026, 7, 15, 11, 1, tzinfo=UTC),
    ).reason_codes == ("freshness_expired",)
    assert evaluate_integrity_receipt(
        receipt,
        "a" * 64,
        ["b" * 64, "c" * 64],
        datetime(2026, 7, 15, 9, 59, tzinfo=UTC),
    ).reason_codes == ("future_timestamp",)
