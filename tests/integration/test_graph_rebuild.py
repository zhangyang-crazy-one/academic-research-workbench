from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from arw.kernel.core.canonical import canonical_json_bytes
from arw.graph_models import GraphQueryRequest
from arw.graph_oracle import assert_equivalent, normalize_query_page
from arw.graph_projection import GraphProjectionError, project_canonical_records
from arw.graph_store import GraphStore, GraphStoreError

from .test_graph_projection import _fixture_records


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _projection(records: list[dict[str, object]], watermark: int = 10):
    return project_canonical_records(records, ledger_watermark=watermark, ledger_head_sha256="a" * 64)


def _query_snapshot(store: GraphStore) -> dict[str, object]:
    pages = {}
    for operation, entity_id in (
        ("trace_claim", "claim-004"),
        ("trace_source", "source-005"),
        ("trace_experiment", "experiment-007"),
        ("trace_review", "review-009"),
        ("trace_gate_evidence", "gate-010"),
    ):
        result = store.query(
            GraphQueryRequest(
                schema_version="1.0.0",
                operation=operation,
                entity_id=entity_id,
                max_depth=3,
                max_rows=100,
            )
        )
        assert result.status == "ok"
        pages[operation] = normalize_query_page(operation, result.rows)
    return pages


def _mutated_records(kind: str) -> list[dict[str, object]]:
    records = copy.deepcopy(_fixture_records())
    if kind == "modify":
        claim = records[3]
        claim["payload"] = {**claim["payload"], "title": "claim-004 corrected payload"}
        claim["source_digest"] = _digest({"manifest": "claim-004", "revision": 2})
    elif kind == "rename":
        source = records[4]
        source["payload"] = {**source["payload"], "path": "renamed/source-005.md"}
    elif kind == "delete":
        records[4]["supersession_state"] = "deleted"
        records[4]["payload"] = {**records[4]["payload"], "body": None}
    elif kind == "correction":
        correction = {
            "entity_type": "Claim",
            "entity_id": "claim-011",
            "source_digest": _digest({"manifest": "claim-011"}),
            "payload": {"entity_type": "Claim", "title": "corrected claim", "index": 11},
            "edges": [{"edge_type": "supersedes", "to_entity_id": "claim-004"}],
        }
        records.append(correction)
    elif kind == "migration":
        # A compatible schema migration changes the projection head while
        # preserving all canonical node/edge semantics.
        return records
    elif kind == "supersession":
        records[2]["supersession_state"] = "superseded"
        replacement = {
            "entity_type": "Artifact",
            "entity_id": "artifact-011",
            "source_digest": _digest({"manifest": "artifact-011"}),
            "payload": {"entity_type": "Artifact", "title": "replacement", "index": 11},
            "edges": [{"edge_type": "supersedes", "to_entity_id": "artifact-003"}],
        }
        records.append(replacement)
    else:
        raise AssertionError(kind)
    return records


@pytest.mark.parametrize("kind", ["modify", "rename", "delete", "correction", "migration", "supersession"])
def test_clean_incremental_delete_rebuild_equivalence(tmp_path: Path, kind: str) -> None:
    mutated = _mutated_records(kind)
    expected = GraphStore(tmp_path / f"expected-{kind}", "research-root")
    expected.build_full(_projection(mutated, watermark=11))

    incremental = GraphStore(tmp_path / f"incremental-{kind}", "research-root")
    incremental.build_full(_projection(_fixture_records()))
    incremental_receipt = incremental.build_incremental(_projection(mutated, watermark=11))
    assert incremental_receipt.status == "PASS"
    assert_equivalent(
        _query_snapshot(expected),
        _query_snapshot(incremental),
        left_label=f"clean-{kind}",
        right_label=f"incremental-{kind}",
    )

    rebuilt = GraphStore(tmp_path / f"rebuilt-{kind}", "research-root")
    rebuilt.build_full(_projection(_fixture_records()))
    rebuilt.delete_and_rebuild(_projection(mutated, watermark=11))
    assert_equivalent(
        _query_snapshot(expected),
        _query_snapshot(rebuilt),
        left_label=f"clean-{kind}",
        right_label=f"delete-rebuild-{kind}",
    )


def test_repeated_projection_is_idempotent_and_does_not_publish_duplicate_generation(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "control", "research-root")
    projection = _projection(_fixture_records())
    first = store.build_full(projection)
    second = store.build_incremental(projection)
    assert first == second
    generations = sorted((store.generations).glob("graph-generation-*"))
    assert [path.name for path in generations] == [first.selected_generation_id]


def test_ambiguous_lineage_and_stale_incremental_fail_closed(tmp_path: Path) -> None:
    duplicate = _fixture_records() + [copy.deepcopy(_fixture_records()[4])]
    with pytest.raises(GraphProjectionError, match="duplicate canonical entity"):
        _projection(duplicate)
    store = GraphStore(tmp_path / "control", "research-root")
    store.build_full(_projection(_fixture_records(), watermark=10))
    with pytest.raises(GraphStoreError, match="older"):
        store.build_incremental(_projection(_fixture_records(), watermark=9))


def test_mutation_fixture_is_machine_readable() -> None:
    fixture = Path(__file__).parents[1] / "fixtures/research-graph/mutations/mutations.json"
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    assert payload["oracle"] == "research-graph-normalization-v1"
    assert {item["id"] for item in payload["mutations"]} == {
        "modify", "rename", "delete", "correction", "migration", "supersession"
    }
