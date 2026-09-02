"""v2-compat: LocalStoreKnowledgeAdapter matches GraphProjectionAdapter.

This test mirrors ``tests/compat/test_port_adapters.py::test_knowledge_provider_adapter_matches_projection_oracle``
for the v2 local-store adapter — it pins the projection digest through the
new adapter and proves the receipt PASS invariants hold across both
adapters.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from arw_ext.local_store import LocalProjectionStore, LocalStoreKnowledgeAdapter

from arw.adapters.knowledge import GraphProjectionAdapter
from arw.graph_projection import project_canonical_records
from arw.graph_store import GraphStore
from arw.kernel.core.canonical import canonical_event_bytes, sha256_hex
from arw.kernel.ledger.journal import ReplayState
from arw.kernel.state.models import (
    ArtifactAcceptedPayload,
    CanonicalEvent,
    RunInitializedPayload,
)

from .normalize import read_golden_json
from .test_projection_equivalence import _fixture_records

pytestmark = pytest.mark.v2_compat

GOLDEN_DIR = Path(__file__).parent / "golden" / "projection"

RUN_ID = "run-00000000-0000-4000-8000-0000000000f1"


def _event_id(seq: int) -> str:
    return f"evt-00000000-0000-4000-8000-{seq:012x}"


def _command_id(seq: int) -> str:
    return f"cmd-00000000-0000-4000-8000-{seq:012x}"


def _event(
    *,
    event_type: str,
    payload,
    seq: int,
    occurred_at: str = "2026-07-15T10:00:00Z",
) -> CanonicalEvent:
    unsigned = {
        "schema_version": "1.0.0",
        "event_type": event_type,
        "event_id": _event_id(seq),
        "command_id": _command_id(seq),
        "run_id": RUN_ID,
        "sequence": seq,
        "occurred_at": occurred_at,
        "expected_revision": seq - 1,
        "resulting_revision": seq,
        "actor_id": "parent.runtime",
        "actor_role": "parent_control_plane",
        "prev_event_sha256": "0" * 64,
        "payload": payload.model_dump(mode="json"),
    }
    unsigned["event_sha256"] = sha256_hex(canonical_event_bytes(unsigned))
    return CanonicalEvent.model_validate(unsigned)


def _chained(events):
    """Re-mint fixture events with a valid prev_event_sha256 chain."""

    from arw.kernel.ledger.journal import ZERO_HASH
    from arw.kernel.state.models import CanonicalEvent

    out = []
    previous = ZERO_HASH
    for event in events:
        unsigned = event.model_dump(mode="json")
        unsigned.pop("event_sha256", None)
        unsigned["prev_event_sha256"] = previous
        unsigned["event_sha256"] = sha256_hex(canonical_event_bytes(unsigned))
        minted = CanonicalEvent.model_validate(unsigned)
        out.append(minted)
        previous = minted.event_sha256
    return out


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


def test_local_store_knowledge_adapter_matches_v1_projection_oracle(
    tmp_path: Path,
) -> None:
    """The local-store adapter must satisfy the v2-compat golden projection
    digest through the KnowledgeProvider port."""

    records = _fixture_records()
    projection = project_canonical_records(
        records, ledger_watermark=10, ledger_head_sha256="a" * 64
    )

    # v1 oracle comparison — the same call the v1 adapter already passes.
    golden = read_golden_json(GOLDEN_DIR / "projection_digest.json")
    store = GraphStore(tmp_path / "v1_store", "research-root")
    v1_adapter = GraphProjectionAdapter(store)
    v1_receipt = v1_adapter.build_full(projection)
    assert v1_receipt.input_sha256 == golden["projection_sha256"]

    # Local-store adapter — needs run_state to drive the apply path
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
                artifact_id="artifact-local-compat",
                manifest_sha256=str(records[2]["source_digest"]),
                artifact_sha256="0" * 64,
                attempt_id=None,
            ),
            seq=2,
        ),
    ]
    local_store = LocalProjectionStore(tmp_path / "local.sqlite3")
    local_store.open()
    adapter = LocalStoreKnowledgeAdapter(
        local_store,
        run_id=RUN_ID,
        run_state=_replay_state(_chained(events)),
        workflow_definition_id="core-research.v1",
        root_id="research-root",
    )
    receipt = adapter.build_full(projection)

    # The pinned projection digest survives the new apply path.
    assert receipt.input_sha256 == projection.input_sha256
    assert sha256_hex(projection.canonical_bytes()) == golden["projection_sha256"]

    # Receipt satisfies the GraphProjectionReceipt PASS invariants
    assert receipt.status == "PASS"
    assert receipt.selected_generation_id == receipt.candidate_generation_id
    assert receipt.projection_manifest_sha256 is not None
    assert receipt.reason_codes == []

    # The golden rebuild receipt fields (mirror test_port_adapters.py).
    golden_rebuild = read_golden_json(GOLDEN_DIR / "rebuild_receipt.json")
    assert receipt.input_sha256 == golden_rebuild["input_sha256"]
    assert receipt.ledger_watermark == golden_rebuild["ledger_watermark"]
    local_store.close()
