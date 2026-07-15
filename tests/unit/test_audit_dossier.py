from __future__ import annotations

from types import SimpleNamespace

import pytest

from arw.audit_dossier import (
    AuditDossierManifest,
    assemble_audit_dossier,
    render_audit_dossier_json,
    render_audit_dossier_markdown,
    seal_audit_dossier,
)


RUN_ID = "run-00000000-0000-4000-8000-000000000031"


def _state() -> SimpleNamespace:
    return SimpleNamespace(run_id=RUN_ID, last_event_sha256="a" * 64, events=())


def test_canonical_manifest_and_views_are_byte_identical() -> None:
    dossier = assemble_audit_dossier(
        replay_state=_state(),
        run_manifest_sha256="b" * 64,
        generated_at="2026-07-16T00:00:00Z",
    )
    assert render_audit_dossier_json(dossier) == render_audit_dossier_json(dossier.model_dump(mode="json"))
    assert render_audit_dossier_markdown(dossier) == render_audit_dossier_markdown(dossier.model_dump(mode="json"))
    assert "non-authoritative" in render_audit_dossier_markdown(dossier).decode()
    assert dossier.release_qualification.verdict == "BLOCKED"
    assert {"SUP-04", "P04-09"} <= set(dossier.release_qualification.reason_codes)


def test_manifest_rejects_unknown_fields_unsorted_refs_and_digest_substitution() -> None:
    dossier = assemble_audit_dossier(
        replay_state=_state(),
        run_manifest_sha256="b" * 64,
        generated_at="2026-07-16T00:00:00Z",
    )
    value = dossier.model_dump(mode="json")
    value["unexpected"] = True
    with pytest.raises(Exception):
        AuditDossierManifest.model_validate(value)
    value = dossier.model_dump(mode="json")
    value["passport_sha256"] = ["f" * 64, "e" * 64]
    value.pop("dossier_sha256")
    with pytest.raises(Exception):
        seal_audit_dossier(value)
    value = dossier.model_dump(mode="json")
    value["dossier_sha256"] = "f" * 64
    with pytest.raises(Exception):
        seal_audit_dossier(value)


def test_claim_and_test_records_are_bounded_and_sorted() -> None:
    with pytest.raises(Exception):
        AuditDossierManifest.model_validate(
            {
                "schema_version": "arw.audit-dossier.v1",
                "dossier_id": "audit-dossier.current",
                "run_id": RUN_ID,
                "generated_at": "2026-07-16T00:00:00Z",
                "ledger_head_sha256": "a" * 64,
                "run_manifest_sha256": "b" * 64,
                "technical_qualification": {"verdict": "PASS"},
                "release_qualification": {"verdict": "BLOCKED"},
                "test_logs": [{"name": "z", "command_digest": "a" * 64, "result": "PASS", "stdout_sha256": "b" * 64, "stderr_sha256": "c" * 64}, {"name": "a", "command_digest": "a" * 64, "result": "PASS", "stdout_sha256": "b" * 64, "stderr_sha256": "c" * 64}],
            }
        )
