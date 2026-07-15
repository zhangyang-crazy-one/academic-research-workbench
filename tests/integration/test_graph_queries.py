from __future__ import annotations

import json
from pathlib import Path

import pytest

from arw.graph_models import GraphQueryRequest
from arw.graph_projection import project_canonical_records
from arw.graph_store import GraphStore, GraphStoreError
from tests.integration.test_graph_projection import _fixture_records


def _store(tmp_path: Path) -> GraphStore:
    store = GraphStore(tmp_path / "control", "research-root")
    store.build(project_canonical_records(_fixture_records(), ledger_watermark=10, ledger_head_sha256="a" * 64))
    return store


def test_named_trace_is_bounded_and_digest_bound(tmp_path: Path) -> None:
    store = _store(tmp_path)
    result = store.query(
        GraphQueryRequest(
            schema_version="1.0.0",
            operation="trace_claim",
            entity_id="claim-004",
            max_depth=2,
            max_rows=20,
        )
    )
    assert result.status == "ok"
    assert result.projection_generation_id is not None
    assert any(row["entity_id"] == "source-005" for row in result.rows)
    assert len(json.dumps(result.model_dump(mode="json"))) <= 65_536


def test_generation_tamper_is_typed_and_does_not_return_rows(tmp_path: Path) -> None:
    store = _store(tmp_path)
    selected = store.selected_generation()
    assert selected is not None
    selected.database_path.write_bytes(selected.database_path.read_bytes() + b"tamper")
    result = store.query(
        GraphQueryRequest(schema_version="1.0.0", operation="trace_claim", entity_id="claim-004")
    )
    assert result.status == "projection_corrupt"
    assert result.rows == []


def test_generation_unavailable_does_not_raise_or_mutate(tmp_path: Path) -> None:
    store = _store(tmp_path)
    selected = store.selected_generation()
    assert selected is not None
    selected.database_path.unlink()
    result = store.query(
        GraphQueryRequest(schema_version="1.0.0", operation="trace_claim", entity_id="claim-004")
    )
    assert result.status == "projection_unavailable"
    assert result.rows == []


def test_graph_store_rejects_write_operation_and_watermark_drift(tmp_path: Path) -> None:
    store = _store(tmp_path)
    with pytest.raises(ValueError):
        GraphQueryRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "operation": "raw_cypher",
                "entity_id": "claim-004",
                "cypher": "CREATE (n)",
            }
        )
    result = store.query(
        GraphQueryRequest(
            schema_version="1.0.0",
            operation="trace_claim",
            entity_id="claim-004",
            expected_ledger_watermark=11,
        )
    )
    assert result.status == "projection_stale"
    assert result.rows == []

