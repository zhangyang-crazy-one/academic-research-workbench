from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str) -> dict[str, object]:
    return json.loads((REPOSITORY_ROOT / "schemas/v1" / name).read_text(encoding="utf-8"))


def _validator(name: str) -> jsonschema.Draft202012Validator:
    resources = []
    for path in sorted((REPOSITORY_ROOT / "schemas/v1").glob("*.schema.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if "$id" in document:
            resources.append((document["$id"], Resource.from_contents(document)))
    return jsonschema.Draft202012Validator(
        _schema(name), registry=Registry().with_resources(resources)
    )


def test_python_and_native_fixtures_validate_independently() -> None:
    from arw.schema_registry import validate_phase1_instance

    python_fixture = json.loads(
        (REPOSITORY_ROOT / "tests/fixtures/recovery/seed/expected-run-manifest.json").read_text(
            encoding="utf-8"
        )
    )
    native_fixture = {
        "schema_version": "1.0.0",
        "status": "denied",
        "error_type": "access_denied",
        "reason": "path_traversal",
        "message": "request path leaves the configured root",
        "allowed_root": "phase1-fixture",
        "relative_path": "../outside/secret.txt",
        "platform_claim": "linux",
    }

    jsonschema.Draft202012Validator(_schema("run-manifest.schema.json")).validate(
        python_fixture
    )
    jsonschema.Draft202012Validator(_schema("mcp-read-result.schema.json")).validate(
        native_fixture
    )
    assert validate_phase1_instance("run-manifest.schema.json", python_fixture) is None
    assert validate_phase1_instance("mcp-read-result.schema.json", native_fixture) is None


def test_native_fixture_rejects_python_only_shape() -> None:
    native_validator = jsonschema.Draft202012Validator(_schema("mcp-read-result.schema.json"))
    with pytest.raises(jsonschema.ValidationError):
        native_validator.validate(
            {
                "schema_version": "1.0.0",
                "status": "denied",
                "error_type": "access_denied",
                "reason": "path_traversal",
                "message": "denied",
                "allowed_root": "phase1-fixture",
                "relative_path": "../outside/secret.txt",
                "platform_claim": "linux",
                "unknown": True,
            }
        )


def _phase2_instances() -> dict[str, list[object]]:
    from arw.kernel.core.canonical import seal_event
    from arw.kernel.state.models import (
        ArtifactAcceptanceRequest,
        ArtifactManifest,
        AttemptCloseRequest,
        AttemptStartRequest,
        CanonicalEvent,
        CheckpointRequest,
        HumanDecisionRequest,
        HumanDecisionResolveRequest,
        MaterialPassport,
        PassportPointer,
        RecoveryReceipt,
        RecoveryRequest,
        Rejection,
        ResumeRequest,
    )
    from arw.reducer import RuntimeState
    from arw.runtime import CommandOutcome
    from arw.kernel.state.status import build_status_report

    run_id = "run-00000000-0000-4000-8000-000000000101"
    common = {
        "schema_version": "1.0.0",
        "run_id": run_id,
        "event_id": "evt-00000000-0000-4000-8000-000000000102",
        "command_id": "cmd-00000000-0000-4000-8000-000000000102",
        "expected_revision": 1,
        "occurred_at": "2026-07-13T09:00:00Z",
        "actor_id": "parent.runtime",
        "actor_role": "parent_control_plane",
    }
    transition = {
        **common,
        "transition_id": "start",
        "from_stage": "initialized",
    }
    decision = HumanDecisionRequest.model_validate(
        {
            **common,
            "decision_id": "decision.route",
            "blocker_code": "human-choice-required",
            "allowed_choices": ["continue", "abort"],
            "rationale_required": True,
            "source_event_ids": [],
            "unlock_transitions": ["start"],
        }
    )
    resolution = HumanDecisionResolveRequest.model_validate(
        {
            **common,
            "decision_id": "decision.route",
            "choice": "continue",
            "rationale": "continue the validated run",
        }
    )
    attempt_start = AttemptStartRequest.model_validate(
        {
            **common,
            "attempt_id": "attempt.writer-001",
            "base_revision": 1,
            "consumed_sha256": ["a" * 64],
        }
    )
    attempt_close = AttemptCloseRequest.model_validate(
        {
            **common,
            "attempt_id": "attempt.writer-001",
            "outcome": "completed",
            "proposal_sha256": "b" * 64,
        }
    )
    artifact_request = ArtifactAcceptanceRequest.model_validate(
        {
            **common,
            "artifact_id": "artifact.result-001",
            "artifact_kind": "result",
            "media_type": "text/plain",
            "content_path": "outputs/result.txt",
            "content_sha256": "c" * 64,
            "attempt_id": None,
            "base_revision": 1,
            "consumed_sha256": [],
        }
    )
    artifact_manifest = ArtifactManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "artifact_id": "artifact.result-001",
            "artifact_kind": "result",
            "media_type": "text/plain",
            "content_path": "outputs/result.txt",
            "content_sha256": "c" * 64,
            "producer_id": "parent.runtime",
            "attempt_id": None,
            "base_revision": 1,
            "consumed_sha256": [],
            "created_at": "2026-07-13T09:00:00Z",
        }
    )
    checkpoint = CheckpointRequest.model_validate(
        {**common, "checkpoint_kind": "explicit", "fresh_until": None}
    )
    passport = MaterialPassport.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "workflow_definition_id": "core-research.v1",
            "workflow_definition_sha256": "d" * 64,
            "based_on_revision": 1,
            "ledger_head_sha256": "a" * 64,
            "stage": "initialized",
            "checkpoint_kind": "explicit",
            "parent_passport_sha256": None,
            "supersedes_passport_sha256": None,
            "accepted_artifact_manifest_sha256": [],
            "pending_human_decisions": [],
            "active_attempts": [],
            "fresh_until": None,
            "created_at": "2026-07-13T09:00:00Z",
            "created_by": "parent.runtime",
        }
    )
    pointer = PassportPointer(
        run_id=run_id,
        passport_sha256="e" * 64,
        accepted_revision=2,
        ledger_head_sha256="f" * 64,
    )
    resume = ResumeRequest.model_validate(
        {
            **common,
            "actor_id": "operator.user",
            "actor_role": "operator",
            "passport_sha256": "e" * 64,
        }
    )
    recovery = RecoveryRequest.model_validate(
        {
            **common,
            "actor_id": "operator.user",
            "actor_role": "operator",
            "expected_head_sha256": "a" * 64,
            "recovery_id": "recovery.tail-001",
            "original_segment_sha256": "b" * 64,
            "reason_code": "process-terminated",
            "reason_text": "process stopped during append",
        }
    )
    receipt = RecoveryReceipt.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "recovery_id": "recovery.tail-001",
            "segment_relative_path": "journal/segments/00000001.jsonl",
            "original_segment_sha256": "b" * 64,
            "original_segment_byte_count": 12,
            "accepted_byte_end": 10,
            "fault_offset": 10,
            "fault_class": "incomplete-record",
            "quarantine_raw_path": "quarantine/recovery.tail-001/segment.raw",
            "quarantine_raw_sha256": "b" * 64,
            "prior_valid_revision": 1,
            "prior_valid_head_sha256": "a" * 64,
            "operator_id": "operator.user",
            "reason_code": "process-terminated",
            "reason_text": "process stopped during append",
            "command_id": common["command_id"],
            "event_id": common["event_id"],
            "occurred_at": common["occurred_at"],
        }
    )
    recovery_event = CanonicalEvent.model_validate(
        seal_event(
            {
                "schema_version": "1.0.0",
                "event_type": "recovery.completed",
                "event_id": common["event_id"],
                "command_id": common["command_id"],
                "run_id": run_id,
                "sequence": 2,
                "occurred_at": common["occurred_at"],
                "expected_revision": 1,
                "resulting_revision": 2,
                "actor_id": "operator.user",
                "actor_role": "operator",
                "prev_event_sha256": "a" * 64,
                "payload": {
                    "recovery_id": "recovery.tail-001",
                    "prior_valid_revision": 1,
                    "prior_valid_head_sha256": "a" * 64,
                    "original_segment_sha256": "b" * 64,
                    "original_segment_byte_count": 12,
                    "quarantine_sha256": "b" * 64,
                    "quarantine_receipt_sha256": "c" * 64,
                    "fault_offset": 10,
                    "fault_class": "incomplete-record",
                    "reason_code": "process-terminated",
                },
            }
        )
    )
    state = RuntimeState.empty(
        run_id=run_id,
        workflow_definition_id="core-research.v1",
    )
    rejection = Rejection(
        code="stale-revision",
        message="request revision is stale",
        run_id=run_id,
        accepted_revision=0,
        ledger_head_sha256="0" * 64,
        current_passport_sha256=None,
        legal_next_transitions=["start"],
        recovery_health="healthy",
    )
    rejected = CommandOutcome(accepted=False, state=state, rejection=rejection)
    accepted_state = state.model_copy(
        update={
            "accepted_revision": 2,
            "ledger_head_sha256": recovery_event.event_sha256,
        }
    )
    accepted = CommandOutcome(
        accepted=True,
        state=accepted_state,
        event=recovery_event,
    )

    def dump(value: object) -> object:
        return value.model_dump(mode="json") if hasattr(value, "model_dump") else value

    return {
        "transition-request.schema.json": [transition],
        "decision-request.schema.json": [dump(decision), dump(resolution)],
        "attempt-request.schema.json": [dump(attempt_start), dump(attempt_close)],
        "artifact-request.schema.json": [dump(artifact_request)],
        "artifact-manifest.schema.json": [dump(artifact_manifest)],
        "checkpoint-request.schema.json": [dump(checkpoint)],
        "material-passport.schema.json": [dump(passport)],
        "passport-pointer.schema.json": [dump(pointer)],
        "resume-request.schema.json": [dump(resume)],
        "recovery-request.schema.json": [dump(recovery)],
        "recovery-receipt.schema.json": [dump(receipt)],
        "event.schema.json": [dump(recovery_event)],
        "rejection.schema.json": [dump(rejection)],
        "status.schema.json": [dump(build_status_report(state))],
        "command-outcome.schema.json": [dump(rejected), dump(accepted)],
    }


def test_phase2_model_fixtures_validate_and_unknown_fields_fail_independently() -> None:
    from arw.schema_registry import SchemaRegistryError, validate_instance

    for name, instances in _phase2_instances().items():
        validator = _validator(name)
        for instance in instances:
            validator.validate(instance)
            validate_instance(name, instance)
            invalid = {**instance, "unexpected_contract_field": True}
            with pytest.raises(jsonschema.ValidationError):
                validator.validate(invalid)
            with pytest.raises(SchemaRegistryError):
                validate_instance(name, invalid)
