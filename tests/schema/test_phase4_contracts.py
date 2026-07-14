from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_PHASE4_SCHEMAS = (
    "role-catalog.schema.json",
    "assignment.schema.json",
    "worker-proposal.schema.json",
    "review-finding-matrix.schema.json",
    "gate-decision.schema.json",
    "hook-observation.schema.json",
    "host-qualification.schema.json",
    "phase4-evaluation-verdict.schema.json",
)


def _schema(name: str) -> dict[str, object]:
    return json.loads((REPOSITORY_ROOT / "schemas/v1" / name).read_text(encoding="utf-8"))


def _registry() -> jsonschema.Draft202012Validator:
    from referencing import Registry, Resource

    resources = []
    for path in sorted((REPOSITORY_ROOT / "schemas/v1").glob("*.schema.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        if "$id" in document:
            resources.append((document["$id"], Resource.from_contents(document)))
    return jsonschema.Draft202012Validator({}, registry=Registry().with_resources(resources))


def test_phase4_schema_documents_are_generated_registered_and_byte_stable(tmp_path: Path) -> None:
    from arw.orchestration_models import generate_phase4_schema_documents
    from arw.schema_registry import (
        PHASE4_SCHEMA_NAMES,
        SCHEMA_NAMES,
        regenerate_schemas,
        validate_checked_in_schemas,
    )

    assert PHASE4_SCHEMA_NAMES == EXPECTED_PHASE4_SCHEMAS
    assert set(PHASE4_SCHEMA_NAMES) <= set(SCHEMA_NAMES)
    generated = generate_phase4_schema_documents()
    assert tuple(generated) == EXPECTED_PHASE4_SCHEMAS
    for name, expected in generated.items():
        actual = _schema(name)
        assert actual == expected
        jsonschema.Draft202012Validator.check_schema(actual)
    assert validate_checked_in_schemas() == SCHEMA_NAMES
    first = regenerate_schemas(tmp_path / "first")
    second = regenerate_schemas(tmp_path / "second")
    assert first == second
    for name in EXPECTED_PHASE4_SCHEMAS:
        assert (tmp_path / "first" / name).read_bytes() == (REPOSITORY_ROOT / "schemas/v1" / name).read_bytes()


def test_phase4_models_and_schemas_reject_unknown_and_invalid_contract_values() -> None:
    from arw.orchestration_models import GateDecision, WorkerProposal
    from arw.schema_registry import SchemaRegistryError, validate_instance

    proposal = {
        "schema_version": "arw.worker-proposal.v1",
        "protocol_version": "1.0.0",
        "run_id": "run-00000000-0000-4000-8000-000000000402",
        "assignment_id": "assignment.schema-001",
        "attempt_id": "attempt.schema-001",
        "role_id": "research_architect",
        "worker_identity_id": "worker.research-001",
        "host_agent_id": "host-agent-002",
        "execution_mode": "degraded_inline",
        "execution_provenance": "degraded_inline",
        "independence_eligible": False,
        "assignment_sha256": "a" * 64,
        "context_manifest_sha256": "b" * 64,
        "policy_sha256": "c" * 64,
        "base_revision": 1,
        "input_sha256": ["d" * 64],
        "proposal_nonce": "nonce.schema-001",
        "status": "completed",
        "result_provenance_mode": "reported",
        "requested_next_action": "accept",
        "artifacts": [
            {
                "relative_path": "result.json",
                "sha256": "e" * 64,
                "media_type": "application/json",
                "schema_id": "arw.result.v1",
                "byte_count": 32,
            }
        ],
        "evidence_sha256": [],
        "summary": "A bounded proposal fixture.",
        "unresolved": [],
    }
    model = WorkerProposal.model_validate(proposal)
    _registry().evolve(schema=_schema("worker-proposal.schema.json")).validate(
        model.model_dump(mode="json")
    )
    validate_instance("worker-proposal.schema.json", model.model_dump(mode="json"))
    invalid = {**proposal, "unknown": True}
    with pytest.raises(ValidationError):
        WorkerProposal.model_validate(invalid)
    with pytest.raises((jsonschema.ValidationError, SchemaRegistryError)):
        validate_instance("worker-proposal.schema.json", invalid)

    gate = {
        "schema_version": "arw.gate-decision.v1",
        "gate_id": "gate.schema-001",
        "subject_sha256": "a" * 64,
        "evidence_sha256": ["b" * 64],
        "verdict": "PASS",
        "rationale": "The evidence is current and complete.",
        "fresh_until": "2026-07-16T00:00:00Z",
        "required": True,
        "human_decision": None,
    }
    GateDecision.model_validate(gate)
    with pytest.raises(ValidationError):
        GateDecision.model_validate({**gate, "evidence_sha256": ["invalid"]})
    with pytest.raises((jsonschema.ValidationError, SchemaRegistryError)):
        validate_instance("gate-decision.schema.json", {**gate, "verdict": "UNKNOWN"})
