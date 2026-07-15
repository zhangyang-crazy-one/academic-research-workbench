from __future__ import annotations

import hashlib

import pytest

from arw.canonical import canonical_json_bytes
from arw.graph_projection import GraphProjectionError, project_canonical_records, project_replayed_manifests
from arw.graph_oracle import assert_equivalent, compare_normalized


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _fixture_records() -> list[dict[str, object]]:
    types = ["Run", "Stage", "Artifact", "Claim", "Source", "Dataset", "Experiment", "Figure", "Review", "Gate"]
    records: list[dict[str, object]] = []
    for index, entity_type in enumerate(types, start=1):
        entity_id = f"{entity_type.lower()}-{index:03d}"
        payload = {"entity_type": entity_type, "title": entity_id, "index": index}
        records.append(
            {
                "entity_type": entity_type,
                "entity_id": entity_id,
                "source_digest": _digest({"manifest": entity_id}),
                "payload": payload,
            }
        )
    records[0]["edges"] = [
        {"edge_type": "contains", "to_entity_id": "stage-002"},
    ]
    records[1]["edges"] = [
        {"edge_type": "produces", "to_entity_id": "artifact-003"},
    ]
    records[2]["edges"] = [
        {"edge_type": "derived_from", "to_entity_id": "experiment-007"},
    ]
    records[3]["edges"] = [
        {"edge_type": "supported_by", "to_entity_id": "source-005"},
        {"edge_type": "uses_dataset", "to_entity_id": "dataset-006"},
        {"edge_type": "uses_experiment", "to_entity_id": "experiment-007"},
        {"edge_type": "uses_figure", "to_entity_id": "figure-008"},
        {"edge_type": "corrects", "to_entity_id": "claim-004"},
    ]
    records[8]["edges"] = [{"edge_type": "dissent_for", "to_entity_id": "claim-004"}]
    records[9]["edges"] = [{"edge_type": "evidenced_by", "to_entity_id": "review-009"}]
    return records


def test_ten_entity_projection_preserves_edges_and_is_replay_stable() -> None:
    records = _fixture_records()
    first = project_canonical_records(records, ledger_watermark=10, ledger_head_sha256="a" * 64)
    second = project_canonical_records(list(reversed(records)), ledger_watermark=10, ledger_head_sha256="a" * 64)
    assert len(first.nodes) == 10
    assert len(first.edges) == 10
    assert first.canonical_bytes() == second.canonical_bytes()
    assert_equivalent(first.model_dump(mode="json"), second.model_dump(mode="json"), left_label="first", right_label="second")


def test_projection_rejects_missing_target_or_digest_drift() -> None:
    records = _fixture_records()
    records[0]["edges"] = [{"edge_type": "contains", "to_entity_id": "stage-missing"}]
    with pytest.raises(GraphProjectionError, match="target"):
        project_canonical_records(records, ledger_watermark=10, ledger_head_sha256="a" * 64)
    records = _fixture_records()
    records[0]["payload_digest"] = "b" * 64
    with pytest.raises(GraphProjectionError, match="payload digest"):
        project_canonical_records(records, ledger_watermark=10, ledger_head_sha256="a" * 64)


def test_replayed_events_require_contiguous_canonical_watermark() -> None:
    with pytest.raises(GraphProjectionError, match="contiguous"):
        project_replayed_manifests(
            [{"sequence": 1}, {"sequence": 3}],
            _fixture_records(),
            ledger_head_sha256="a" * 64,
        )


def test_oracle_strips_backend_noise_but_not_evidence() -> None:
    left = {"rows": [{"entity_id": "claim-004", "evidence_digest": "a" * 64, "backend_row_id": 1}]}
    right = {"rows": [{"entity_id": "claim-004", "evidence_digest": "a" * 64, "backend_row_id": 9}]}
    assert compare_normalized(left, right, left_label="clean", right_label="incremental").equal
    changed = {"rows": [{"entity_id": "claim-004", "evidence_digest": "b" * 64}]}
    assert not compare_normalized(left, changed, left_label="clean", right_label="changed").equal
