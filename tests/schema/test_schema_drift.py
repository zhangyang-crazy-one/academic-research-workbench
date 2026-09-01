from __future__ import annotations

import json
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_checked_in_schemas_regenerate_byte_stably(tmp_path: Path) -> None:
    from arw.kernel.policy.schema_registry import (
        PHASE1_SCHEMA_NAMES,
        SCHEMA_NAMES,
        aggregate_schema_sha256,
        regenerate_schemas,
        validate_checked_in_schemas,
    )

    assert len(PHASE1_SCHEMA_NAMES) == 8
    assert {
        "command-outcome.schema.json",
        "decision-request.schema.json",
        "recovery-receipt.schema.json",
        "recovery-request.schema.json",
        "rejection.schema.json",
        "status.schema.json",
    } <= set(SCHEMA_NAMES)
    assert validate_checked_in_schemas() == SCHEMA_NAMES
    first = regenerate_schemas(tmp_path / "first")
    second = regenerate_schemas(tmp_path / "second")
    assert first == second
    assert aggregate_schema_sha256(first) == aggregate_schema_sha256(second)
    for relative, digest in first:
        assert relative.startswith("schemas/v1/")
        assert len(digest) == 64


def test_registry_rejects_unknown_or_incompatible_schema_drift(tmp_path: Path) -> None:
    from arw.kernel.policy.schema_registry import SchemaRegistryError, validate_schema_document

    document = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/build-identity.schema.json").read_text(
            encoding="utf-8"
        )
    )
    document["properties"]["unexpected"] = {"type": "string"}
    with pytest.raises(SchemaRegistryError, match="additional properties"):
        validate_schema_document("build-identity.schema.json", document)

    incompatible = json.loads(
        (REPOSITORY_ROOT / "schemas/v1/version-report.schema.json").read_text(
            encoding="utf-8"
        )
    )
    incompatible["properties"]["command"] = {"const": "not-version"}
    with pytest.raises(SchemaRegistryError, match="command"):
        validate_schema_document("version-report.schema.json", incompatible)


def test_runtime_request_instances_validate_independently() -> None:
    from arw.kernel.policy.schema_registry import validate_instance

    common = {
        "schema_version": "1.0.0",
        "run_id": "run-00000000-0000-4000-8000-000000000031",
        "event_id": "evt-00000000-0000-4000-8000-000000000032",
        "command_id": "cmd-00000000-0000-4000-8000-000000000032",
        "expected_revision": 1,
        "occurred_at": "2026-07-13T02:00:01Z",
        "actor_id": "parent.runtime",
        "actor_role": "parent_control_plane",
    }
    validate_instance(
        "transition-request.schema.json",
        {**common, "transition_id": "start", "from_stage": "initialized"},
    )
    validate_instance(
        "attempt-request.schema.json",
        {
            **common,
            "attempt_id": "attempt.writer-001",
            "base_revision": 1,
            "consumed_sha256": ["a" * 64],
        },
    )
    validate_instance(
        "attempt-request.schema.json",
        {
            **common,
            "attempt_id": "attempt.writer-001",
            "outcome": "completed",
            "proposal_sha256": "b" * 64,
        },
    )
