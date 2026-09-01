"""record_checksum verification pass (D3-amended task 5.2).

``verify_checksums(connection)`` walks every assertion + provenance row and
recomputes its ``record_checksum`` from the canonical byte span defined in
``openspec/changes/sqlite-projection-store/design.md`` (D3-amended, "record
checksum canonical byte span").  Any mismatch is returned as an
:class:`AuditFault` — the apply path NEVER silently drops mismatched rows
and the verify path NEVER mutates the DB.

This is a thin reader; the apply path uses the same byte-span helpers
(:func:`arw_ext.local_store.apply._node_identity_subset`,
:func:`arw_ext.local_store.apply._edge_identity_subset`,
:func:`arw_ext.local_store.apply._provenance_identity_subset`).  Reusing
them keeps the wire contract single-sourced.
"""

from __future__ import annotations

import sqlite3

from arw.kernel.core.canonical import sha256_hex

from .apply import (
    _edge_identity_subset,
    _node_identity_subset,
    _provenance_identity_subset,
)
from .receipts import AuditFault

GRAPH_SCHEMA_VERSION = "1.0.0"


def verify_checksums(
    connection: sqlite3.Connection,
    *,
    projection_name: str = "knowledge",
) -> tuple[AuditFault, ...]:
    """Return one AuditFault per mismatched assertion or provenance row.

    The function never raises on mismatch — the apply / verify contract is
    that projection admission is canonical-by-construction and the verify
    pass records drift without rejecting the row.
    """

    faults: list[AuditFault] = []
    cursor = connection.cursor()

    # -------- assertions (nodes) --------
    rows = cursor.execute(
        """
        SELECT assertion_id, entity_type, entity_id, edge_type, supersession_state,
               source_digest, ledger_watermark, record_checksum
        FROM assertions
        WHERE edge_type IS NULL
        """
    ).fetchall()
    for row in rows:
        (
            assertion_id,
            entity_type,
            entity_id,
            _edge_type,
            supersession_state,
            source_digest,
            watermark,
            stored_checksum,
        ) = row
        payload_digest = cursor.execute(
            "SELECT payload_digest FROM nodes WHERE entity_id = ?",
            (entity_id,),
        ).fetchone()
        if payload_digest is None:
            faults.append(
                AuditFault(
                    code="checksum_missing_node",
                    message=f"assertion {assertion_id} references missing node {entity_id}",
                    affected_rows=1,
                    projection_name=projection_name,
                )
            )
            continue
        payload_digest = payload_digest[0]
        expected = sha256_hex(
            _node_identity_subset(
                schema_version=GRAPH_SCHEMA_VERSION,
                entity_type=entity_type,
                entity_id=entity_id,
                source_digest=source_digest,
                payload_digest=payload_digest,
                supersession_state=supersession_state,
                ledger_watermark=watermark,
            )
        )
        if expected != stored_checksum:
            faults.append(
                AuditFault(
                    code="checksum_mismatch",
                    message=(
                        f"assertion {assertion_id} ({entity_id}) record_checksum mismatch: "
                        f"stored={stored_checksum}, recomputed={expected}"
                    ),
                    affected_rows=1,
                    projection_name=projection_name,
                )
            )

    # -------- assertions (edges) --------
    rows = cursor.execute(
        """
        SELECT a.assertion_id, a.edge_type, a.entity_id, a.supersession_state,
               a.source_digest, a.ledger_watermark, a.record_checksum,
               e.evidence_digest, e.from_entity_id, e.to_entity_id
        FROM assertions a
        JOIN edges e
          ON e.edge_type = a.edge_type
         AND e.from_entity_id || '->' || e.to_entity_id || ':' || e.evidence_digest
             = SUBSTR(a.entity_id, INSTR(a.entity_id, ':') + 1)
        WHERE a.edge_type IS NOT NULL
        """
    ).fetchall()
    for row in rows:
        (
            assertion_id,
            edge_type,
            _entity_id,
            supersession_state,
            source_digest,
            watermark,
            stored_checksum,
            evidence_digest,
            from_id,
            to_id,
        ) = row
        edge_node_or_edge_id = f"{edge_type}:{from_id}->{to_id}:{evidence_digest}"
        expected = sha256_hex(
            _edge_identity_subset(
                schema_version=GRAPH_SCHEMA_VERSION,
                edge_type=edge_type,
                from_entity_id=from_id,
                to_entity_id=to_id,
                evidence_digest=evidence_digest,
                source_digest=source_digest,
                supersession_state=supersession_state,
                ledger_watermark=watermark,
            )
        )
        if expected != stored_checksum:
            faults.append(
                AuditFault(
                    code="checksum_mismatch",
                    message=(
                        f"assertion {assertion_id} (edge {edge_node_or_edge_id}) "
                        f"record_checksum mismatch: stored={stored_checksum}, "
                        f"recomputed={expected}"
                    ),
                    affected_rows=1,
                    projection_name=projection_name,
                )
            )

    # -------- provenance --------
    rows = cursor.execute(
        """
        SELECT provenance_id, assertion_id, node_or_edge_id, source_digest,
               record_checksum
        FROM provenance
        """
    ).fetchall()
    for row in rows:
        provenance_id, assertion_id, node_or_edge_id, source_digest, stored_checksum = (
            row
        )
        expected = sha256_hex(
            _provenance_identity_subset(
                schema_version=GRAPH_SCHEMA_VERSION,
                provenance_id=provenance_id,
                assertion_id=assertion_id,
                node_or_edge_id=node_or_edge_id,
                source_digest=source_digest,
            )
        )
        if expected != stored_checksum:
            faults.append(
                AuditFault(
                    code="checksum_mismatch",
                    message=(
                        f"provenance {provenance_id} record_checksum mismatch: "
                        f"stored={stored_checksum}, recomputed={expected}"
                    ),
                    affected_rows=1,
                    projection_name=projection_name,
                )
            )

    return tuple(faults)


__all__ = ["verify_checksums"]
