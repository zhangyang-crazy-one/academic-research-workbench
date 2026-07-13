from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _schema(name: str) -> dict[str, object]:
    return json.loads((REPOSITORY_ROOT / "schemas/v1" / name).read_text(encoding="utf-8"))


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
