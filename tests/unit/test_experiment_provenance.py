from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/fixtures/phase6/representative-run/experiment/provenance.json"


def _payload() -> dict[str, object]:
    return {
        "schema_version": "arw.experiment-provenance.v1",
        "provenance_id": "provenance.exp-001",
        "run_id": "run-00000000-0000-4000-8000-000000000031",
        "experiment_id": "experiment.baseline-001",
        "source_datasets": [
            {
                "uri_or_path": "https://example.invalid/datasets/iris.json",
                "content_sha256": "498b9c10429a6517400aafd3c2bbac55a4f8d5c16b607b4344493856c7b8e082",
                "access_state": "publicly_verified",
                "manifest_sha256": "b" * 64,
            }
        ],
        "model_identity": [
            {
                "name": "example-model",
                "revision": "v1.2.3",
                "source_sha256": "acfc18d91e43f67e646ca04de8580c83062e736985c420c16199f5606ff60bf1",
            }
        ],
        "configuration": [
            {
                "name": "default",
                "canonical_sha256": "1203d2d7b9daa167bef051bcc1b4f51ec83268b45d688624e83f23754878ad9f",
                "content_type": "application/json",
            }
        ],
        "metrics": [
            {
                "name": "accuracy",
                "value": 0.875,
                "unit": "ratio",
                "metric_sha256": "eaf20b70838e1c5392e7b6f3b5369d1766c90869471e60a182a95b86c0766d9a",
            }
        ],
        "artifacts": [
            {
                "artifact_id": "artifact.metrics-001",
                "media_type": "application/json",
                "content_sha256": "5ff8114c2609b219ae030441bf230e753c788f7fa49ce9f61a0e781200275cfc",
                "manifest_sha256": "1" * 64,
                "content_path": "results/metrics.json",
            }
        ],
        "environment": [
            {
                "key": "python.version",
                "redacted_value_or_digest": "3.14.6",
                "tool_version": "3.14.6",
                "redacted": True,
            },
            {
                "key": "runtime.os",
                "redacted_value_or_digest": "linux",
                "tool_version": "6.8",
                "redacted": True,
            },
        ],
        "runner": {
            "identity": "runner.external-001",
            "command_digest": "2" * 64,
            "host_digest": "3" * 64,
            "started_at": "2026-07-15T10:00:00Z",
            "finished_at": "2026-07-15T10:05:00Z",
        },
        "execution_claim": {"mode": "external_only", "status": "imported"},
        "qualification_receipts": [],
        "source_manifest_sha256": ["4" * 64],
        "created_at": "2026-07-15T10:05:00Z",
    }


def test_external_provenance_is_strict_and_deterministically_sealed() -> None:
    from arw.experiment_provenance import ExperimentProvenance, seal_experiment_provenance

    first = seal_experiment_provenance(_payload())
    second = seal_experiment_provenance(first.model_dump(mode="json"))
    assert isinstance(first, ExperimentProvenance)
    assert first.provenance_sha256 == second.provenance_sha256
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.source_datasets[0].access_state == "publicly_verified"


def test_representative_fixture_round_trips_through_checked_schema() -> None:
    from arw.experiment_provenance import seal_experiment_provenance
    from arw.schema_registry import validate_instance

    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    provenance = seal_experiment_provenance(value)
    validate_instance("experiment-provenance.schema.json", provenance.model_dump(mode="json"))
    schema = json.loads(
        (ROOT / "schemas/v1/experiment-provenance.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(provenance.model_dump(mode="json"))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"unknown": True}),
        lambda value: value["execution_claim"].update({"mode": "controlled_reproduction"}),
        lambda value: value["source_datasets"].append(value["source_datasets"][0]),
        lambda value: value["metrics"][0].update({"value": "0.875"}),
        lambda value: value["artifacts"][0].update({"content_path": "../secret.txt"}),
        lambda value: value["environment"][0].update(
            {"redacted_value_or_digest": "sk-test-secret-token"}
        ),
        lambda value: value.update({"provenance_sha256": "f" * 64}),
    ],
)
def test_untrusted_or_malformed_provenance_fails_before_publication(mutation) -> None:
    from arw.experiment_provenance import ExperimentProvenance, seal_experiment_provenance

    value = _payload()
    mutation(value)
    with pytest.raises((ValidationError, ValueError)):
        ExperimentProvenance.model_validate(value)
    with pytest.raises((ValidationError, ValueError)):
        seal_experiment_provenance(value)


def test_secret_environment_key_is_rejected() -> None:
    from arw.experiment_provenance import ExperimentProvenance

    value = _payload()
    value["environment"] = [
        {
            "key": "api_key",
            "redacted_value_or_digest": "not-redacted",
            "tool_version": "1",
            "redacted": False,
        }
    ]
    with pytest.raises((ValidationError, ValueError)):
        ExperimentProvenance.model_validate(value)
