"""Read-only evidence impact composition; no admission or semantic truth authority."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from typing import Literal

from pydantic import Field

from arw.graph_models import GraphId, GraphQueryRequest
from arw.graph_store import GraphStore
from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.state.models import StrictModel


class EvidenceUpdate(StrictModel):
    """Operator-declared change, not an inferred scientific verdict."""

    update_id: GraphId
    source_id: GraphId
    relation: Literal["support", "counterevidence", "withdrawal", "irrelevant"]
    affected_records: list[GraphId] = Field(default_factory=list, max_length=32)
    note: str = Field(min_length=1, max_length=2048)


# Follow dependents only. The generic trace is bidirectional; traversing it
# wholesale would incorrectly revise sibling claims sharing another source.
DEPENDENCIES = frozenset(
    {
        "supported_by",
        "derived_from",
        "uses_experiment",
        "uses_dataset",
        "uses_figure",
        "supersedes",
    }
)
ACTIONS = {
    "support": "Review whether additional support warrants a bounded wording or plan update.",
    "counterevidence": "Review conflicting evidence and qualify only the affected inference.",
    "withdrawal": "Reassess remaining support; withdrawal alone does not prove the claim false.",
    "irrelevant": "Review declared links; an irrelevant label does not erase dependencies.",
}


def impact_checklist(
    store: GraphStore,
    update: EvidenceUpdate,
    *,
    expected_watermark: int,
    proposed_text: Mapping[str, str] | None = None,
    max_records: int = 128,
) -> dict:
    """Compose trace + affected_records into advisory candidates without writes.

    Caller owns original-validator provenance and source-change classification.
    Proposed text is supplied by a reviewer, never inferred or accepted here.
    Failure returns an incomplete checklist, never an empty successful result.
    """
    if not 1 <= max_records <= 500:
        raise ValueError("max_records must be between 1 and 500")
    proposals = dict(proposed_text or {})
    queue = deque([(update.source_id, [update.source_id])])
    queue.extend(
        (identity, ["declared:affected_records", identity])
        for identity in update.affected_records
    )
    seen: set[str] = set()
    candidates: list[dict] = []
    generation = None
    calls = rows_read = response_bytes = 0
    blockers: list[str] = []

    def query(identity: str):
        nonlocal calls, rows_read, response_bytes, generation
        result = store.query(
            GraphQueryRequest(
                schema_version="1.0.0",
                operation="trace_source",
                entity_id=identity,
                max_depth=0,
                max_rows=2,
                max_fanout=200,
                max_bytes=262144,
                expected_ledger_watermark=expected_watermark,
            )
        )
        calls += 1
        rows_read += len(result.rows)
        response_bytes += len(canonical_json_bytes(result.model_dump(mode="json")))
        if result.status != "ok":
            blockers.append(result.reason_code or result.status)
            return None
        anchor = (result.projection_generation_id, result.projection_manifest_sha256)
        if generation is not None and generation != anchor:
            blockers.append("projection_changed_during_review")
            return None
        generation = anchor
        if len(result.rows) != 1 or result.rows[0]["entity_id"] != identity:
            blockers.append("incomplete_trace")
            return None
        return result.rows[0]

    while queue and not blockers:
        identity, path = queue.popleft()
        if identity in seen:
            continue
        if len(seen) >= max_records:
            blockers.append("impact_budget_exceeded")
            break
        seen.add(identity)
        row = query(identity)
        if row is None:
            break
        attributes = row.get("attributes")
        if not isinstance(attributes, dict):
            blockers.append("invalid_record_attributes")
            break
        kind = {"Claim": "claim", "Experiment": "experiment"}.get(row["entity_type"])
        if row["entity_type"] == "Artifact":
            kind = attributes.get("revision_kind")
            if not isinstance(kind, str) or kind not in {"plan", "paragraph"}:
                blockers.append("unsupported_artifact_revision_kind")
                break
        if (
            kind in {"claim", "plan", "experiment", "paragraph"}
            and row["supersession_state"] == "active"
        ):
            original_text = attributes.get("text")
            replacement = proposals.get(identity)
            if not isinstance(original_text, str) or not original_text.strip():
                blockers.append("invalid_original_text")
                break
            if identity in proposals and (
                not isinstance(replacement, str) or not replacement.strip()
            ):
                blockers.append("invalid_proposed_text")
                break
            candidates.append(
                {
                    "record_id": identity,
                    "kind": kind,
                    "status": "review_required_not_false",
                    "supersedes": row["payload_digest"],
                    "original_text": original_text,
                    "proposed_text": replacement,
                    "action": ACTIONS[update.relation],
                    "decision_trace": {
                        "update_id": update.update_id,
                        "path": path,
                        "relation_basis": "operator_declaration",
                    },
                }
            )
        for edge in row["relationships"]:
            if (
                edge["direction"] == "incoming"
                and edge["edge_type"] in DEPENDENCIES
                and edge["supersession_state"] == "active"
            ):
                target = edge["entity_id"]
                queue.append((target, [*path, edge["edge_type"], target]))
    # Detect generation changes even if they happen after the last dependency read.
    if not blockers:
        query(update.source_id)
    candidates.sort(key=lambda item: item["record_id"])
    ids = {item["record_id"] for item in candidates}
    return {
        "schema_version": "arw.evidence-impact-checklist.v1",
        "update": update.model_dump(mode="json"),
        "status": "incomplete" if blockers else "review_required",
        "scope": "declared_dependencies_not_semantic_truth",
        "human_review_required": True,
        "accepted_outputs_modified": False,
        "ledger_watermark": expected_watermark,
        "projection_generation_id": generation[0] if generation else None,
        "projection_manifest_sha256": generation[1] if generation else None,
        "candidates": candidates,
        "blockers": blockers,
        "unapplied_proposals": sorted(set(proposals) - ids),
        "costs": {
            "graph_queries": calls,
            "graph_rows": rows_read,
            "graph_response_bytes": response_bytes,
            "model_calls": 0,
            "model_input_tokens": 0,
            "model_output_tokens": 0,
            "external_retrieval_calls": 0,
        },
    }
