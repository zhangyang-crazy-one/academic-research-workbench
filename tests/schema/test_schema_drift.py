from __future__ import annotations

import json
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_checked_in_schemas_regenerate_byte_stably(tmp_path: Path) -> None:
    from arw.schema_registry import (
        PHASE1_SCHEMA_NAMES,
        SCHEMA_NAMES,
        aggregate_schema_sha256,
        regenerate_schemas,
        validate_checked_in_schemas,
    )

    assert len(PHASE1_SCHEMA_NAMES) == 8
    assert {"rejection.schema.json", "status.schema.json"} <= set(SCHEMA_NAMES)
    assert validate_checked_in_schemas() == SCHEMA_NAMES
    first = regenerate_schemas(tmp_path / "first")
    second = regenerate_schemas(tmp_path / "second")
    assert first == second
    assert aggregate_schema_sha256(first) == aggregate_schema_sha256(second)
    for relative, digest in first:
        assert relative.startswith("schemas/v1/")
        assert len(digest) == 64


def test_registry_rejects_unknown_or_incompatible_schema_drift(tmp_path: Path) -> None:
    from arw.schema_registry import SchemaRegistryError, validate_schema_document

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
