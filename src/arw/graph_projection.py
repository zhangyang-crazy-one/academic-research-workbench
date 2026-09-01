"""Parent-owned deterministic projection from canonical records to graph input."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.graph_models import (
    GRAPH_PROJECTION_ALGORITHM,
    GraphEdge,
    GraphEntityType,
    GraphNode,
    GraphProjectionInput,
)


class GraphProjectionError(ValueError):
    """Canonical input is missing, malformed, or internally inconsistent."""


def _digest(value: object) -> str:
    try:
        return sha256_hex(canonical_json_bytes(value))
    except (TypeError, ValueError) as error:
        raise GraphProjectionError(f"projection payload is not canonical JSON: {error}") from error


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise GraphProjectionError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _entity_id(record: Mapping[str, Any], *, namespace: str) -> str:
    identity = record.get("entity_id")
    if not isinstance(identity, str) or not identity:
        raise GraphProjectionError("canonical manifest record must contain its stable entity_id")
    if not identity.startswith(f"{namespace}.") and not identity.startswith(("run-", "artifact-", "claim-", "source-", "dataset-", "experiment-", "figure-", "review-", "gate-", "stage-")):
        raise GraphProjectionError("entity_id is not bound to an accepted canonical namespace")
    return identity


def project_canonical_records(
    records: Sequence[Mapping[str, Any]],
    *,
    ledger_watermark: int,
    ledger_head_sha256: str,
    namespace: str = "research",
) -> GraphProjectionInput:
    """Project validated manifest-like records without mutating runtime state.

    `records` are read-only views of canonical manifests.  The caller may not
    provide a payload digest or graph row identity that disagrees with the
    canonical payload; the projector derives both the payload hash and every
    edge evidence hash.
    """

    if ledger_watermark < 0:
        raise GraphProjectionError("ledger watermark must be non-negative")
    ledger_head_sha256 = _require_digest(ledger_head_sha256, "ledger_head_sha256")
    nodes: list[GraphNode] = []
    raw_edges: list[tuple[Mapping[str, Any], str, str, str]] = []
    seen: set[str] = set()
    allowed_types = set(GraphEntityType.__args__)  # type: ignore[attr-defined]
    for record in records:
        if not isinstance(record, Mapping):
            raise GraphProjectionError("canonical manifest record must be an object")
        entity_type = record.get("entity_type")
        if entity_type not in allowed_types:
            raise GraphProjectionError(f"unknown research entity type: {entity_type!r}")
        entity_id = _entity_id(record, namespace=namespace)
        if entity_id in seen:
            raise GraphProjectionError(f"duplicate canonical entity: {entity_id}")
        seen.add(entity_id)
        payload = record.get("payload")
        if not isinstance(payload, Mapping):
            raise GraphProjectionError(f"{entity_id} is missing a canonical payload object")
        payload_digest = _digest(payload)
        supplied_payload_digest = record.get("payload_digest")
        if supplied_payload_digest is not None and supplied_payload_digest != payload_digest:
            raise GraphProjectionError(f"{entity_id} supplied a mismatched payload digest")
        source_digest = _require_digest(record.get("source_digest"), f"{entity_id}.source_digest")
        node_watermark = record.get("ledger_watermark", ledger_watermark)
        if not isinstance(node_watermark, int) or isinstance(node_watermark, bool) or not 0 <= node_watermark <= ledger_watermark:
            raise GraphProjectionError(f"{entity_id} has an invalid ledger watermark")
        try:
            node = GraphNode(
                schema_version="1.0.0",
                entity_type=entity_type,
                entity_id=entity_id,
                source_digest=source_digest,
                payload_digest=payload_digest,
                supersession_state=record.get("supersession_state", "active"),
                ledger_watermark=node_watermark,
                attributes=dict(payload),
            )
        except (ValidationError, ValueError, TypeError) as error:
            raise GraphProjectionError(f"invalid canonical node {entity_id}: {error}") from error
        nodes.append(node)
        edges = record.get("edges", ())
        if not isinstance(edges, Sequence) or isinstance(edges, (str, bytes, bytearray)):
            raise GraphProjectionError(f"{entity_id}.edges must be an array")
        for edge in edges:
            if not isinstance(edge, Mapping):
                raise GraphProjectionError(f"{entity_id} contains a malformed edge")
            target = edge.get("to_entity_id")
            edge_type = edge.get("edge_type")
            if not isinstance(target, str) or not isinstance(edge_type, str):
                raise GraphProjectionError(f"{entity_id} edge lacks type or target")
            evidence = edge.get("evidence")
            evidence_digest = _digest(evidence if evidence is not None else {"from": entity_id, "to": target, "type": edge_type})
            supplied_evidence = edge.get("evidence_digest")
            if supplied_evidence is not None and supplied_evidence != evidence_digest:
                raise GraphProjectionError(f"{entity_id} supplied a mismatched edge evidence digest")
            raw_edges.append((edge, entity_id, target, evidence_digest))

    node_ids = {node.entity_id for node in nodes}
    source_digests = {node.entity_id: node.source_digest for node in nodes}
    graph_edges: list[GraphEdge] = []
    for raw, source_id, target_id, evidence_digest in raw_edges:
        if target_id not in node_ids:
            raise GraphProjectionError(f"edge target is not a projected canonical entity: {target_id}")
        edge_watermark = raw.get("ledger_watermark", ledger_watermark)
        if not isinstance(edge_watermark, int) or not 0 <= edge_watermark <= ledger_watermark:
            raise GraphProjectionError("edge watermark is outside the canonical projection watermark")
        try:
            graph_edges.append(
                GraphEdge(
                    schema_version="1.0.0",
                    edge_type=raw["edge_type"],
                    from_entity_id=source_id,
                    to_entity_id=target_id,
                    evidence_digest=evidence_digest,
                    source_digest=_require_digest(raw.get("source_digest", source_digests[source_id]), "edge.source_digest"),
                    supersession_state=raw.get("supersession_state", "active"),
                    ledger_watermark=edge_watermark,
                    attributes=dict(raw.get("attributes", {})),
                )
            )
        except (KeyError, ValidationError, ValueError, TypeError) as error:
            raise GraphProjectionError(f"invalid edge {source_id}->{target_id}: {error}") from error
    return GraphProjectionInput(
        schema_version="1.0.0",
        projection_algorithm=GRAPH_PROJECTION_ALGORITHM,
        ledger_watermark=ledger_watermark,
        ledger_head_sha256=ledger_head_sha256,
        nodes=nodes,
        edges=graph_edges,
    )


def project_replayed_manifests(
    events: Sequence[Mapping[str, Any]],
    manifests: Sequence[Mapping[str, Any]],
    *,
    ledger_head_sha256: str,
    namespace: str = "research",
) -> GraphProjectionInput:
    """Project a read-only replay prefix and manifest set.

    Events are inspected for a contiguous accepted sequence.  No event is
    appended, rewritten, or interpreted as a graph authority decision.
    """

    ordered = sorted(events, key=lambda event: event.get("sequence", -1))
    sequences = [event.get("sequence") for event in ordered]
    if sequences and sequences != list(range(1, len(sequences) + 1)):
        raise GraphProjectionError("canonical replay events must have a contiguous sequence")
    watermark = len(ordered)
    return project_canonical_records(
        manifests,
        ledger_watermark=watermark,
        ledger_head_sha256=ledger_head_sha256,
        namespace=namespace,
    )


def write_projection_input(path, projection: GraphProjectionInput) -> str:
    """Write one canonical input bundle through the caller-owned parent path."""

    raw = projection.canonical_bytes()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()

