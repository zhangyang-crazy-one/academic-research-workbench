"""v2 compatibility baseline: graph projection equivalence fixtures.

Pins the projection digest for the canonical fixture record set and proves
delete-and-rebuild reproduces it byte-identically. Reuses the v1 Phase 5
fixture records so the pin covers the exact projection semantics v2 inherits.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from arw.canonical import sha256_hex
from arw.graph_models import GraphQueryOperation, GraphQueryRequest
from arw.graph_oracle import assert_equivalent, normalize_query_page
from arw.graph_projection import project_canonical_records
from arw.graph_store import GraphStore

from .normalize import read_golden_json

RECORDS_FIXTURE = Path(__file__).parent / "golden" / "projection" / "canonical_records.json"


def _fixture_records() -> list[dict[str, object]]:
    """Checked-in canonical record set — frozen locally so unrelated
    integration-test moves or edits can never drift this baseline."""
    return list(read_golden_json(RECORDS_FIXTURE)["records"])

pytestmark = pytest.mark.v2_compat

GOLDEN_DIR = Path(__file__).parent / "golden" / "projection"


def _projection():
    return project_canonical_records(
        _fixture_records(), ledger_watermark=10, ledger_head_sha256="a" * 64
    )


def test_projection_digest_matches_golden() -> None:
    projection = _projection()
    digest = sha256_hex(projection.canonical_bytes())
    golden = read_golden_json(GOLDEN_DIR / "projection_digest.json")
    assert digest == golden["projection_sha256"], (
        "projection digest drifted; v2 must rebuild the same graph from the "
        "same canonical evidence"
    )
    assert golden["node_count"] == len(projection.nodes)
    assert golden["edge_count"] == len(projection.edges)


def _query_snapshot(store: GraphStore) -> dict[str, object]:
    pages: dict[str, object] = {}
    queries: tuple[tuple[GraphQueryOperation, str], ...] = (
        ("trace_claim", "claim-004"),
        ("trace_source", "source-005"),
        ("trace_experiment", "experiment-007"),
        ("trace_review", "review-009"),
        ("trace_gate_evidence", "gate-010"),
    )
    for operation, entity_id in queries:
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


def test_delete_and_rebuild_equivalence(tmp_path: Path) -> None:
    """Delete-and-rebuild must serve identical evidence to a fresh build.

    Receipts embed per-build generation identities (timestamps), so the pin
    is at the level v1 itself guarantees: projection canonical bytes,
    receipt content fields, and normalized query snapshots (the v1 oracle).
    """
    projection = _projection()

    first = GraphStore(tmp_path / "first", "research-root")
    first_receipt = first.build_full(projection)
    first_snapshot = _query_snapshot(first)

    # True delete: remove the ENTIRE store directory (all generations and
    # pointers), then rebuild from canonical evidence alone.
    store_dir = tmp_path / "second"
    second = GraphStore(store_dir, "research-root")
    second.build_full(projection)
    shutil.rmtree(store_dir)
    assert not store_dir.exists()
    rebuilt = GraphStore(store_dir, "research-root")
    rebuilt_receipt = rebuilt.build_full(projection)

    for receipt in (first_receipt, rebuilt_receipt):
        assert receipt.input_sha256 == sha256_hex(projection.canonical_bytes())
    assert_equivalent(
        first_snapshot,
        _query_snapshot(rebuilt),
        left_label="fresh-build",
        right_label="delete-rebuild",
    )

    golden = read_golden_json(GOLDEN_DIR / "rebuild_receipt.json")
    for receipt in (first_receipt, rebuilt_receipt):
        dumped = receipt.model_dump(mode="json")
        for field in ("schema_version", "root_id", "ledger_watermark", "status"):
            assert dumped[field] == golden[field], field
        assert dumped["input_sha256"] == golden["input_sha256"]
        assert dumped["reason_codes"] == golden["reason_codes"]



def test_repeated_projection_canonical_bytes_stable() -> None:
    first = _projection().canonical_bytes()
    second = _projection().canonical_bytes()
    reversed_records = project_canonical_records(
        list(reversed(_fixture_records())),
        ledger_watermark=10,
        ledger_head_sha256="a" * 64,
    ).canonical_bytes()
    assert first == second == reversed_records
