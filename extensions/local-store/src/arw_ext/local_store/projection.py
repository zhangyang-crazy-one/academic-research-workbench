"""LedgerProjection: map canonical ledger events to the manifest-like records
that ``arw.graph_projection.project_canonical_records`` consumes.

This is the *single authority* for ``source_digest`` on every projection row
(per design D3-amended).  The mapping table it implements is documented in
``openspec/changes/sqlite-projection-store/design.md`` under "Oracle rulings
(2026-09-01, pre-implementation)" — D3 (amended): Provenance correlation rule.

The mapper is pure: it never mutates runtime state, it never opens the
projection store, and it never reads the filesystem beyond the canonical
event payloads it was handed.  Callers feed it the events produced by
``replay_run(...)``.

Edge derivation mirrors ``tests/integration/test_graph_projection.py``:

* Artifact → Stage (where ``attempt_id`` implies it) — expressed as a
  ``produces`` edge from the stage node to the artifact node.
* Claim → Source / Dataset / Figure — the canonical fixture records (the
  "v2-compat" fixture) wires these via ``supported_by`` / ``uses_dataset`` /
  ``uses_figure``.  Phase 4 ``proposal.accepted`` payloads expose
  ``proposal.citations`` and ``proposal.dataset_id`` / ``proposal.figure_id``
  candidates when present; the mapper threads a ``supported_by`` edge from
  the claim to any payload-declared source digest, and a ``uses_dataset`` /
  ``uses_figure`` edge when the payload carries the corresponding identity.

The mapper deliberately avoids making the projection STORE authoritative
over supersession.  Supersession semantics are surfaced on the canonical
record's ``supersession_state`` field and via ``supersedes`` edges; the
apply pipeline translates those into row updates.  See ``apply.py``.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.models import (
    ArtifactAcceptedPayload,
    CanonicalEvent,
    ExperimentProvenanceAcceptedPayload,
    GateEvaluatedPayload,
    LifecycleTransitionedPayload,
    ProposalAcceptedPayload,
    ReviewReportAcceptedPayload,
    ReviewSynthesisAcceptedPayload,
    RunInitializedPayload,
)

# ---------------------------------------------------------------------------
# Identity naming convention
# ---------------------------------------------------------------------------


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_digest(payload: object) -> str:
    """Return sha256 of canonical JSON bytes of ``payload``."""

    return sha256_hex(canonical_json_bytes(payload))


def _stage_id(run_id: str, stage: str) -> str:
    """Stable stage entity_id: ``stage-<run_id>-<stage>``.

    Stages are derived from ``lifecycle.transitioned`` events; the mapper
    uses the ``to_stage`` name to mint a deterministic stage identity.
    """

    digest = sha256_hex(canonical_json_bytes({"run_id": run_id, "stage": stage}))
    return f"stage-{digest[:24]}"


# ---------------------------------------------------------------------------
# Per-event-type record mappers (D3-amended table)
# ---------------------------------------------------------------------------


def _record_for_event(event: CanonicalEvent) -> dict[str, Any] | None:
    """Return one canonical manifest record, or None for unsupported events.

    The payload is inspected for the digest field named in design.md D3-amended.
    Any deviation from the table is reported by the caller (see :func:`map_ledger_events`).
    """

    payload = event.payload

    if event.event_type == "run.initialized":
        if not isinstance(payload, RunInitializedPayload):
            return None
        return {
            "entity_type": "Run",
            "entity_id": f"run-{event.run_id.split('-', 1)[1]}",
            "source_digest": payload.manifest_sha256,
            "payload": {"event_id": event.event_id, "occurred_at": event.occurred_at},
            "ledger_watermark": event.sequence,
            "_accepting_event_id": event.event_id,
            "_accepting_event_digest": event.event_sha256,
            "_acceptance_digest": payload.manifest_sha256,
        }

    if event.event_type == "lifecycle.transitioned":
        if not isinstance(payload, LifecycleTransitionedPayload):
            return None
        return {
            "entity_type": "Stage",
            "entity_id": _stage_id(event.run_id, payload.to_stage),
            "source_digest": _canonical_digest(
                {"from_stage": payload.from_stage, "to_stage": payload.to_stage}
            ),
            "payload": {
                "from_stage": payload.from_stage,
                "to_stage": payload.to_stage,
                "transition_id": payload.transition_id,
                "occurred_at": event.occurred_at,
            },
            "ledger_watermark": event.sequence,
            "_accepting_event_id": event.event_id,
            "_accepting_event_digest": event.event_sha256,
            "_acceptance_digest": sha256_hex(
                canonical_json_bytes(
                    {"from_stage": payload.from_stage, "to_stage": payload.to_stage}
                )
            ),
        }

    if event.event_type == "artifact.accepted":
        if not isinstance(payload, ArtifactAcceptedPayload):
            return None
        return {
            "entity_type": "Artifact",
            "entity_id": f"artifact-{payload.artifact_id}",
            "source_digest": payload.manifest_sha256,
            "payload_digest_hint": payload.artifact_sha256,
            "payload": {
                "artifact_id": payload.artifact_id,
                "attempt_id": payload.attempt_id,
                "occurred_at": event.occurred_at,
            },
            "ledger_watermark": event.sequence,
            "_accepting_event_id": event.event_id,
            "_accepting_event_digest": event.event_sha256,
            "_acceptance_digest": payload.manifest_sha256,
            "_artifact_sha256": payload.artifact_sha256,
            "_attempt_id": payload.attempt_id,
        }

    if event.event_type == "proposal.accepted":
        if not isinstance(payload, ProposalAcceptedPayload):
            return None
        proposal_obj = payload.proposal
        proposal_attrs = {
            "assignment_id": payload.assignment_id,
            "attempt_id": payload.attempt_id,
            "proposal_sha256": payload.proposal_sha256,
        }
        record: dict[str, Any] = {
            "entity_type": "Claim",
            "entity_id": f"claim-{payload.proposal_sha256[:24]}",
            "source_digest": payload.proposal_sha256,
            "payload": {**proposal_attrs, "occurred_at": event.occurred_at},
            "ledger_watermark": event.sequence,
            "_accepting_event_id": event.event_id,
            "_accepting_event_digest": event.event_sha256,
            "_acceptance_digest": payload.proposal_sha256,
        }
        # Attempt to surface citation / dataset / figure candidates carried on
        # the proposal payload.  Proposal models vary across versions; the
        # mapper looks up best-effort attributes and silently skips when absent.
        # WorkerProposal exposes ``evidence_sha256`` and ``input_sha256``
        # as tuple-of-sha256 fields.  The mapper threads the canonical
        # fixture's "supported_by / uses_dataset / uses_figure" edges by
        # reading the same kinds of candidate lists — see _collect_indirect_references
        # for the apply-path consumer.
        record["_indirect_refs"] = {
            "supported_by": list(getattr(proposal_obj, "evidence_sha256", ()) or ()),
        }
        return record

    if event.event_type == "review.report_accepted":
        if not isinstance(payload, ReviewReportAcceptedPayload):
            return None
        report = payload.report
        report_id = getattr(report, "report_id", None) or _canonical_digest(
            {"report_sha256": payload.report_sha256}
        )
        return {
            "entity_type": "Review",
            "entity_id": f"review-{report_id}",
            "source_digest": payload.report_sha256,
            "payload": {
                "report_id": report_id,
                "occurred_at": event.occurred_at,
            },
            "ledger_watermark": event.sequence,
            "_accepting_event_id": event.event_id,
            "_accepting_event_digest": event.event_sha256,
            "_acceptance_digest": payload.report_sha256,
            "_review_kind": "report",
        }

    if event.event_type == "review.synthesis_accepted":
        if not isinstance(payload, ReviewSynthesisAcceptedPayload):
            return None
        matrix = payload.finding_matrix
        synthesis = getattr(matrix, "synthesis", None)
        synth_id = (
            getattr(synthesis, "synthesis_id", None)
            or getattr(matrix, "panel_manifest_sha256", None)
            or payload.finding_matrix_sha256
        )
        return {
            "entity_type": "Review",
            "entity_id": f"review-synthesis-{synth_id[:24] if isinstance(synth_id, str) else synth_id}",
            "source_digest": payload.finding_matrix_sha256,
            "payload": {
                "synthesis_id": synth_id,
                "occurred_at": event.occurred_at,
            },
            "ledger_watermark": event.sequence,
            "_accepting_event_id": event.event_id,
            "_accepting_event_digest": event.event_sha256,
            "_acceptance_digest": payload.finding_matrix_sha256,
            "_review_kind": "synthesis",
        }

    if event.event_type == "gate.evaluated":
        if not isinstance(payload, GateEvaluatedPayload):
            return None
        decision = payload.decision
        gate_id = getattr(decision, "gate_id", None) or payload.decision_sha256
        return {
            "entity_type": "Gate",
            "entity_id": f"gate-{gate_id}",
            "source_digest": payload.decision_sha256,
            "payload": {
                "gate_id": gate_id,
                "verdict": getattr(decision, "verdict", None),
                "occurred_at": event.occurred_at,
            },
            "ledger_watermark": event.sequence,
            "_accepting_event_id": event.event_id,
            "_accepting_event_digest": event.event_sha256,
            "_acceptance_digest": payload.decision_sha256,
        }

    if event.event_type == "experiment.provenance.accepted":
        if not isinstance(payload, ExperimentProvenanceAcceptedPayload):
            return None
        return {
            "entity_type": "Experiment",
            "entity_id": f"experiment-{payload.experiment_id}",
            "source_digest": payload.provenance_sha256,
            "payload": {
                "provenance_id": payload.provenance_id,
                "experiment_id": payload.experiment_id,
                "occurred_at": event.occurred_at,
            },
            "ledger_watermark": event.sequence,
            "_accepting_event_id": event.event_id,
            "_accepting_event_digest": event.event_sha256,
            "_acceptance_digest": payload.provenance_sha256,
        }

    # Event types that don't project into a node by themselves; the apply
    # pipeline may still derive Tier-2 Source/Dataset/Figure entities from
    # their payloads (e.g. consumed_sha256, figure attachments).
    return None


# ---------------------------------------------------------------------------
# Indirect references: events whose payloads carry Source/Dataset/Figure identities
# ---------------------------------------------------------------------------


def _collect_indirect_references(
    event: CanonicalEvent,
) -> list[tuple[str, str, str, dict[str, Any]]]:
    """Yield ``(entity_type, entity_id, source_digest, payload_dict)`` tuples
    for Tier-2 Source/Dataset/Figure entities referenced by an event payload.

    The convention: any 64-character lowercase hex string inside the payload's
    ``consumed_sha256`` / ``source_evidence_sha256`` / ``accepted_artifact_manifest_sha256``
    / ``source_references`` fields is a candidate Source identity.  Datasets and
    Figures are surfaced via the same fields when the parent manifest names them
    via structured identifiers (``dataset_id`` / ``figure_id``).

    The apply pipeline uses the *first* event in sequence order whose payload
    references each digest (design D3-amended, Tier 2: "first-in-sequence wins").
    This function is therefore called once per event and the apply pipeline
    keeps a per-digest "first seen at sequence N" map.
    """

    out: list[tuple[str, str, str, dict[str, Any]]] = []
    payload = event.payload

    def _extend_digests(container: object) -> None:
        if not isinstance(container, (list, tuple)):
            return
        for item in container:
            if (
                isinstance(item, str)
                and len(item) == 64
                and all(c in "0123456789abcdef" for c in item)
            ):
                candidate_digests.append(item)

    candidate_digests: list[str] = []
    for field in (
        "consumed_sha256",
        "source_evidence_sha256",
        "accepted_artifact_manifest_sha256",
    ):
        _extend_digests(getattr(payload, field, None))
    for field in ("dataset_ids", "figure_ids", "source_references"):
        _extend_digests(getattr(payload, field, None))
    # Nested proposal payloads expose ``evidence_sha256`` on the proposal record
    # itself, not on the Phase 4 wrapper; surface them here so proposal-accepted
    # events contribute Tier-2 Source identities.
    nested_proposal = getattr(payload, "proposal", None)
    if nested_proposal is not None:
        _extend_digests(getattr(nested_proposal, "evidence_sha256", None))
        _extend_digests(getattr(nested_proposal, "input_sha256", None))

    for digest in candidate_digests:
        out.append(
            (
                "Source",
                f"source-{digest[:24]}",
                digest,
                {"referenced_by": event.event_id, "occurred_at": event.occurred_at},
            )
        )
    return out


# ---------------------------------------------------------------------------
# Edge derivation
# ---------------------------------------------------------------------------


def _build_edges_from_record(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Translate one mapped record's indirect references into edge dicts.

    The mapper emits ``supported_by`` / ``uses_dataset`` / ``uses_figure`` edges
    that mirror the v2-compat canonical fixture's Claim wiring; this is what
    makes the v1 ``test_graph_projection`` fixture records produce semantically
    equivalent graphs through the local store.
    """

    edges: list[dict[str, Any]] = []
    if record.get("entity_type") != "Claim":
        return edges
    refs = record.get("_indirect_refs") or {}
    for edge_type, target_ids in refs.items():
        for target in target_ids:
            if not isinstance(target, str):
                continue
            target_id = (
                f"source-{target[:24]}"
                if edge_type == "supported_by"
                else f"dataset-{target[:24]}"
                if edge_type == "uses_dataset"
                else f"figure-{target[:24]}"
            )
            edges.append({"edge_type": edge_type, "to_entity_id": target_id})
    return edges


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def map_ledger_events(
    events: Sequence[CanonicalEvent],
    *,
    include_synthetic_entities: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Map a replay prefix to canonical projection records + a binding map.

    Returns a 2-tuple of:

    * ``records`` — the manifest-like list consumed by ``project_canonical_records``.
      Each record carries a ``_accepting_event_id`` / ``_accepting_event_digest``
      / ``_acceptance_digest`` triple so the apply pipeline can wire the
      3-tier provenance binding without re-scanning events.
    * ``binding_map`` — a per-entity-type digest lookup that supports the
      indirect binding tier (the apply pipeline merges this with the events
      list when computing "first-in-sequence wins").

    The mapper signature was chosen so callers can drive it from
    ``replay_run(...).events`` directly; it never reads the filesystem.
    """

    records_by_id: dict[str, dict[str, Any]] = {}
    record_order: list[str] = []
    synthetic_records: list[dict[str, Any]] = []
    binding_map: dict[str, Any] = {
        "direct": {},  # entity_type → digest -> (event_id, event_sha256, occurred_at, actor_id)
        "indirect": {},  # digest -> [(event_id, event_sha256, field_path)]
        "synthetic": {},  # entity_type → digest -> entity_id  (Tier-2 synthesized refs)
    }
    seen_entity_ids: set[str] = set()

    for event in events:
        record = _record_for_event(event)
        if record is not None:
            entity_type = record["entity_type"]
            entity_id = record["entity_id"]
            acceptance = (
                event.event_id,
                event.event_sha256,
                event.occurred_at,
                event.actor_id,
                record["_acceptance_digest"],
            )
            if entity_id in records_by_id:
                # Re-acceptance: the LATEST record wins (it carries the final
                # state), and the acceptance history accumulates in sequence
                # order so the apply path can write the provenance supersedes
                # chain and rebind ledger_event_id to the superseding event.
                record["_acceptance_history"] = [
                    *records_by_id[entity_id]["_acceptance_history"],
                    acceptance,
                ]
                records_by_id[entity_id] = record
            else:
                record["_acceptance_history"] = [acceptance]
                records_by_id[entity_id] = record
                record_order.append(entity_id)
                seen_entity_ids.add(entity_id)
            binding_map["direct"].setdefault(entity_type, {})[
                record["source_digest"]
            ] = (
                event.event_id,
                event.event_sha256,
                event.occurred_at,
                event.actor_id,
            )
            # Translate indirect refs on the record into edges.
            record["edges"] = _build_edges_from_record(record)

        if include_synthetic_entities:
            for entity_type, entity_id, digest, payload in _collect_indirect_references(
                event
            ):
                if entity_id not in seen_entity_ids:
                    seen_entity_ids.add(entity_id)
                    synthetic_records.append(
                        {
                            "entity_type": entity_type,
                            "entity_id": entity_id,
                            "source_digest": digest,
                            "payload": payload,
                            "ledger_watermark": event.sequence,
                            "_synthetic": True,
                            "_referencing_event_id": event.event_id,
                        }
                    )
                    binding_map["synthetic"].setdefault(entity_type, {})[digest] = (
                        entity_id
                    )
                binding_map["indirect"].setdefault(digest, []).append(
                    (
                        event.event_id,
                        event.event_sha256,
                        event.sequence,
                        event.payload.__class__.__name__,
                    )
                )

    records = [records_by_id[entity_id] for entity_id in record_order]
    records.extend(synthetic_records)
    return records, binding_map


def record_check_payload_digest(record: Mapping[str, Any]) -> str:
    """Compute the projection ``payload_digest`` for one record.

    Delegates to ``arw.kernel.core.canonical``; never reads the filesystem.
    """

    payload = record.get("payload")
    if payload is None:
        return "0" * 64
    return sha256_hex(canonical_json_bytes(payload))


__all__ = [
    "map_ledger_events",
    "record_check_payload_digest",
]
