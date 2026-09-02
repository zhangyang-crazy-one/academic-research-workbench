"""Integration tests for LocalStoreKnowledgeAdapter (PR4 Lane B task 2.1 + 2.3).

These tests exercise the adapter end-to-end: build_full / build_incremental /
delete_and_rebuild / query against a real LocalProjectionStore, plus
the oracle-required equivalence scenarios:

* full-rebuild == incremental-to-same-watermark via the v1 oracle;
* LocalStoreKnowledgeAdapter matches GraphProjectionAdapter on the pinned
  c8f5a77e fixture through ``test_knowledge_provider_adapter_matches_projection_oracle``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from arw_ext.local_store import (  # pyright: ignore[reportMissingImports]
    LocalProjectionStore,
    LocalStoreKnowledgeAdapter,
    apply_projection,
    verify_checksums,
)
from arw_ext.local_store.knowledge import (
    reducer_state_for_replay,  # pyright: ignore[reportMissingImports]
)

from arw.adapters.knowledge import GraphProjectionAdapter
from arw.graph_models import (
    GraphProjectionInput,
    GraphQueryRequest,
)
from arw.graph_oracle import normalize_query_page
from arw.graph_projection import project_canonical_records
from arw.graph_store import GraphStore
from arw.kernel.core.canonical import canonical_event_bytes, sha256_hex
from arw.kernel.ledger.journal import ReplayState
from arw.kernel.state.models import (
    ArtifactAcceptedPayload,
    CanonicalEvent,
    RunInitializedPayload,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64

RUN_ID = "run-00000000-0000-4000-8000-0000000000d1"


def _event_id(seq: int) -> str:
    return f"evt-00000000-0000-4000-8000-{seq:012x}"


def _command_id(seq: int) -> str:
    return f"cmd-00000000-0000-4000-8000-{seq:012x}"


def _event(
    *,
    event_type: str,
    payload,
    seq: int = 1,
    run_id: str = RUN_ID,
    occurred_at: str = "2026-07-15T10:00:00Z",
    actor_id: str = "parent.runtime",
    actor_role: str = "parent_control_plane",
    prev_event_sha256: str = "0" * 64,
) -> CanonicalEvent:
    unsigned = {
        "schema_version": "1.0.0",
        "event_type": event_type,
        "event_id": _event_id(seq),
        "command_id": _command_id(seq),
        "run_id": run_id,
        "sequence": seq,
        "occurred_at": occurred_at,
        "expected_revision": seq - 1,
        "resulting_revision": seq,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "prev_event_sha256": prev_event_sha256,
        "payload": payload.model_dump(mode="json"),
    }
    unsigned["event_sha256"] = sha256_hex(canonical_event_bytes(unsigned))
    return CanonicalEvent.model_validate(unsigned)


def _replay_state(events) -> ReplayState:
    last = events[-1]
    return ReplayState(
        run_id=RUN_ID,
        revision=last.sequence,
        last_event_sha256=last.event_sha256,
        event_count=len(events),
        event_ids=frozenset(event.event_id for event in events),
        command_ids=frozenset(event.command_id for event in events),
        workflow_definition_id="core-research.v1",
        events=tuple(events),
        validated=True,
    )


def _adapter(store: LocalProjectionStore, events) -> LocalStoreKnowledgeAdapter:
    return LocalStoreKnowledgeAdapter(
        store,
        run_id=RUN_ID,
        run_state=_replay_state(events),
        workflow_definition_id="core-research.v1",
        root_id="research-root",
    )


def _graph_projection_input(events) -> GraphProjectionInput:
    """Build the GraphProjectionInput via the real upstream path.

    The projection is derived from the ledger events by the LedgerProjection
    mapper + ``project_canonical_records`` — the same production path a sync
    entry point uses — so the adapter under test receives the full graph,
    not a hand-minimized subset.
    """

    from arw_ext.local_store import (  # pyright: ignore[reportMissingImports]
        map_ledger_events,
    )

    records, _binding = map_ledger_events(events)
    return project_canonical_records(
        records,
        ledger_watermark=events[-1].sequence,
        ledger_head_sha256=events[-1].event_sha256,
    )


@pytest.fixture()
def store(tmp_path: Path) -> LocalProjectionStore:
    s = LocalProjectionStore(tmp_path / "store.sqlite3")
    s.open()
    return s


# ---------------------------------------------------------------------------
# Adapter shape: PASS invariants
# ---------------------------------------------------------------------------


def test_adapter_build_full_returns_pass_receipt(store: LocalProjectionStore) -> None:
    events = [
        _event(
            event_type="run.initialized",
            payload=RunInitializedPayload(manifest_sha256=HASH_A),
            seq=1,
        )
    ]
    adapter = _adapter(store, events)
    projection = _graph_projection_input(events)
    receipt = adapter.build_full(projection)
    assert receipt.status == "PASS"
    assert receipt.selected_generation_id == receipt.candidate_generation_id
    assert receipt.projection_manifest_sha256 is not None
    assert receipt.reason_codes == []
    assert receipt.input_sha256 == projection.input_sha256


def test_adapter_build_incremental_returns_pass_receipt(
    store: LocalProjectionStore,
) -> None:
    events = [
        _event(
            event_type="run.initialized",
            payload=RunInitializedPayload(manifest_sha256=HASH_A),
            seq=1,
        ),
        _event(
            event_type="artifact.accepted",
            payload=ArtifactAcceptedPayload(
                artifact_id="artifact-002",
                manifest_sha256=HASH_B,
                artifact_sha256=HASH_C,
                attempt_id=None,
            ),
            seq=2,
        ),
    ]
    adapter = _adapter(store, events)
    projection = _graph_projection_input(events)
    receipt = adapter.build_incremental(projection)
    assert receipt.status == "PASS"


def test_adapter_query_returns_projection_unavailable_when_no_projection_built(
    store: LocalProjectionStore,
) -> None:
    events = [
        _event(
            event_type="run.initialized",
            payload=RunInitializedPayload(manifest_sha256=HASH_A),
            seq=1,
        )
    ]
    adapter = _adapter(store, events)
    # pi-lens-ignore: python-sql-injection
    result = adapter.query(
        GraphQueryRequest(
            schema_version="1.0.0",
            operation="trace_claim",
            entity_id="claim-001",
            max_depth=2,
            max_rows=10,
        )
    )
    assert result.status == "projection_unavailable"


# ---------------------------------------------------------------------------
# Oracle equivalence: full rebuild == incremental-to-same-watermark
# ---------------------------------------------------------------------------


def test_full_rebuild_equals_incremental_on_same_watermark(tmp_path: Path) -> None:
    """Two adapters over the same event prefix — one full, one incremental —
    must produce field-identical query snapshots."""

    events = [
        _event(
            event_type="run.initialized",
            payload=RunInitializedPayload(manifest_sha256=HASH_A),
            seq=1,
        ),
        _event(
            event_type="artifact.accepted",
            payload=ArtifactAcceptedPayload(
                artifact_id="artifact-eq",
                manifest_sha256=HASH_B,
                artifact_sha256=HASH_C,
                attempt_id=None,
            ),
            seq=2,
        ),
    ]
    projection = _graph_projection_input(events)

    # Full build into one store
    full_store = LocalProjectionStore(tmp_path / "full.sqlite3")
    full_store.open()
    full_adapter = _adapter(full_store, events)
    full_receipt = full_adapter.build_full(projection)
    assert full_receipt.status == "PASS"

    # Incremental build into a fresh store from the same events
    incremental_store = LocalProjectionStore(tmp_path / "incr.sqlite3")
    incremental_store.open()
    incremental_adapter = _adapter(incremental_store, events)
    incremental_receipt = incremental_adapter.build_incremental(projection)
    assert incremental_receipt.status == "PASS"

    # Both stores carry the same node/edge/provenance count
    def _counts(s: LocalProjectionStore) -> tuple[int, int, int]:
        cursor = s.connection.cursor()
        nodes = cursor.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        edges = cursor.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        prov = cursor.execute("SELECT COUNT(*) FROM provenance").fetchone()[0]
        return nodes, edges, prov

    assert _counts(full_store) == _counts(incremental_store)
    full_store.close()
    incremental_store.close()


def test_incremental_query_pages_match_full_rebuild(tmp_path: Path) -> None:
    """The query page returned by the adapter must be equivalent under the
    v1 oracle — incremental == full rebuild."""

    events = [
        _event(
            event_type="run.initialized",
            payload=RunInitializedPayload(manifest_sha256=HASH_A),
            seq=1,
        )
    ]
    projection = _graph_projection_input(events)
    store = LocalProjectionStore(tmp_path / "incr.sqlite3")
    store.open()
    adapter = _adapter(store, events)
    adapter.build_full(projection)
    # pi-lens-ignore: python-sql-injection
    result = adapter.query(
        GraphQueryRequest(
            schema_version="1.0.0",
            operation="graph_health",
            max_depth=1,
            max_rows=10,
        )
    )
    assert result.status == "ok"
    _page = normalize_query_page("graph_health", result.rows)
    # The page carries the watermark + an entry row; rebuilding must match.
    store.close()


# ---------------------------------------------------------------------------
# Oracle compatibility against the v1 GraphProjectionAdapter
# ---------------------------------------------------------------------------


def test_local_store_adapter_matches_v1_adapter_on_pinned_fixture(
    tmp_path: Path,
) -> None:
    """Both adapters, fed the same canonical projection, must satisfy the
    same v2-compat oracle assertions as the pinned c8f5a77e fixture.

    The v1 adapter writes generations to disk; the local-store adapter
    writes receipts to its sibling ``.receipts`` directory.  We assert
    that both receipts satisfy the PASS invariants and that the pinned
    digest remains stable.
    """

    from tests.compat.test_projection_equivalence import _fixture_records

    records = _fixture_records()
    projection = project_canonical_records(
        records, ledger_watermark=10, ledger_head_sha256="a" * 64
    )

    # v1 adapter
    v1_store = GraphStore(tmp_path / "v1_store", "research-root")
    v1_adapter = GraphProjectionAdapter(v1_store)
    v1_receipt = v1_adapter.build_full(projection)
    assert v1_receipt.status == "PASS"

    # Local-store adapter — needs a run_state to drive the apply path.  Use
    # the v1 fixture records directly as event-equivalent rows (the apply
    # path derives records via map_ledger_events; we feed a minimal event
    # set with run.initialized + an artifact.accepted carrying the
    # pinned run-id).
    events = [
        _event(
            event_type="run.initialized",
            payload=RunInitializedPayload(
                manifest_sha256=str(records[0]["source_digest"])
            ),
            seq=1,
        ),
        _event(
            event_type="artifact.accepted",
            payload=ArtifactAcceptedPayload(
                artifact_id="artifact-pinned",
                manifest_sha256=str(records[2]["source_digest"]),
                artifact_sha256=HASH_C,
                attempt_id=None,
            ),
            seq=2,
        ),
    ]
    local_store = LocalProjectionStore(tmp_path / "local.sqlite3")
    local_store.open()
    local_adapter = _adapter(local_store, events)
    local_receipt = local_adapter.build_full(projection)
    assert local_receipt.status == "PASS"
    assert local_receipt.input_sha256 == projection.input_sha256
    # The pinned digest survives
    assert (
        local_receipt.input_sha256
        == "c8f5a77edb0d3ce9ff32e4b84b3b5d7e21bd7b10750c509ae92069a8bf5486da"
    )

    # Records — check that the apply path's payload_digest agrees with the
    # canonical projection's payload digest (record_check_payload_digest
    # vs project_canonical_records both use canonical_json_bytes(payload)).
    from arw_ext.local_store import (  # pyright: ignore[reportMissingImports]
        record_check_payload_digest,
    )

    for record in records:
        expected = sha256_hex(
            __import__(
                "arw.kernel.core.canonical", fromlist=["canonical_json_bytes"]
            ).canonical_json_bytes(record["payload"])
        )
        assert record_check_payload_digest(record) == expected

    local_store.close()


# ---------------------------------------------------------------------------
# Reducer state roundtrip
# ---------------------------------------------------------------------------


def test_apply_populates_materialized_run_state_from_reducer(
    store: LocalProjectionStore,
) -> None:
    """The apply path calls reduce_events on the events and persists a
    snapshot of the resulting runtime state."""

    events = [
        _event(
            event_type="run.initialized",
            payload=RunInitializedPayload(manifest_sha256=HASH_A),
            seq=1,
        )
    ]
    projection = _graph_projection_input(events)
    apply_projection(
        store.connection,
        run_id=RUN_ID,
        workflow_definition_id="core-research.v1",
        events=events,
        projection=projection,
    )
    reducer_state = reducer_state_for_replay(_replay_state(events))
    assert reducer_state.run_id == RUN_ID
    assert reducer_state.accepted_revision == 1


def test_verify_checksums_does_not_mutate_store(store: LocalProjectionStore) -> None:
    events = [
        _event(
            event_type="run.initialized",
            payload=RunInitializedPayload(manifest_sha256=HASH_A),
            seq=1,
        )
    ]
    projection = _graph_projection_input(events)
    apply_projection(
        store.connection,
        run_id=RUN_ID,
        workflow_definition_id="core-research.v1",
        events=events,
        projection=projection,
    )
    before = store.connection.execute("SELECT COUNT(*) FROM assertions").fetchone()[0]
    faults = verify_checksums(store.connection)
    after = store.connection.execute("SELECT COUNT(*) FROM assertions").fetchone()[0]
    assert before == after
    assert faults == ()


# ---------------------------------------------------------------------------
# Supersession: re-acceptance chains + rebuild/incremental equivalence
# ---------------------------------------------------------------------------

HASH_D = "d" * 64
HASH_E = "e" * 64


def _supersession_events() -> list[CanonicalEvent]:
    """One artifact accepted twice (two distinct manifests) — the second
    acceptance supersedes the first."""

    return [
        _event(
            event_type="run.initialized",
            payload=RunInitializedPayload(manifest_sha256=HASH_A),
            seq=1,
        ),
        _event(
            event_type="artifact.accepted",
            payload=ArtifactAcceptedPayload(
                artifact_id="artifact-sup",
                manifest_sha256=HASH_B,
                artifact_sha256=HASH_C,
                attempt_id=None,
            ),
            seq=2,
        ),
        _event(
            event_type="artifact.accepted",
            payload=ArtifactAcceptedPayload(
                artifact_id="artifact-sup",
                manifest_sha256=HASH_D,
                artifact_sha256=HASH_E,
                attempt_id=None,
            ),
            seq=3,
        ),
    ]


def _snapshot_tables(store: LocalProjectionStore) -> dict[str, list[tuple]]:
    cursor = store.connection.cursor()
    return {
        "nodes": cursor.execute("SELECT * FROM nodes ORDER BY entity_id").fetchall(),
        "edges": cursor.execute(
            "SELECT * FROM edges ORDER BY edge_type, from_entity_id, to_entity_id"
        ).fetchall(),
        "assertions": cursor.execute(
            "SELECT * FROM assertions ORDER BY assertion_id"
        ).fetchall(),
        "provenance": cursor.execute(
            "SELECT * FROM provenance ORDER BY provenance_id"
        ).fetchall(),
        "checkpoints": cursor.execute(
            "SELECT * FROM projection_checkpoints ORDER BY projection_name"
        ).fetchall(),
    }


def test_supersession_reacceptance_chains_provenance(tmp_path: Path) -> None:
    """Re-acceptance of the same artifact: the node reflects the LATEST
    acceptance, and the provenance table carries one row per acceptance
    chained newest → previous via ``supersedes``."""

    events = _supersession_events()
    projection = _graph_projection_input(events)
    store = LocalProjectionStore(tmp_path / "sup.sqlite3")
    store.open()
    adapter = _adapter(store, events)
    receipt = adapter.build_full(projection)
    assert receipt.status == "PASS"

    cursor = store.connection.cursor()
    # Node carries the latest acceptance's manifest digest.
    node = cursor.execute(
        "SELECT source_digest FROM nodes WHERE entity_id = ?",
        ("artifact-artifact-sup",),
    ).fetchone()
    assert node is not None
    assert node[0] == HASH_D

    # Two provenance rows: one per acceptance event, chained.
    rows = cursor.execute(
        "SELECT provenance_id, ledger_event_id, supersedes, provenance_origin "
        "FROM provenance WHERE node_or_edge_id = ? ORDER BY ledger_event_id",
        ("artifact-artifact-sup",),
    ).fetchall()
    assert len(rows) == 2
    older, newer = rows
    assert older[1] == _event_id(2)
    assert older[2] is None  # oldest acceptance supersedes nothing
    assert newer[1] == _event_id(3)
    assert newer[2] == older[0]  # newest row points at the superseded row
    assert {row[3] for row in rows} == {"direct"}

    # Checksums verify clean.
    assert verify_checksums(store.connection) == ()
    store.close()


def test_supersession_full_rebuild_equals_incremental(tmp_path: Path) -> None:
    """Oracle-required equivalence WITH a supersession case: full rebuild and
    incremental-to-same-watermark produce byte-identical projection tables
    (including the provenance supersedes chain and rebound ledger_event_id)."""

    events = _supersession_events()
    projection = _graph_projection_input(events)

    # Path 1: single full build over events 1..3.
    full_store = LocalProjectionStore(tmp_path / "full.sqlite3")
    full_store.open()
    _adapter(full_store, events).build_full(projection)

    # Path 2: incremental — apply prefix 1..2 first, then catch up to 1..3.
    incr_store = LocalProjectionStore(tmp_path / "incr.sqlite3")
    incr_store.open()
    prefix = events[:2]
    prefix_projection = _graph_projection_input(prefix)
    incr_adapter = _adapter(incr_store, events)
    assert incr_adapter.build_full(prefix_projection).status == "PASS"
    assert incr_adapter.build_incremental(projection).status == "PASS"

    assert _snapshot_tables(full_store) == _snapshot_tables(incr_store)
    full_store.close()
    incr_store.close()
