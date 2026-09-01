from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
import jsonschema


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/phase6/representative-run/experiment/provenance.json"


def _provenance():
    from arw.kernel.artifacts.experiment_provenance import seal_experiment_provenance

    return seal_experiment_provenance(json.loads(FIXTURE.read_text(encoding="utf-8")))


def _ingestable_provenance():
    from arw.kernel.artifacts.experiment_provenance import seal_experiment_provenance
    from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex

    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    value["artifacts"][0]["content_path"] = None
    artifact = value["artifacts"][0]
    artifact["content_sha256"] = sha256_hex(canonical_json_bytes({
        "artifact_id": artifact["artifact_id"],
        "media_type": artifact["media_type"],
        "manifest_sha256": artifact["manifest_sha256"],
        "content_path": None,
    }))
    value.pop("provenance_sha256", None)
    return seal_experiment_provenance(value)


def _receipt(provenance, kind: str, *, valid_until: str = "2026-07-15T12:00:00Z", **changes):
    from arw.kernel.artifacts.experiment_provenance import QualificationReceipt

    payload = {
        "kind": kind,
        "subject_sha256": provenance.provenance_sha256,
        "configuration_sha256": provenance.configuration_sha256,
        "artifacts_sha256": provenance.artifacts_sha256,
        "observed_at": "2026-07-15T10:00:00Z",
        "valid_until": valid_until,
        "verdict": "PASS",
        **changes,
    }
    if kind == "accountable_approval":
        payload.update({"authority_sha256": "5" * 64, "accountable_actor_id": "operator.user"})
    if kind == "provenance_equivalence_probe":
        payload.setdefault("probe_result", "equivalent")
    return QualificationReceipt.model_validate(payload)


def test_external_import_is_parent_owned_and_cold_replayable(tmp_path: Path) -> None:
    import hashlib

    from arw.kernel.artifacts.experiment_provenance import ingest_experiment_provenance, load_experiment_provenance
    from arw.kernel.ledger.journal import initialize_run
    from arw.kernel.state.models import InitRunRequest, RuntimeCommandRequest
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.ledger.workflows import CORE_WORKFLOW

    root = tmp_path / "run"
    source = root / "input" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("provenance source\n", encoding="utf-8")
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": "run-00000000-0000-4000-8000-000000000031",
                "occurred_at": "2026-07-15T10:00:00Z",
                "immutable_input": {
                    "path": "input/source.txt",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                },
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "workflow_definition_id": CORE_WORKFLOW.definition_id,
                "workflow_definition_sha256": CORE_WORKFLOW.sha256,
                "journal_layout": "segmented-v1",
                "capabilities": ["canonical-journal"],
                "event_id": "evt-00000000-0000-4000-8000-000000000031",
                "command_id": "cmd-00000000-0000-4000-8000-000000000031",
                "actor_id": "parent.runtime",
            }
        ),
    )
    request = RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": "run-00000000-0000-4000-8000-000000000031",
            "event_id": "evt-00000000-0000-4000-8000-000000000033",
            "command_id": "cmd-00000000-0000-4000-8000-000000000033",
            "expected_revision": 1,
            "occurred_at": "2026-07-15T10:05:00Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
        }
    )
    service = RuntimeCommandService(root)
    from arw.kernel.artifacts.experiment_provenance import ProvenanceAuthorityEnvelope

    result = ingest_experiment_provenance(
        _ingestable_provenance(), root, ProvenanceAuthorityEnvelope(service, request)
    )
    assert result.outcome.accepted
    assert result.path.is_file()
    assert load_experiment_provenance(root, result.provenance.provenance_sha256) == result.provenance
    replayed = RuntimeCommandService(root).read_state()
    assert result.provenance.provenance_sha256 in replayed.accepted_evidence_sha256
    assert result.outcome.event is not None
    assert result.outcome.event.event_type == "experiment.provenance.accepted"
    event_schema = json.loads(
        (Path(__file__).resolve().parents[2] / "schemas/v1/event.schema.json").read_text(
            encoding="utf-8"
        )
    )
    jsonschema.Draft202012Validator(event_schema).validate(
        result.outcome.event.model_dump(mode="json")
    )


def test_policy_rejects_forged_flags_and_stays_blocked_after_projection_loss(monkeypatch) -> None:
    from arw.kernel.artifacts.experiment_provenance import evaluate_controlled_execution_policy

    provenance = _provenance()
    called = []
    monkeypatch.setattr("subprocess.run", lambda *args, **kwargs: called.append(args))
    decision = evaluate_controlled_execution_policy(
        provenance,
        now=datetime(2026, 7, 15, 10, 30, tzinfo=UTC),
        sandbox_passed=True,
        reproduced=True,
    )
    assert decision.status == "BLOCKED"
    assert "caller_supplied_gate_flag" in decision.reason_codes
    assert "controlled_execution_adapter_disabled" in decision.reason_codes
    assert decision.subprocess_allowed is False
    assert called == []

    # Policy consumes canonical provenance only; deleting any projection/cache
    # cannot turn imported observations into a reproduction claim.
    decision_after_loss = evaluate_controlled_execution_policy(provenance, None)
    assert decision_after_loss.status == "BLOCKED"
    assert "missing_sandbox_approval" in decision_after_loss.reason_codes


def test_ingest_rejects_non_parent_authority_before_publication(tmp_path: Path) -> None:
    from arw.kernel.artifacts.experiment_provenance import ProvenanceAuthorityEnvelope, ProvenanceError, ingest_experiment_provenance
    from arw.kernel.state.models import RuntimeCommandRequest
    from arw.kernel.execution.runtime import RuntimeCommandService

    request = RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": "run-00000000-0000-4000-8000-000000000031",
            "event_id": "evt-00000000-0000-4000-8000-000000000034",
            "command_id": "cmd-00000000-0000-4000-8000-000000000034",
            "expected_revision": 1,
            "occurred_at": "2026-07-15T10:05:00Z",
            "actor_id": "operator.user",
            "actor_role": "operator",
        }
    )
    envelope = ProvenanceAuthorityEnvelope(RuntimeCommandService(tmp_path), request)
    with pytest.raises(ProvenanceError, match="parent_control_plane"):
        ingest_experiment_provenance(_ingestable_provenance(), tmp_path, envelope)
    assert not (tmp_path / "experiment").exists()


def test_missing_local_reference_and_loader_are_fail_closed_and_read_only(tmp_path: Path) -> None:
    from arw.kernel.artifacts.experiment_provenance import ProvenanceError, load_experiment_provenance, _verify_local_references

    with pytest.raises(ProvenanceError):
        _verify_local_references(tmp_path, _provenance())
    with pytest.raises(ProvenanceError):
        load_experiment_provenance(tmp_path, "a" * 64)
    assert not (tmp_path / "experiment").exists()


def test_raw_mapping_authority_is_rejected(tmp_path: Path) -> None:
    from arw.kernel.artifacts.experiment_provenance import ProvenanceError, ingest_experiment_provenance

    with pytest.raises(ProvenanceError, match="existing ProvenanceAuthorityEnvelope"):
        ingest_experiment_provenance(_ingestable_provenance(), tmp_path, {"actor_role": "parent_control_plane"})
