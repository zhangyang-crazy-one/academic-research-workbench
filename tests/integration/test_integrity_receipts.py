from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/phase6/representative-run/integrity/receipt.json"


def _receipt():
    from arw.integrity import seal_integrity_receipt

    return seal_integrity_receipt(json.loads(FIXTURE.read_text(encoding="utf-8")))


def test_publish_is_write_once_and_cold_replay_is_byte_identical(tmp_path: Path) -> None:
    from arw.integrity import load_integrity_receipt, publish_integrity_receipt

    receipt = _receipt()
    path = publish_integrity_receipt(tmp_path, receipt)
    assert path.read_bytes() == receipt.canonical_bytes()
    assert publish_integrity_receipt(tmp_path, receipt) == path
    replayed = load_integrity_receipt(tmp_path, receipt.receipt_sha256)
    assert replayed.model_dump(mode="json") == receipt.model_dump(mode="json")
    assert replayed.canonical_bytes() == path.read_bytes()


def test_publication_rejects_collision_and_symlink_store(tmp_path: Path) -> None:
    from arw.integrity import IntegrityReceiptError, publish_integrity_receipt

    receipt = _receipt()
    target = tmp_path / "integrity" / "receipts" / "sha256"
    target.mkdir(parents=True)
    (target / f"{receipt.receipt_sha256}.json").write_bytes(b"wrong immutable bytes")
    with pytest.raises(IntegrityReceiptError, match="collision|replacement"):
        publish_integrity_receipt(tmp_path, receipt)

    symlink_root = tmp_path / "symlink-root"
    symlink_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (symlink_root / "integrity").symlink_to(outside, target_is_directory=True)
    with pytest.raises(IntegrityReceiptError, match="symlink"):
        publish_integrity_receipt(symlink_root, receipt)


def test_subject_input_expiry_and_future_clock_fail_closed_without_mutating_receipt(
    tmp_path: Path,
) -> None:
    from arw.integrity import (
        evaluate_integrity_receipt,
        load_integrity_receipt,
        publish_integrity_receipt,
    )

    receipt = _receipt()
    publish_integrity_receipt(tmp_path, receipt)
    before = receipt.canonical_bytes()
    fresh = datetime(2026, 7, 15, 10, 30, tzinfo=UTC)
    assert evaluate_integrity_receipt(receipt, "a" * 64, ["b" * 64, "c" * 64], fresh).verdict == "PASS"
    changed_subject = evaluate_integrity_receipt(receipt, "f" * 64, ["b" * 64, "c" * 64], fresh)
    assert changed_subject.verdict == "FAIL"
    assert changed_subject.reason_codes == ("subject_digest_mismatch",)
    changed_input = evaluate_integrity_receipt(receipt, "a" * 64, ["b" * 64], fresh)
    assert changed_input.verdict == "FAIL"
    assert changed_input.reason_codes == ("input_digest_mismatch",)
    expired = evaluate_integrity_receipt(
        receipt,
        "a" * 64,
        ["b" * 64, "c" * 64],
        datetime(2026, 7, 15, 11, 1, tzinfo=UTC),
    )
    assert expired.verdict == "FAIL"
    assert expired.reason_codes == ("freshness_expired",)
    future = evaluate_integrity_receipt(
        receipt,
        "a" * 64,
        ["b" * 64, "c" * 64],
        datetime(2026, 7, 15, 9, 59, tzinfo=UTC),
    )
    assert future.verdict == "BLOCKED"
    assert future.reason_codes == ("future_timestamp",)
    assert receipt.canonical_bytes() == before
    assert load_integrity_receipt(tmp_path, receipt.receipt_sha256).canonical_bytes() == before


def test_tampered_file_is_not_revivable_by_evaluator_or_loader(tmp_path: Path) -> None:
    from arw.integrity import IntegrityReceiptError, load_integrity_receipt, publish_integrity_receipt

    receipt = _receipt()
    path = publish_integrity_receipt(tmp_path, receipt)
    path.write_bytes(path.read_bytes() + b"tamper")
    with pytest.raises(IntegrityReceiptError, match="address|invalid"):
        load_integrity_receipt(tmp_path, receipt.receipt_sha256)
