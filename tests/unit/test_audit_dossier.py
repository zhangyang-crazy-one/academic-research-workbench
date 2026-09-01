from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from arw.audit_dossier import (
    AuditDossierError,
    AuditDossierManifest,
    assemble_audit_dossier,
    load_audit_dossier,
    publish_audit_dossier,
    render_audit_dossier_json,
    render_audit_dossier_markdown,
    seal_audit_dossier,
)
from arw.journal import ReplayState


RUN_ID = "run-00000000-0000-4000-8000-000000000031"


def _state() -> ReplayState:
    return ReplayState(run_id=RUN_ID, revision=0, last_event_sha256="a" * 64, event_count=0, event_ids=frozenset(), command_ids=frozenset(), events=(), validated=True)


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


def test_dossier_rejects_forged_pass_claims_and_unvalidated_replay() -> None:
    with pytest.raises(AuditDossierError, match="validated canonical replay"):
        assemble_audit_dossier(
            replay_state=object(),
            run_manifest_sha256="b" * 64,
            generated_at="2026-07-16T00:00:00Z",
        )
    with pytest.raises(AuditDossierError, match="validated canonical replay"):
        assemble_audit_dossier(
            replay_state=ReplayState(run_id=RUN_ID, revision=0, last_event_sha256="a" * 64, event_count=0, event_ids=frozenset(), command_ids=frozenset()),
            run_manifest_sha256="b" * 64,
            generated_at="2026-07-16T00:00:00Z",
        )
    with pytest.raises(AuditDossierError, match="caller-supplied claim PASS"):
        assemble_audit_dossier(
            replay_state=_state(),
            run_manifest_sha256="b" * 64,
            generated_at="2026-07-16T00:00:00Z",
            claim_capabilities=({"capability": "audit_complete", "verdict": "PASS"},),
        )


def test_empty_replayed_dossier_is_technically_blocked() -> None:
    dossier = assemble_audit_dossier(
        replay_state=_state(),
        run_manifest_sha256="b" * 64,
        generated_at="2026-07-16T00:00:00Z",
    )
    assert dossier.technical_qualification.verdict == "BLOCKED"
    assert any(item.code == "missing_claim_lifecycle_evidence" for item in dossier.blockers)


def test_direct_technical_pass_cannot_be_sealed_or_published(tmp_path) -> None:
    dossier = assemble_audit_dossier(
        replay_state=_state(),
        run_manifest_sha256="b" * 64,
        generated_at="2026-07-16T00:00:00Z",
    )
    forged = dossier.model_dump(mode="json")
    forged["technical_qualification"] = {
        "verdict": "PASS",
        "reason_codes": [],
        "evidence_sha256": ["c" * 64],
        "rationale": "caller supplied",
    }
    forged.pop("dossier_sha256")
    # Recompute the outer digest so the only failing boundary is qualification
    # authority, not a superficial hash mismatch.
    from arw.kernel.core.canonical import sha256_hex, canonical_json_bytes

    forged["dossier_sha256"] = sha256_hex(
        canonical_json_bytes({k: v for k, v in forged.items() if k != "dossier_sha256"})
    )
    with pytest.raises(Exception, match="technical PASS"):
        AuditDossierManifest.model_validate(forged)
    with pytest.raises(AuditDossierError, match="technical PASS"):
        seal_audit_dossier(forged)
    with pytest.raises(AuditDossierError, match="technical PASS"):
        publish_audit_dossier(tmp_path, forged)


def test_parent_receipt_allows_cold_load_of_assembled_pass(tmp_path) -> None:
    from arw.audit_dossier import _seal_audit_dossier
    from arw.evidence_access import publish_evidence_access_decision, seal_evidence_access_decision
    from arw.experiment_provenance import publish_experiment_provenance, seal_experiment_provenance
    from arw.integrity import publish_integrity_receipt, seal_integrity_receipt
    from arw.journal import initialize_run
    from arw.kernel.state.models import InitRunRequest
    from arw.workflows import CORE_WORKFLOW

    root = tmp_path / "run"
    source = root / "input/source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("qualification receipt\n", encoding="utf-8")
    request = InitRunRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "occurred_at": "2026-07-16T00:00:00Z",
            "immutable_input": {
                "path": "input/source.txt",
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            },
            "workflow_family": "academic-pipeline",
            "workflow_mode": "inline-role-prompts",
            "workflow_definition_id": CORE_WORKFLOW.definition_id,
            "workflow_definition_sha256": CORE_WORKFLOW.sha256,
            "journal_layout": "segmented-v1",
            "capabilities": ["canonical-journal", "forced-stop-replay"],
            "event_id": "evt-00000000-0000-4000-8000-000000000031",
            "command_id": "cmd-00000000-0000-4000-8000-000000000031",
            "actor_id": "parent.runtime",
        }
    )
    replayed = initialize_run(root, request)
    manifest_sha256 = hashlib.sha256((root / "run-manifest.json").read_bytes()).hexdigest()
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures/phase6/representative-run"
    integrity = seal_integrity_receipt(
        json.loads((fixture_root / "integrity/receipt.json").read_text(encoding="utf-8"))
    )
    provenance = seal_experiment_provenance(
        json.loads((fixture_root / "experiment/provenance.json").read_text(encoding="utf-8"))
    )
    access = seal_evidence_access_decision(
        {
            "schema_version": "arw.evidence-access-decision.v1",
            "decision_id": "decision.receipt-test",
            "evidence_id": "evidence.receipt-test",
            "subject_sha256": "a" * 64,
            "evidence_sha256": ["b" * 64],
            "source_manifest_sha256": ["c" * 64],
            "access_state": "human_review_required",
            "license_status": "unknown",
            "accountable_actor_id": "operator.user",
            "accountable_role": "operator",
            "authority_sha256": "d" * 64,
            "rationale": "receipt test requires human review",
            "scope": "receipt test",
            "created_at": "2026-07-16T00:00:00Z",
        }
    )
    publish_integrity_receipt(root, integrity)
    publish_experiment_provenance(root, provenance)
    publish_evidence_access_decision(root, access)
    claims = [
        {"capability": capability, "verdict": "PASS"}
        for capability in (
            "audit_complete",
            "citation_verified",
            "experiment_reproduced",
            "independent_review_complete",
        )
    ]
    body = {
        "schema_version": "arw.audit-dossier.v1",
        "dossier_id": "audit-dossier.current",
        "run_id": RUN_ID,
        "generated_at": "2026-07-16T00:00:00Z",
        "ledger_head_sha256": replayed.last_event_sha256,
        "run_history": [
            {
                "sequence": event.sequence,
                "event_sha256": event.event_sha256,
                "event_type": event.event_type,
                "resulting_revision": event.resulting_revision,
            }
            for event in replayed.events
        ],
        "run_manifest_sha256": manifest_sha256,
        "integrity_receipt_sha256": [integrity.receipt_sha256],
        "experiment_provenance_sha256": [provenance.provenance_sha256],
        "access_decisions": [access.decision_sha256],
        "claim_capabilities": claims,
        "technical_qualification": {
            "verdict": "PASS",
            "reason_codes": [],
            "evidence_sha256": [replayed.last_event_sha256],
            "rationale": "parent-derived qualification",
        },
        "release_qualification": {
            "verdict": "BLOCKED",
            "reason_codes": ["SUP-04"],
            "evidence_sha256": [],
            "rationale": "legal release evidence remains unresolved",
        },
        "blockers": [],
    }
    dossier = _seal_audit_dossier(body, allow_derived_pass=True)
    published = publish_audit_dossier(root, dossier)
    loaded = load_audit_dossier(root, dossier.dossier_sha256)
    assert published.read_bytes() == loaded.canonical_bytes()
    assert loaded.technical_qualification.verdict == "PASS"
