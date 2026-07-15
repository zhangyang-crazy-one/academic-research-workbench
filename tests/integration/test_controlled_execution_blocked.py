from __future__ import annotations

from datetime import UTC, datetime

import pytest

from tests.integration.test_experiment_provenance import _provenance, _receipt


@pytest.mark.parametrize("mask", range(16))
def test_all_sixteen_gate_combinations_are_blocked_without_subprocess(monkeypatch, mask: int) -> None:
    from arw.experiment_provenance import QUALIFICATION_KINDS, evaluate_controlled_execution_policy

    called: list[object] = []
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: called.append(args))
    provenance = _provenance()
    receipts = {
        kind: _receipt(provenance, kind)
        for index, kind in enumerate(QUALIFICATION_KINDS)
        if mask & (1 << index)
    }
    decision = evaluate_controlled_execution_policy(
        provenance,
        receipts,
        now=datetime(2026, 7, 15, 10, 30, tzinfo=UTC),
    )
    assert decision.status == "BLOCKED"
    assert decision.subprocess_allowed is False
    assert "controlled_execution_adapter_disabled" in decision.reason_codes
    assert called == []
    if mask != 15:
        assert any(reason.startswith("missing_") for reason in decision.reason_codes)


def test_stale_mismatched_and_failed_receipts_are_not_qualification(monkeypatch) -> None:
    from arw.experiment_provenance import QUALIFICATION_KINDS, evaluate_controlled_execution_policy

    called: list[object] = []
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: called.append(args))
    provenance = _provenance()
    receipts = {
        kind: _receipt(provenance, kind, valid_until="2026-07-15T10:01:00Z")
        for kind in QUALIFICATION_KINDS
    }
    receipts["sandbox_approval"] = _receipt(
        provenance,
        "sandbox_approval",
        valid_until="2026-07-15T10:01:00Z",
        subject_sha256="9" * 64,
    )
    receipts["provenance_equivalence_probe"] = _receipt(
        provenance,
        "provenance_equivalence_probe",
        valid_until="2026-07-15T12:00:00Z",
        verdict="FAIL",
        probe_result="not_equivalent",
    )
    decision = evaluate_controlled_execution_policy(
        provenance,
        receipts,
        now=datetime(2026, 7, 15, 10, 30, tzinfo=UTC),
    )
    assert decision.status == "BLOCKED"
    assert "sandbox_approval_subject_mismatch" in decision.reason_codes
    assert "sandbox_approval_stale" in decision.reason_codes
    assert "provenance_equivalence_failed" in decision.reason_codes
    assert called == []


def test_all_four_fresh_receipts_still_do_not_enable_controlled_execution() -> None:
    from arw.experiment_provenance import QUALIFICATION_KINDS, evaluate_controlled_execution_policy

    provenance = _provenance()
    receipts = {kind: _receipt(provenance, kind) for kind in QUALIFICATION_KINDS}
    decision = evaluate_controlled_execution_policy(
        provenance,
        receipts,
        now=datetime(2026, 7, 15, 10, 30, tzinfo=UTC),
    )
    assert decision.status == "BLOCKED"
    assert decision.reason_codes == ("controlled_execution_adapter_disabled",)
    assert decision.replacement_evidence == ("future-qualified-execution-adapter",)
