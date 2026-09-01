"""Apply pipeline: write projection rows + provenance + checkpoints + run state.

The apply path is the only mutator of the projection tables (other than the
``store.py`` migration runner).  It runs inside the caller's SQLite
transaction; the local-store connection provides isolation.

Steps:

1. Compute ``projection_records`` from the ledger events via
   :func:`arw_ext.local_store.projection.map_ledger_events`.
2. For each record, resolve the per-record ``source_digest`` against the
   3-tier binding table (direct / indirect / unbound) and emit one
   deterministic provenance row per acceptance (unchained single row for
   indirect / unbound bindings); unbound rows also surface an audit fault.
3. For each record, derive ``payload_digest``, the projection-identity
   subset (``record_checksum`` byte span), and UPSERT it into ``nodes`` /
   ``edges`` / ``assertions`` (the ``assertions`` row carries the
   ``record_checksum``; the ``provenance`` rows store their own checksum).
4. Populate ``projection_checkpoints`` (last ledger sequence, head digest)
   and ``materialized_run_state`` (from ``reduce_events`` over the same
   event prefix — the apply path is *the* writer; later lanes may add
   status consumers).

Supersession semantics (D3-amended): re-acceptance of the same entity is
expressed by the mapper as one record whose ``_acceptance_history`` lists
every accepting event in sequence order.  The apply path writes one
provenance row per acceptance (deterministic id) and chains them via the
``supersedes`` pointer, newest row pointing at the previous one.  The
assertion row itself is upserted to the latest state.  Final state is a
pure function of (events 1..N, records) so full-rebuild and
incremental-to-same-watermark agree byte-for-byte on every projection row.

Determinism contract: every row id written by this module derives from
stable content (assertion id, accepting event id) — no UUIDs, no clocks —
so repeated applies are idempotent and cross-path comparison is meaningful.
Audit faults are *returned* to the caller (``ApplyResult.audit_faults``);
the caller persists them after COMMIT so a rolled-back transaction never
leaves fault sidecars behind.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from arw.graph_models import GraphProjectionInput, GraphProjectionManifest
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.reducer import reduce_events
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

from .errors import LocalStoreError
from .projection import map_ledger_events, record_check_payload_digest
from .receipts import AuditFault

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ApplyError(LocalStoreError):
    """The apply path rejected its inputs as malformed or stale.

    Distinct codes:

    * ``projection_stale`` — the stored checkpoint watermark > new
      watermark (mirrors ``GraphStore.build_incremental``).
    * ``apply_projection_invalid`` — the GraphProjectionInput is missing
      required fields or disagrees with the ledger event prefix.
    """

    code = "apply_projection_failed"


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ApplyResult:
    """The state of the projection store after one apply call.

    ``node_count`` / ``edge_count`` / ``assertion_count`` reflect post-apply
    totals (incremental applies report *cumulative* counts so callers can
    short-circuit incremental drift detection).
    """

    projection_name: str
    last_ledger_sequence: int
    last_ledger_event_digest: str
    node_count: int
    edge_count: int
    assertion_count: int
    unbound_count: int
    audit_faults: tuple[AuditFault, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# record_checksum canonical byte spans (D3-amended)
# ---------------------------------------------------------------------------


def _node_identity_subset(
    *,
    schema_version: str,
    entity_type: str,
    entity_id: str,
    source_digest: str,
    payload_digest: str,
    supersession_state: str,
    ledger_watermark: int,
) -> bytes:
    """Compute ``record_checksum`` byte span for a node assertion."""

    subset = {
        "schema_version": schema_version,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "source_digest": source_digest,
        "payload_digest": payload_digest,
        "supersession_state": supersession_state,
        "ledger_watermark": ledger_watermark,
    }
    return canonical_json_bytes(subset)


def _edge_identity_subset(
    *,
    schema_version: str,
    edge_type: str,
    from_entity_id: str,
    to_entity_id: str,
    evidence_digest: str,
    source_digest: str,
    supersession_state: str,
    ledger_watermark: int,
) -> bytes:
    subset = {
        "schema_version": schema_version,
        "edge_type": edge_type,
        "from_entity_id": from_entity_id,
        "to_entity_id": to_entity_id,
        "evidence_digest": evidence_digest,
        "source_digest": source_digest,
        "supersession_state": supersession_state,
        "ledger_watermark": ledger_watermark,
    }
    return canonical_json_bytes(subset)


def _provenance_identity_subset(
    *,
    schema_version: str,
    provenance_id: str,
    assertion_id: str,
    node_or_edge_id: str,
    source_digest: str,
) -> bytes:
    """Checksum span for one provenance row.

    The span deliberately covers only the row's own identity columns so the
    verify pass can recompute it without joins and without referencing
    provenance-payload columns (ledger event ids, supersedes pointers) that
    legitimately change across supersession rebinding.
    """

    subset = {
        "schema_version": schema_version,
        "provenance_id": provenance_id,
        "assertion_id": assertion_id,
        "node_or_edge_id": node_or_edge_id,
        "source_digest": source_digest,
    }
    return canonical_json_bytes(subset)


# ---------------------------------------------------------------------------
# Helpers: attribute JSON / deterministic ids / evidence digests
# ---------------------------------------------------------------------------


def _jsonify(value: Any) -> str:
    """Canonical-JSON serialization of arbitrary attributes."""

    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )


def _node_assertion_id(entity_type: str, entity_id: str) -> str:
    digest = hashlib.sha256(f"{entity_type}:{entity_id}".encode()).hexdigest()[:24]
    return f"asrt-{digest}"


def _edge_assertion_id(
    edge_type: str, from_id: str, to_id: str, evidence_digest: str
) -> str:
    digest = hashlib.sha256(
        f"{edge_type}:{from_id}->{to_id}:{evidence_digest}".encode()
    ).hexdigest()[:24]
    return f"asrt-{digest}"


def _provenance_id_for(assertion_id: str, qualifier: str) -> str:
    """Deterministic provenance row id from (assertion, accepting event).

    ``qualifier`` is the accepting ledger event id for bound rows, or the
    literal ``"unbound"`` for unbound rows.  Determinism is what makes the
    full-rebuild vs incremental equivalence property checkable on the
    provenance table itself.
    """

    digest = hashlib.sha256(
        f"provenance:{assertion_id}|{qualifier}".encode()
    ).hexdigest()[:24]
    return f"prov-{digest}"


def _digest_evidence(evidence: Any) -> str:
    """Default evidence digest: sha256 over canonical JSON of the edge identity."""

    if evidence is None:
        evidence = {"from": None, "to": None, "type": None}
    return sha256_hex(canonical_json_bytes(evidence))


_PROVENANCE_UPSERT = """
INSERT INTO provenance (
    provenance_id, assertion_id, node_or_edge_id, source_artifact_id,
    source_digest, source_locator, activity_id, agent_id, tool_id,
    tool_version, extraction_method, confidence, created_at,
    ledger_event_id, ledger_event_digest, projection_version,
    record_checksum, supersedes, provenance_origin
) VALUES (?, ?, ?, NULL, ?, ?, NULL, ?, NULL, NULL, NULL, NULL, ?,
          ?, ?, ?, ?, ?, ?)
ON CONFLICT(provenance_id) DO UPDATE SET
    assertion_id = excluded.assertion_id,
    node_or_edge_id = excluded.node_or_edge_id,
    source_digest = excluded.source_digest,
    source_locator = excluded.source_locator,
    agent_id = excluded.agent_id,
    created_at = excluded.created_at,
    ledger_event_id = excluded.ledger_event_id,
    ledger_event_digest = excluded.ledger_event_digest,
    projection_version = excluded.projection_version,
    record_checksum = excluded.record_checksum,
    supersedes = excluded.supersedes,
    provenance_origin = excluded.provenance_origin
"""


# ---------------------------------------------------------------------------
# Apply (full / incremental)
# ---------------------------------------------------------------------------


def apply_projection(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    workflow_definition_id: str,
    events: Sequence[CanonicalEvent],
    projection: GraphProjectionInput,
    projection_name: str = "knowledge",
    incremental: bool = False,
    receipt_id: str | None = None,
) -> ApplyResult:
    """Apply one projection against an opened LocalProjectionStore connection.

    On ``incremental=False``: truncates the projection tables and rebuilds
    from scratch.  On ``incremental=True``: upserts the same deterministic
    rows over the existing checkpoint; raises :class:`ApplyError` with code
    ``projection_stale`` when the stored checkpoint watermark is ahead of
    the input watermark.  Because every row id and checksum is a pure
    function of (events, records), both modes converge to identical state.
    """

    if not events:
        raise ApplyError(
            "apply requires at least run.initialized", code="apply_projection_invalid"
        )

    head_event = events[-1]
    new_watermark = head_event.sequence

    if not incremental:
        _truncate_projection_tables(connection)
    else:
        existing_checkpoint = _read_checkpoint(connection, projection_name)
        if existing_checkpoint is not None:
            existing_seq, existing_digest = existing_checkpoint
            if existing_seq > new_watermark or (
                existing_seq == new_watermark
                and existing_digest != head_event.event_sha256
            ):
                raise ApplyError(
                    "stored projection checkpoint is ahead of the new input watermark",
                    code="projection_stale",
                )

    records, _binding_map = map_ledger_events(events)

    # Build a digest → (event_id, event_sha256, occurred_at, actor_id) map for
    # *direct* binding, plus a digest → [(event_id, ...)] map for indirect
    # binding.  We re-scan the events once here so the apply path stays a
    # pure function of (events, records).
    direct_lookup: dict[str, tuple[str, str, str, str]] = {}
    indirect_lookup: dict[str, list[tuple[str, str, int, str]]] = {}
    event_index = events_by_id(events)
    for event in events:
        direct = _event_acceptance_digest(event)
        if direct is not None:
            direct_lookup.setdefault(
                direct,
                (event.event_id, event.event_sha256, event.occurred_at, event.actor_id),
            )
        for payload_field in (
            "consumed_sha256",
            "source_evidence_sha256",
            "accepted_artifact_manifest_sha256",
        ):
            value = getattr(event.payload, payload_field, None)
            if isinstance(value, (list, tuple)):
                for item in value:
                    if (
                        isinstance(item, str)
                        and len(item) == 64
                        and all(c in "0123456789abcdef" for c in item)
                    ):
                        indirect_lookup.setdefault(item, []).append(
                            (
                                event.event_id,
                                event.event_sha256,
                                event.sequence,
                                payload_field,
                            )
                        )
        # Nested proposal payload carries ``evidence_sha256`` and
        # ``input_sha256`` — surface those as Tier-2 indirect refs.
        nested = getattr(event.payload, "proposal", None)
        if nested is not None:
            for nested_field in ("evidence_sha256", "input_sha256"):
                value = getattr(nested, nested_field, None)
                if isinstance(value, (list, tuple)):
                    for item in value:
                        if (
                            isinstance(item, str)
                            and len(item) == 64
                            and all(c in "0123456789abcdef" for c in item)
                        ):
                            indirect_lookup.setdefault(item, []).append(
                                (
                                    event.event_id,
                                    event.event_sha256,
                                    event.sequence,
                                    f"proposal.{nested_field}",
                                )
                            )

    audit_faults: list[AuditFault] = []

    cursor = connection.cursor()

    nodes_inserted = 0
    edges_inserted = 0
    assertions_inserted = 0
    unbound_count = 0

    # ------------------------------------------------------------------
    # Insert nodes + assertions + provenance
    # ------------------------------------------------------------------
    record_by_entity_id: dict[str, dict[str, Any]] = {}

    schema_version = projection.schema_version

    for record in records:
        entity_type = record["entity_type"]
        entity_id = record["entity_id"]
        source_digest = record["source_digest"]
        payload_digest = record_check_payload_digest(record)
        # pi-lens-ignore: unchecked-throwing-call-python
        ledger_watermark = int(record.get("ledger_watermark", new_watermark))
        supersession_state = record.get("supersession_state", "active")
        attributes = record.get("payload", {})

        node_row = (
            entity_type,
            entity_id,
            source_digest,
            payload_digest,
            supersession_state,
            ledger_watermark,
            _jsonify(attributes),
        )
        # pi-lens-ignore: python-sql-injection
        cursor.execute(
            """
            INSERT INTO nodes (entity_type, entity_id, source_digest, payload_digest,
                              supersession_state, ledger_watermark, attributes_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(entity_id) DO UPDATE SET
                entity_type = excluded.entity_type,
                source_digest = excluded.source_digest,
                payload_digest = excluded.payload_digest,
                supersession_state = excluded.supersession_state,
                ledger_watermark = excluded.ledger_watermark,
                attributes_json = excluded.attributes_json
            """,
            node_row,
        )
        nodes_inserted += 1
        record_by_entity_id[entity_id] = record

        # Resolve the binding tier for THIS record.  ``direct`` requires the
        # record's own acceptance digest to match its source_digest (the D3
        # convention) and to appear in the direct lookup; otherwise the row
        # falls back to indirect (first-in-sequence referencing event) and
        # finally to unbound (NULL event ids + audit fault).
        acceptance_digest = record.get("_acceptance_digest")
        history: Sequence[tuple[str, str, str, str, str]] = (
            record.get("_acceptance_history") or ()
        )
        origin: str
        ledger_event_id: str | None
        ledger_event_digest: str | None
        if (
            acceptance_digest is not None
            and acceptance_digest == source_digest
            and acceptance_digest in direct_lookup
        ):
            origin = "direct"
            ledger_event_id = direct_lookup[acceptance_digest][0]
            ledger_event_digest = direct_lookup[acceptance_digest][1]
        elif source_digest in indirect_lookup:
            origin = "indirect"
            indirect_event_id, indirect_event_sha, _, _field = indirect_lookup[
                source_digest
            ][0]
            ledger_event_id = indirect_event_id
            ledger_event_digest = indirect_event_sha
        else:
            origin = "unbound"
            ledger_event_id = None
            ledger_event_digest = None
            unbound_count += 1
            audit_faults.append(
                AuditFault(
                    code="projection_unbound_provenance",
                    message=f"source_digest {source_digest!r} for {entity_id} has no matching ledger event",
                    affected_rows=1,
                    projection_name=projection_name,
                    receipt_id=receipt_id,
                )
            )

        assertion_id = _node_assertion_id(entity_type, entity_id)
        checksum = sha256_hex(
            _node_identity_subset(
                schema_version=schema_version,
                entity_type=entity_type,
                entity_id=entity_id,
                source_digest=source_digest,
                payload_digest=payload_digest,
                supersession_state=supersession_state,
                ledger_watermark=ledger_watermark,
            )
        )
        cursor.execute(
            """
            INSERT INTO assertions (assertion_id, entity_type, entity_id, edge_type,
                                    supersession_state, source_digest, ledger_watermark,
                                    projection_version, record_checksum)
            VALUES (?, ?, ?, NULL, ?, ?, ?, ?, ?)
            ON CONFLICT(assertion_id) DO UPDATE SET
                supersession_state = excluded.supersession_state,
                source_digest = excluded.source_digest,
                ledger_watermark = excluded.ledger_watermark,
                record_checksum = excluded.record_checksum
            """,
            (
                assertion_id,
                entity_type,
                entity_id,
                supersession_state,
                source_digest,
                ledger_watermark,
                "1",
                checksum,
            ),
        )
        assertions_inserted += 1

        # Provenance rows: deterministic id per (assertion, accepting event);
        # one row per acceptance in the entity's history, chained newest →
        # previous via ``supersedes``.  Indirect / unbound rows get a single
        # row keyed by the referencing event (or the "unbound" qualifier).
        if origin == "direct" and history:
            previous_prov_id: str | None = None
            for (
                h_event_id,
                h_event_sha,
                h_occurred_at,
                h_actor_id,
                _h_digest,
            ) in history:
                prov_id = _provenance_id_for(assertion_id, h_event_id)
                prov_checksum = sha256_hex(
                    _provenance_identity_subset(
                        schema_version=schema_version,
                        provenance_id=prov_id,
                        assertion_id=assertion_id,
                        node_or_edge_id=entity_id,
                        source_digest=source_digest,
                    )
                )
                # pi-lens-ignore: python-sql-injection
                cursor.execute(
                    _PROVENANCE_UPSERT,
                    (
                        prov_id,
                        assertion_id,
                        entity_id,
                        source_digest,
                        f"{entity_type}://{entity_id}",
                        h_actor_id,
                        h_occurred_at,
                        h_event_id,
                        h_event_sha,
                        "1",
                        prov_checksum,
                        previous_prov_id,
                        "direct",
                    ),
                )
                previous_prov_id = prov_id
        else:
            prov_id = _provenance_id_for(assertion_id, ledger_event_id or "unbound")
            prov_checksum = sha256_hex(
                _provenance_identity_subset(
                    schema_version=schema_version,
                    provenance_id=prov_id,
                    assertion_id=assertion_id,
                    node_or_edge_id=entity_id,
                    source_digest=source_digest,
                )
            )
            bound_event = event_index.get(ledger_event_id) if ledger_event_id else None
            # pi-lens-ignore: python-sql-injection
            cursor.execute(
                _PROVENANCE_UPSERT,
                (
                    prov_id,
                    assertion_id,
                    entity_id,
                    source_digest,
                    f"{entity_type}://{entity_id}",
                    bound_event.actor_id if bound_event else None,
                    bound_event.occurred_at if bound_event else None,
                    ledger_event_id,
                    ledger_event_digest,
                    "1",
                    prov_checksum,
                    None,
                    origin,
                ),
            )

    # ------------------------------------------------------------------
    # Insert edges + their provenance
    # ------------------------------------------------------------------
    for source_id, record in record_by_entity_id.items():
        raw_edges = record.get("edges", []) or []
        for raw_edge in raw_edges:
            edge_type = raw_edge["edge_type"]
            to_entity_id = raw_edge["to_entity_id"]
            evidence = raw_edge.get("evidence")
            evidence_digest = raw_edge.get("evidence_digest") or _digest_evidence(
                evidence
            )
            edge_supersession_state = raw_edge.get("supersession_state", "active")
            # pi-lens-ignore: unchecked-throwing-call-python
            edge_watermark = int(raw_edge.get("ledger_watermark", new_watermark))
            edge_attributes = raw_edge.get("attributes", {})

            edge_row = (
                edge_type,
                source_id,
                to_entity_id,
                evidence_digest,
                record["source_digest"],
                edge_supersession_state,
                edge_watermark,
                _jsonify(edge_attributes),
            )
            # pi-lens-ignore: python-sql-injection
            cursor.execute(
                """
                INSERT INTO edges (edge_type, from_entity_id, to_entity_id,
                                   evidence_digest, source_digest, supersession_state,
                                   ledger_watermark, attributes_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(edge_type, from_entity_id, to_entity_id, evidence_digest) DO UPDATE SET
                    source_digest = excluded.source_digest,
                    supersession_state = excluded.supersession_state,
                    ledger_watermark = excluded.ledger_watermark,
                    attributes_json = excluded.attributes_json
                """,
                edge_row,
            )
            edges_inserted += 1

            edge_node_or_edge_id = (
                f"{edge_type}:{source_id}->{to_entity_id}:{evidence_digest}"
            )
            assertion_id = _edge_assertion_id(
                edge_type, source_id, to_entity_id, evidence_digest
            )
            checksum = sha256_hex(
                _edge_identity_subset(
                    schema_version=schema_version,
                    edge_type=edge_type,
                    from_entity_id=source_id,
                    to_entity_id=to_entity_id,
                    evidence_digest=evidence_digest,
                    source_digest=record["source_digest"],
                    supersession_state=edge_supersession_state,
                    ledger_watermark=edge_watermark,
                )
            )
            cursor.execute(
                """
                INSERT INTO assertions (assertion_id, entity_type, entity_id, edge_type,
                                        supersession_state, source_digest, ledger_watermark,
                                        projection_version, record_checksum)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(assertion_id) DO UPDATE SET
                    supersession_state = excluded.supersession_state,
                    source_digest = excluded.source_digest,
                    ledger_watermark = excluded.ledger_watermark,
                    record_checksum = excluded.record_checksum
                """,
                (
                    assertion_id,
                    "Edge",
                    edge_node_or_edge_id,
                    edge_type,
                    edge_supersession_state,
                    record["source_digest"],
                    edge_watermark,
                    "1",
                    checksum,
                ),
            )
            assertions_inserted += 1

            # Edge provenance: edges bind to the FROM entity's latest
            # acceptance (per D3-amended), falling back to indirect / unbound
            # with the same audit-fault semantics as nodes.
            from_history: Sequence[tuple[str, str, str, str, str]] = (
                record.get("_acceptance_history") or ()
            )
            if (
                from_history
                and record.get("_acceptance_digest") == record["source_digest"]
            ):
                latest_event_id, latest_event_sha, latest_at, latest_actor, _ = (
                    from_history[-1]
                )
                edge_origin = "direct"
                edge_ledger_event_id: str | None = latest_event_id
                edge_ledger_event_digest: str | None = latest_event_sha
                edge_created_at: str | None = latest_at
                edge_agent_id: str | None = latest_actor
            elif record["source_digest"] in indirect_lookup:
                evt_id, evt_sha, _, _field = indirect_lookup[record["source_digest"]][0]
                edge_origin = "indirect"
                edge_ledger_event_id = evt_id
                edge_ledger_event_digest = evt_sha
                edge_event = event_index.get(evt_id)
                edge_created_at = edge_event.occurred_at if edge_event else None
                edge_agent_id = edge_event.actor_id if edge_event else None
            else:
                edge_origin = "unbound"
                edge_ledger_event_id = None
                edge_ledger_event_digest = None
                edge_created_at = None
                edge_agent_id = None
                unbound_count += 1
                audit_faults.append(
                    AuditFault(
                        code="projection_unbound_provenance",
                        message=f"edge {source_id}->{to_entity_id} ({edge_type}) has no matching ledger event",
                        affected_rows=1,
                        projection_name=projection_name,
                        receipt_id=receipt_id,
                    )
                )

            edge_prov_id = _provenance_id_for(
                assertion_id, edge_ledger_event_id or "unbound"
            )
            edge_prov_checksum = sha256_hex(
                _provenance_identity_subset(
                    schema_version=schema_version,
                    provenance_id=edge_prov_id,
                    assertion_id=assertion_id,
                    node_or_edge_id=edge_node_or_edge_id,
                    source_digest=record["source_digest"],
                )
            )
            # pi-lens-ignore: python-sql-injection
            cursor.execute(
                _PROVENANCE_UPSERT,
                (
                    edge_prov_id,
                    assertion_id,
                    edge_node_or_edge_id,
                    record["source_digest"],
                    f"Edge://{source_id}->{to_entity_id}",
                    edge_agent_id,
                    edge_created_at,
                    edge_ledger_event_id,
                    edge_ledger_event_digest,
                    "1",
                    edge_prov_checksum,
                    None,
                    edge_origin,
                ),
            )

    # ------------------------------------------------------------------
    # Projection checkpoint
    # ------------------------------------------------------------------
    cursor.execute(
        """
        INSERT INTO projection_checkpoints
            (projection_name, last_ledger_sequence, last_ledger_event_digest,
             last_applied_at, projection_version)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(projection_name) DO UPDATE SET
            last_ledger_sequence = excluded.last_ledger_sequence,
            last_ledger_event_digest = excluded.last_ledger_event_digest,
            last_applied_at = excluded.last_applied_at,
            projection_version = excluded.projection_version
        """,
        (
            projection_name,
            new_watermark,
            head_event.event_sha256,
            head_event.occurred_at,
            "1",
        ),
    )

    # ------------------------------------------------------------------
    # Materialized run state via reducer
    # ------------------------------------------------------------------
    try:
        reduced = reduce_events(workflow_definition_id, list(events))
        stage = getattr(reduced, "stage", "initialized")
        status = getattr(reduced, "status", "RUNNING")
        revision = getattr(reduced, "accepted_revision", new_watermark)
        attributes = {
            "execution_mode": getattr(reduced, "execution_mode", None),
            "blockers": [item.code for item in getattr(reduced, "blockers", [])],
            "accepted_revision": revision,
            "reducer_version": getattr(reduced, "reducer_version", "1.0.0"),
        }
    except Exception:  # noqa: BLE001 — reducer failure is non-fatal for apply
        stage = "initialized"
        status = "RUNNING"
        revision = new_watermark
        attributes = {}

    cursor.execute(
        """
        INSERT INTO materialized_run_state
            (run_id, stage, status, started_at, updated_at, last_event_sequence,
             attributes_json, ledger_watermark)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(run_id) DO UPDATE SET
            stage = excluded.stage,
            status = excluded.status,
            updated_at = excluded.updated_at,
            last_event_sequence = excluded.last_event_sequence,
            attributes_json = excluded.attributes_json,
            ledger_watermark = excluded.ledger_watermark
        """,
        (
            run_id,
            stage,
            status,
            events[0].occurred_at,
            head_event.occurred_at,
            new_watermark,
            _jsonify(attributes),
            new_watermark,
        ),
    )

    return ApplyResult(
        projection_name=projection_name,
        last_ledger_sequence=new_watermark,
        last_ledger_event_digest=head_event.event_sha256,
        node_count=nodes_inserted,
        edge_count=edges_inserted,
        assertion_count=assertions_inserted,
        unbound_count=unbound_count,
        audit_faults=tuple(audit_faults),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truncate_projection_tables(connection: sqlite3.Connection) -> None:
    """Truncate every projection-owned table.

    The migration runner's tables ``projection_meta``, ``activities``,
    ``agents``, ``decisions``, ``materialized_run_state``, ``artifacts`` and
    the file-side tables are NOT touched — this function only resets
    projection-domain tables so a rebuild is deterministic for the
    knowledge projection.  ``materialized_run_state`` rows are *overwritten*
    by the apply path so a rebuild refreshes them too.
    """

    cursor = connection.cursor()
    cursor.execute("DELETE FROM provenance")
    cursor.execute("DELETE FROM assertions")
    cursor.execute("DELETE FROM edges")
    cursor.execute("DELETE FROM nodes")
    cursor.execute("DELETE FROM projection_checkpoints")


def _read_checkpoint(
    connection: sqlite3.Connection,
    projection_name: str,
) -> tuple[int, str] | None:
    cursor = connection.cursor()
    row = cursor.execute(
        "SELECT last_ledger_sequence, last_ledger_event_digest "
        "FROM projection_checkpoints WHERE projection_name = ?",
        (projection_name,),
    ).fetchone()
    if row is None:
        return None
    # pi-lens-ignore: unchecked-throwing-call-python
    return int(row[0]), str(row[1])


def _event_acceptance_digest(event: CanonicalEvent) -> str | None:
    """Return the per-event "acceptance digest" used by the binding table.

    Mirrors the source_digest convention table in design.md D3-amended.
    Returns ``None`` for event types that don't project a node.
    """

    payload = event.payload
    if event.event_type == "run.initialized" and isinstance(
        payload, RunInitializedPayload
    ):
        return payload.manifest_sha256
    if event.event_type == "lifecycle.transitioned" and isinstance(
        payload, LifecycleTransitionedPayload
    ):
        return sha256_hex(
            canonical_json_bytes(
                {"from_stage": payload.from_stage, "to_stage": payload.to_stage}
            )
        )
    if event.event_type == "artifact.accepted" and isinstance(
        payload, ArtifactAcceptedPayload
    ):
        return payload.manifest_sha256
    if event.event_type == "proposal.accepted" and isinstance(
        payload, ProposalAcceptedPayload
    ):
        return payload.proposal_sha256
    if event.event_type == "review.report_accepted" and isinstance(
        payload, ReviewReportAcceptedPayload
    ):
        return payload.report_sha256
    if event.event_type == "review.synthesis_accepted" and isinstance(
        payload, ReviewSynthesisAcceptedPayload
    ):
        return payload.finding_matrix_sha256
    if event.event_type == "gate.evaluated" and isinstance(
        payload, GateEvaluatedPayload
    ):
        return payload.decision_sha256
    if event.event_type == "experiment.provenance.accepted" and isinstance(
        payload, ExperimentProvenanceAcceptedPayload
    ):
        return payload.provenance_sha256
    return None


def events_by_id(events: Sequence[CanonicalEvent]) -> dict[str, CanonicalEvent]:
    """Return an event_id → CanonicalEvent lookup."""

    return {event.event_id: event for event in events}


def build_graph_manifest(
    *,
    projection_name: str,
    projection: GraphProjectionInput,
    generation_id: str,
    last_ledger_event_digest: str,
    database_path_str: str,
) -> GraphProjectionManifest:
    """Build the manifest envelope that the receipt binds.

    Mirrors ``GraphStore.build``'s manifest shape so the receipt's
    ``projection_manifest_sha256`` is comparable across adapters.  The
    ``generation_id`` is supplied by the caller (deterministic, derived from
    the projection input) so repeated builds over the same input yield the
    same generation identity.
    """

    del (
        projection_name,
        last_ledger_event_digest,
    )  # envelope fields come from projection
    return GraphProjectionManifest(
        schema_version=projection.schema_version,
        generation_id=generation_id,
        input_sha256=projection.input_sha256,
        ledger_watermark=projection.ledger_watermark,
        ledger_head_sha256=projection.ledger_head_sha256,
        node_count=len(projection.nodes),
        edge_count=len(projection.edges),
        projection_algorithm=projection.projection_algorithm,
        database_sha256=_database_digest(database_path_str),
        status="closed",
    )


def _database_digest(database_path_str: str) -> str | None:
    if not database_path_str:
        return None
    try:
        from pathlib import Path

        return sha256_hex(Path(database_path_str).read_bytes())
    except OSError:
        return None


__all__ = [
    "ApplyError",
    "ApplyResult",
    "apply_projection",
    "build_graph_manifest",
]
