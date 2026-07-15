"""Strict, disposable research-graph contracts for Phase 5.

The graph is an index over canonical manifests.  None of these records grants
authority to a graph consumer: the parent ledger and immutable manifests remain
the source of truth.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from arw.canonical import canonical_json_bytes
from arw.models import Sha256, StableRuntimeId, StrictModel


GRAPH_SCHEMA_VERSION = "1.0.0"
GRAPH_PROJECTION_ALGORITHM = "research-graph-projection-v1"
GRAPH_NORMALIZATION_ORACLE = "research-graph-normalization-v1"

GraphEntityType = Literal[
    "Run",
    "Stage",
    "Artifact",
    "Claim",
    "Source",
    "Dataset",
    "Experiment",
    "Figure",
    "Review",
    "Gate",
]
GraphSupersessionState = Literal[
    "active",
    "superseded",
    "corrected",
    "deleted",
    "unavailable",
]
GraphEdgeType = Literal[
    "contains",
    "produces",
    "supported_by",
    "derived_from",
    "uses_dataset",
    "uses_experiment",
    "uses_figure",
    "reviews",
    "dissent_for",
    "synthesizes",
    "evidenced_by",
    "supersedes",
    "corrects",
]
GraphQueryOperation = Literal[
    "trace_claim",
    "trace_source",
    "trace_experiment",
    "trace_review",
    "trace_gate_evidence",
    "graph_health",
]
GraphResultStatus = Literal["ok", "projection_stale", "projection_corrupt", "projection_unavailable"]

GraphId = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9._:-]{2,191}$")]


class GraphModel(StrictModel):
    """Frozen strict boundary shared by graph contracts."""

    model_config = {
        **StrictModel.model_config,
        "json_schema_extra": {"$schema": "https://json-schema.org/draft/2020-12/schema"},
    }


class GraphNode(GraphModel):
    schema_version: Literal[GRAPH_SCHEMA_VERSION]
    entity_type: GraphEntityType
    entity_id: GraphId
    source_digest: Sha256
    payload_digest: Sha256
    supersession_state: GraphSupersessionState
    ledger_watermark: Annotated[int, Field(ge=0)]
    attributes: dict[str, Any]

    @field_validator("attributes")
    @classmethod
    def attributes_are_json_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        # Round-trip through canonical JSON to reject NaN, bytes, and custom objects.
        canonical_json_bytes(value)
        if any(key.startswith("_") for key in value):
            raise ValueError("graph attributes cannot contain private authority keys")
        return value


class GraphEdge(GraphModel):
    schema_version: Literal[GRAPH_SCHEMA_VERSION]
    edge_type: GraphEdgeType
    from_entity_id: GraphId
    to_entity_id: GraphId
    evidence_digest: Sha256
    source_digest: Sha256
    supersession_state: GraphSupersessionState
    ledger_watermark: Annotated[int, Field(ge=0)]
    attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("attributes")
    @classmethod
    def edge_attributes_are_json_object(cls, value: dict[str, Any]) -> dict[str, Any]:
        canonical_json_bytes(value)
        if any(key.startswith("_") for key in value):
            raise ValueError("graph attributes cannot contain private authority keys")
        return value


class GraphProjectionInput(GraphModel):
    schema_version: Literal[GRAPH_SCHEMA_VERSION]
    projection_algorithm: Literal[GRAPH_PROJECTION_ALGORITHM]
    ledger_watermark: Annotated[int, Field(ge=0)]
    ledger_head_sha256: Sha256
    nodes: list[GraphNode]
    edges: list[GraphEdge]

    @model_validator(mode="after")
    def canonicalize_and_bind(self) -> Self:
        nodes = sorted(self.nodes, key=lambda item: (item.entity_type, item.entity_id))
        edges = sorted(
            self.edges,
            key=lambda item: (
                item.edge_type,
                item.from_entity_id,
                item.to_entity_id,
                item.evidence_digest,
            ),
        )
        if len({(node.entity_type, node.entity_id) for node in nodes}) != len(nodes):
            raise ValueError("graph node identities must be unique")
        if len(
            {
                (edge.edge_type, edge.from_entity_id, edge.to_entity_id, edge.evidence_digest)
                for edge in edges
            }
        ) != len(edges):
            raise ValueError("graph edges must be unique")
        if any(node.ledger_watermark > self.ledger_watermark for node in nodes):
            raise ValueError("node watermark exceeds projection watermark")
        if any(edge.ledger_watermark > self.ledger_watermark for edge in edges):
            raise ValueError("edge watermark exceeds projection watermark")
        node_ids = {node.entity_id for node in nodes}
        if any(edge.from_entity_id not in node_ids or edge.to_entity_id not in node_ids for edge in edges):
            raise ValueError("edges must reference projected nodes")
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "edges", edges)
        return self

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.model_dump(mode="json"))

    @property
    def input_sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


class GraphProjectionManifest(GraphModel):
    schema_version: Literal[GRAPH_SCHEMA_VERSION]
    generation_id: StableRuntimeId
    input_sha256: Sha256
    ledger_watermark: Annotated[int, Field(ge=0)]
    ledger_head_sha256: Sha256
    node_count: Annotated[int, Field(ge=0)]
    edge_count: Annotated[int, Field(ge=0)]
    projection_algorithm: Literal[GRAPH_PROJECTION_ALGORITHM]
    database_sha256: Sha256 | None
    status: Literal["building", "closed", "blocked"]


class GraphProjectionReceipt(GraphModel):
    schema_version: Literal[GRAPH_SCHEMA_VERSION]
    root_id: StableRuntimeId
    candidate_generation_id: StableRuntimeId
    previous_generation_id: StableRuntimeId | None
    selected_generation_id: StableRuntimeId | None
    projection_manifest_sha256: Sha256 | None
    input_sha256: Sha256
    ledger_watermark: Annotated[int, Field(ge=0)]
    status: Literal["PASS", "BLOCKED"]
    reason_codes: list[StableRuntimeId] = Field(default_factory=list)

    @model_validator(mode="after")
    def receipt_selection_is_closed(self) -> Self:
        if self.status == "PASS":
            if self.selected_generation_id != self.candidate_generation_id:
                raise ValueError("successful receipt must select its candidate generation")
            if self.projection_manifest_sha256 is None:
                raise ValueError("successful receipt must bind a projection manifest")
            if self.reason_codes:
                raise ValueError("successful receipt cannot contain blocker reasons")
        elif not self.reason_codes:
            raise ValueError("blocked receipt requires reason codes")
        return self


class GraphQueryRequest(GraphModel):
    schema_version: Literal[GRAPH_SCHEMA_VERSION]
    operation: GraphQueryOperation
    entity_id: GraphId | None = None
    max_depth: Annotated[int, Field(ge=0, le=8)] = 2
    max_fanout: Annotated[int, Field(ge=1, le=200)] = 50
    max_rows: Annotated[int, Field(ge=1, le=500)] = 100
    max_bytes: Annotated[int, Field(ge=256, le=262_144)] = 65_536
    timeout_ms: Annotated[int, Field(ge=1, le=5_000)] = 5_000
    expected_ledger_watermark: Annotated[int, Field(ge=0)] | None = None
    cursor: Annotated[str, StringConstraints(max_length=4096)] | None = None

    @model_validator(mode="after")
    def operation_identity_requirements(self) -> Self:
        if self.operation != "graph_health" and self.entity_id is None:
            raise ValueError("trace operations require an entity_id")
        if self.operation == "graph_health" and self.entity_id is not None:
            raise ValueError("graph_health does not accept an entity_id")
        return self


class GraphQueryResult(GraphModel):
    schema_version: Literal[GRAPH_SCHEMA_VERSION]
    operation: GraphQueryOperation
    status: GraphResultStatus
    projection_generation_id: StableRuntimeId | None
    projection_manifest_sha256: Sha256 | None
    ledger_watermark: Annotated[int, Field(ge=0)] | None
    rows: list[dict[str, Any]] = Field(default_factory=list)
    next_cursor: Annotated[str, StringConstraints(max_length=4096)] | None = None
    reason_code: StableRuntimeId | None = None

    @model_validator(mode="after")
    def result_body_matches_status(self) -> Self:
        if self.status != "ok" and self.rows:
            raise ValueError("non-ok graph result cannot contain semantic rows")
        if self.status == "ok":
            if self.projection_generation_id is None or self.ledger_watermark is None:
                raise ValueError("successful result must bind generation and watermark")
        elif self.reason_code is None:
            raise ValueError("non-ok result requires a reason code")
        return self


class GraphOracleComparison(GraphModel):
    schema_version: Literal[GRAPH_SCHEMA_VERSION]
    oracle_version: Literal[GRAPH_NORMALIZATION_ORACLE]
    left_label: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    right_label: Annotated[str, StringConstraints(min_length=1, max_length=128)]
    left_normalized_sha256: Sha256
    right_normalized_sha256: Sha256
    equal: bool
    diff_sha256: Sha256 | None
    normalized_bytes_sha256: Sha256


PHASE5_SCHEMA_MODELS: tuple[tuple[str, type[GraphModel]], ...] = (
    ("graph-node.schema.json", GraphNode),
    ("graph-edge.schema.json", GraphEdge),
    ("graph-projection-manifest.schema.json", GraphProjectionManifest),
    ("graph-projection-receipt.schema.json", GraphProjectionReceipt),
    ("graph-query-request.schema.json", GraphQueryRequest),
    ("graph-query-result.schema.json", GraphQueryResult),
    ("graph-oracle.schema.json", GraphOracleComparison),
)
PHASE5_SCHEMA_NAMES: tuple[str, ...] = tuple(name for name, _ in PHASE5_SCHEMA_MODELS)


def generate_phase5_schema_documents() -> dict[str, dict[str, Any]]:
    documents: dict[str, dict[str, Any]] = {}
    for name, model in PHASE5_SCHEMA_MODELS:
        document = model.model_json_schema(mode="validation")
        documents[name] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://arw.local/schemas/v1/{name}",
            **document,
        }
    return documents


def render_phase5_schema_bytes(name: str) -> bytes:
    documents = generate_phase5_schema_documents()
    if name not in documents:
        raise KeyError(name)
    return (json.dumps(documents[name], ensure_ascii=False, indent=2) + "\n").encode("utf-8")
