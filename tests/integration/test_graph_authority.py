from __future__ import annotations

import hashlib
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes
from arw.graph_models import GraphQueryRequest
from arw.graph_projection import project_canonical_records
from arw.graph_store import GraphStore
from arw.runtime import RuntimeCommandService

from .test_graph_projection import _fixture_records
from .test_orchestration_lifecycle import _run


def _projection():
    return project_canonical_records(_fixture_records(), ledger_watermark=10, ledger_head_sha256="a" * 64)


def test_corruption_and_unavailability_do_not_change_canonical_runtime_state(tmp_path: Path) -> None:
    run_root, _ = _run(tmp_path / "runtime")
    before = RuntimeCommandService(run_root).read_state()
    store = GraphStore(tmp_path / "graph", "research-root")
    store.build_full(_projection())
    selected = store.selected_generation()
    assert selected is not None
    selected.database_path.write_bytes(selected.database_path.read_bytes() + b"corrupt")
    corrupt = store.query(
        GraphQueryRequest(schema_version="1.0.0", operation="trace_claim", entity_id="claim-004")
    )
    assert corrupt.status == "projection_corrupt" and corrupt.rows == []
    after_corrupt = RuntimeCommandService(run_root).read_state()
    assert after_corrupt == before

    selected.database_path.unlink()
    unavailable = store.query(
        GraphQueryRequest(schema_version="1.0.0", operation="trace_claim", entity_id="claim-004")
    )
    assert unavailable.status == "projection_unavailable" and unavailable.rows == []
    assert RuntimeCommandService(run_root).read_state() == before


def test_stale_watermark_has_no_body_bearing_rows_or_graph_mutation(tmp_path: Path) -> None:
    store = GraphStore(tmp_path / "graph", "research-root")
    store.build_full(_projection())
    selected_before = store.selected_generation()
    assert selected_before is not None
    pointer_before = (store.selected_path).read_bytes()
    result = store.query(
        GraphQueryRequest(
            schema_version="1.0.0",
            operation="trace_claim",
            entity_id="claim-004",
            expected_ledger_watermark=11,
        )
    )
    assert result.status == "projection_stale" and result.rows == []
    assert store.selected_path.read_bytes() == pointer_before
    assert hashlib.sha256(selected_before.database_path.read_bytes()).hexdigest() == selected_before.manifest.database_sha256
