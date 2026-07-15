from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]


def _payload() -> dict[str, object]:
    return {
        "schema_version": "arw.integrity-receipt.v1",
        "receipt_id": "receipt.integrity-001",
        "subject_kind": "artifact",
        "subject_id": "artifact.result-001",
        "subject_sha256": "a" * 64,
        "input_sha256": ["b" * 64, "c" * 64],
        "method_id": "integrity.sha256",
        "method_version": "1.0.0",
        "tool_identity": {
            "name": "arw-integrity",
            "version": "0.1.0",
            "build_sha256": "d" * 64,
        },
        "observed_at": "2026-07-15T10:00:00Z",
        "freshness_policy": {
            "valid_until": "2026-07-15T11:00:00Z",
            "clock_skew_seconds": 30,
        },
        "verdict": "PASS",
        "reason_codes": ["verified"],
        "reason_text": "subject and inputs matched",
        "source_manifest_sha256": ["e" * 64],
        "created_by": "parent.runtime",
    }


def test_phase6_receipt_schema_is_registry_generated_and_strict() -> None:
    from arw.integrity import generate_phase6_schema_documents
    from arw.schema_registry import PHASE6_SCHEMA_NAMES, SCHEMA_NAMES

    assert PHASE6_SCHEMA_NAMES == (
        "integrity-receipt.schema.json",
        "experiment-provenance.schema.json",
        "evidence-access-decision.schema.json",
        "lifecycle-evidence.schema.json",
    )
    assert set(PHASE6_SCHEMA_NAMES) <= set(SCHEMA_NAMES)
    generated_documents = generate_phase6_schema_documents()
    for name, generated in generated_documents.items():
        checked = json.loads((ROOT / "schemas/v1" / name).read_text(encoding="utf-8"))
        assert checked == generated
        jsonschema.Draft202012Validator.check_schema(checked)
        assert checked["additionalProperties"] is False


def test_receipt_round_trips_through_json_schema_and_hashes_canonical_payload() -> None:
    from arw.canonical import canonical_json_bytes, sha256_hex
    from arw.integrity import IntegrityReceipt

    receipt = IntegrityReceipt.model_validate(_payload())
    document = receipt.model_dump(mode="json")
    schema = json.loads(
        (ROOT / "schemas/v1/integrity-receipt.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(document)
    unsigned = dict(document)
    actual = unsigned.pop("receipt_sha256")
    assert actual == sha256_hex(canonical_json_bytes(unsigned))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown": True}),
        lambda value: value.update({"subject_sha256": "A" * 64}),
        lambda value: value.update({"receipt_sha256": "f" * 64}),
        lambda value: value.update({"input_sha256": ["c" * 64, "b" * 64]}),
        lambda value: value.update({"input_sha256": ["b" * 64, "b" * 64]}),
        lambda value: value.update({"verdict": "PASS", "reason_codes": ["freshness_expired"]}),
    ],
)
def test_receipt_rejects_unknowns_noncanonical_arrays_and_digest_substitution(mutation) -> None:
    from arw.integrity import IntegrityReceipt

    value = _payload()
    mutation(value)
    with pytest.raises((ValidationError, ValueError)):
        IntegrityReceipt.model_validate(value)


def test_registry_validates_phase6_instances_without_static_count() -> None:
    from arw.integrity import IntegrityReceipt
    from arw.schema_registry import SCHEMA_NAMES, validate_checked_in_schemas, validate_instance

    receipt = IntegrityReceipt.model_validate(_payload())
    validate_instance("integrity-receipt.schema.json", receipt.model_dump(mode="json"))
    assert validate_checked_in_schemas() == SCHEMA_NAMES
    assert len(SCHEMA_NAMES) == len(set(SCHEMA_NAMES))
