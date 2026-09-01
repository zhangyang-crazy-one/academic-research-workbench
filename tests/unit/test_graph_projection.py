from __future__ import annotations

import hashlib

from arw.kernel.core.canonical import canonical_json_bytes


def _node(entity_type: str, entity_id: str, source: str) -> dict[str, object]:
    payload = {"entity_type": entity_type, "entity_id": entity_id, "source": source}
    return {
        "schema_version": "1.0.0",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "source_digest": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
        "payload_digest": hashlib.sha256(canonical_json_bytes(payload)).hexdigest(),
        "supersession_state": "active",
        "ledger_watermark": 7,
        "attributes": payload,
    }


def test_projection_input_is_canonical_and_ordered() -> None:
    from arw.graph_projection import GraphProjectionInput

    nodes = [
        _node("Source", "source-z", "z"),
        _node("Run", "run-a", "a"),
    ]
    projection = GraphProjectionInput(
        schema_version="1.0.0",
        projection_algorithm="research-graph-projection-v1",
        ledger_watermark=7,
        ledger_head_sha256="c" * 64,
        nodes=nodes,
        edges=[],
    )
    assert [node.entity_id for node in projection.nodes] == ["run-a", "source-z"]
    first = projection.canonical_bytes()
    assert first == projection.canonical_bytes()
    assert projection.input_sha256 == hashlib.sha256(first).hexdigest()

