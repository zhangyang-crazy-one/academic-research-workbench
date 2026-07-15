from __future__ import annotations

import json

import pytest
from pydantic import ValidationError


def _node(entity_type: str = "Run") -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "entity_type": entity_type,
        "entity_id": "run-00000000-0000-4000-8000-000000000001",
        "source_digest": "a" * 64,
        "payload_digest": "b" * 64,
        "supersession_state": "active",
        "ledger_watermark": 3,
        "attributes": {"title": "fixture"},
    }


def test_graph_models_are_strict_and_reject_untrusted_query_surface() -> None:
    from arw.graph_models import GraphNode, GraphQueryRequest

    node = GraphNode.model_validate(_node())
    assert node.entity_type == "Run"
    with pytest.raises(ValidationError):
        GraphNode.model_validate({**_node(), "unexpected": True})
    with pytest.raises(ValidationError):
        GraphNode.model_validate({**_node(), "source_digest": "not-a-digest"})
    with pytest.raises(ValidationError):
        GraphNode.model_validate({**_node(), "entity_type": "Unknown"})
    with pytest.raises(ValidationError):
        GraphQueryRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "operation": "raw_cypher",
                "entity_id": node.entity_id,
                "max_depth": 2,
                "max_rows": 10,
                "max_bytes": 4096,
                "timeout_ms": 1000,
                "cypher": "MATCH (n) RETURN n",
            }
        )


def test_graph_schema_documents_are_draft_2020_12_and_closed() -> None:
    from arw.graph_models import generate_phase5_schema_documents

    documents = generate_phase5_schema_documents()
    assert len(documents) == 7
    for name, document in documents.items():
        assert name.endswith(".schema.json")
        assert document["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert document["additionalProperties"] is False


def test_schema_registry_includes_phase5_documents() -> None:
    from arw.schema_registry import PHASE5_SCHEMA_NAMES, SCHEMA_NAMES

    assert len(PHASE5_SCHEMA_NAMES) == 7
    assert set(PHASE5_SCHEMA_NAMES) <= set(SCHEMA_NAMES)

