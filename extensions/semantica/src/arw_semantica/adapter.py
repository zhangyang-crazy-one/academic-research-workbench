"""SQLite-backed, Semantica-inspired accountability projection.

This extension intentionally implements only the reviewed Semantica
provenance subset: record checksum, source/agent/activity attribution, and
bounded lineage.  It has no embedding, graph-server, REST/MCP, or UI imports.
Its database is a disposable sidecar; ARW's canonical ledger remains the only
source of authority.
"""

from __future__ import annotations

import json
import sqlite3
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from arw.graph_models import (
    GraphProjectionInput,
    GraphProjectionReceipt,
    GraphQueryRequest,
    GraphQueryResult,
)
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.ports.knowledge import KnowledgeProvider, NullKnowledgeProvider


def _json_value(value: str | bytes) -> object:
    """Parse a sidecar value, turning corrupt JSON into a typed read failure."""

    try:
        return json.loads(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError("corrupt Semantica sidecar JSON") from error


class UnboundProvenanceError(ValueError):
    """Raised when a record lacks a verified ARW artifact/ledger binding."""


@dataclass(frozen=True)
class ProvenanceRecord:
    """One Lite-profile provenance assertion.

    ``ledger_event_id`` and ``ledger_event_digest`` identify the canonical
    ARW event that admitted this assertion.  Their presence is validated
    before the record reaches this rebuildable sidecar.
    """

    record_id: str
    entity_id: str
    entity_type: str
    artifact_id: str
    ledger_event_id: str
    ledger_event_digest: str
    activity_id: str
    agent_id: str
    created_at: str
    derived_from: tuple[str, ...] = ()
    attributes: Mapping[str, object] | None = None

    def canonical_payload(self) -> dict[str, object]:
        return {
            "activity_id": self.activity_id,
            "agent_id": self.agent_id,
            "artifact_id": self.artifact_id,
            "attributes": dict(self.attributes or {}),
            "created_at": self.created_at,
            "derived_from": list(self.derived_from),
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "ledger_event_digest": self.ledger_event_digest,
            "ledger_event_id": self.ledger_event_id,
            "record_id": self.record_id,
        }

    @property
    def checksum(self) -> str:
        return sha256_hex(canonical_json_bytes(self.canonical_payload()))


class SemanticaSQLiteAdapter:
    """KnowledgeProvider delegate plus a canonical-bound provenance sidecar.

    ``canonical_event_digests`` is a mapping produced from replay-validated
    ARW events. A record is accepted only when its exact id/digest pair is
    present in that mapping. This prevents a valid sidecar checksum from being
    mistaken for canonical acceptance.
    """

    def __init__(
        self,
        database_path: Path,
        *,
        canonical_event_digests: Mapping[str, str],
        accepted_artifact_ids_by_event: Mapping[str, tuple[str, ...]],
        audit_database_path: Path | None = None,
        graph_provider: KnowledgeProvider | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._canonical_event_digests = dict(canonical_event_digests)
        self._accepted_artifact_ids_by_event = {
            event_id: frozenset(artifact_ids)
            for event_id, artifact_ids in accepted_artifact_ids_by_event.items()
        }
        self._audit_database_path = audit_database_path or self._database_path
        self._graph_delegate = graph_provider or NullKnowledgeProvider()
        self._initialize()

    # KnowledgeProvider: graph semantics remain owned by the supplied,
    # replaceable graph provider. The Semantica sidecar adds accountability.
    def build_full(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        return self._graph_delegate.build_full(projection)

    def build_incremental(
        self, projection: GraphProjectionInput
    ) -> GraphProjectionReceipt:
        return self._graph_delegate.build_incremental(projection)

    def delete_and_rebuild(
        self, projection: GraphProjectionInput
    ) -> GraphProjectionReceipt:
        return self._graph_delegate.delete_and_rebuild(projection)

    def query(self, request: GraphQueryRequest) -> GraphQueryResult:
        return self._graph_delegate.query(request)

    def record(self, record: ProvenanceRecord) -> str:
        """Validate bindings, then atomically persist and return checksum."""

        self._validate_binding(record)
        payload = canonical_json_bytes(record.canonical_payload())
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO provenance_records(
                        record_id, entity_id, entity_type, artifact_id,
                        ledger_event_id, ledger_event_digest, activity_id,
                        agent_id, created_at, derived_from_json, payload,
                        checksum
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(record_id) DO UPDATE SET
                        entity_id = excluded.entity_id,
                        entity_type = excluded.entity_type,
                        artifact_id = excluded.artifact_id,
                        ledger_event_id = excluded.ledger_event_id,
                        ledger_event_digest = excluded.ledger_event_digest,
                        activity_id = excluded.activity_id,
                        agent_id = excluded.agent_id,
                        created_at = excluded.created_at,
                        derived_from_json = excluded.derived_from_json,
                        payload = excluded.payload,
                        checksum = excluded.checksum
                    """,
                    (
                        record.record_id,
                        record.entity_id,
                        record.entity_type,
                        record.artifact_id,
                        record.ledger_event_id,
                        record.ledger_event_digest,
                        record.activity_id,
                        record.agent_id,
                        record.created_at,
                        json.dumps(list(record.derived_from), separators=(",", ":")),
                        payload,
                        record.checksum,
                    ),
                )
                connection.commit()
        except sqlite3.Error as error:
            raise RuntimeError(f"semantica sidecar write failed: {error}") from error
        return record.checksum

    def lineage(
        self, entity_id: str, *, max_depth: int = 8, max_rows: int = 100
    ) -> list[dict[str, object]]:
        """Return bounded ancestors in deterministic breadth-first order."""

        if max_depth < 0 or max_depth > 8 or max_rows < 1 or max_rows > 500:
            raise ValueError("lineage bounds are outside the Lite profile limits")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_id, payload, checksum FROM provenance_records ORDER BY record_id"
            ).fetchall()
        by_entity: dict[
            str, list[tuple[str, tuple[str, ...], dict[str, object], str]]
        ] = {}
        for record_id, payload, checksum in rows:
            payload_bytes = bytes(payload)
            if sha256_hex(payload_bytes) != str(checksum):
                raise RuntimeError(f"corrupt Semantica payload for {record_id}")
            record_value = _json_value(payload_bytes)
            if not isinstance(record_value, dict):
                raise RuntimeError(f"corrupt Semantica payload for {record_id}")
            payload_record_id = record_value.get("record_id")
            stored_entity_id = record_value.get("entity_id")
            parents_value = record_value.get("derived_from")
            if (
                not isinstance(payload_record_id, str)
                or payload_record_id != str(record_id)
                or not isinstance(stored_entity_id, str)
                or not isinstance(parents_value, list)
                or not all(isinstance(parent, str) for parent in parents_value)
            ):
                raise RuntimeError(f"corrupt Semantica lineage payload for {record_id}")
            by_entity.setdefault(stored_entity_id, []).append(
                (payload_record_id, tuple(parents_value), record_value, str(checksum))
            )
        queue: deque[tuple[str, int]] = deque([(entity_id, 0)])
        visited: set[str] = set()
        results: list[dict[str, object]] = []
        while queue and len(results) < max_rows:
            current, depth = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            for record_id, parents, record_value, checksum in by_entity.get(current, []):
                if len(results) >= max_rows:
                    break
                results.append(
                    {
                        "checksum": checksum,
                        "depth": depth,
                        "entity_id": current,
                        "record": record_value,
                        "record_id": record_id,
                    }
                )
                if depth < max_depth and len(results) < max_rows:
                    queue.extend((parent, depth + 1) for parent in parents)
        return results

    def decision_chain(
        self, entity_id: str, *, max_depth: int = 8, max_rows: int = 100
    ) -> list[dict[str, object]]:
        """Return lineage entries whose entities are decision assertions."""

        rows = self.lineage(entity_id, max_depth=max_depth, max_rows=max_rows)
        decisions: list[dict[str, object]] = []
        for row in rows:
            record = row.get("record")
            if (
                isinstance(record, dict)
                and str(record.get("entity_type", "")).lower() == "decision"
            ):
                decisions.append(row)
        return decisions

    def verify(self) -> tuple[object, ...]:
        """Detect tampering and persist a non-authoritative audit receipt."""

        from arw_ext.local_store.receipts import AuditFault, persist_audit_fault

        faults: list[AuditFault] = []
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT record_id, payload, checksum FROM provenance_records ORDER BY record_id"
            ).fetchall()
        for record_id, payload, stored_checksum in rows:
            payload_bytes = payload if isinstance(payload, bytes) else None
            checksum_matches = (
                payload_bytes is not None
                and sha256_hex(payload_bytes) == str(stored_checksum)
            )
            if checksum_matches:
                continue
            detail = (
                "payload has a non-BLOB SQLite storage class"
                if payload_bytes is None
                else "checksum mismatch"
            )
            fault = AuditFault(
                code="semantica_checksum_mismatch",
                message=f"Semantica provenance record {record_id} {detail}",
                affected_rows=1,
                projection_name="knowledge.provenance",
                receipt_id=(
                    f"semantica-{sha256_hex(str(record_id).encode('utf-8'))[:24]}"
                ),
            )
            persist_audit_fault(self._audit_database_path, fault)
            faults.append(fault)
        return tuple(faults)

    def _validate_binding(self, record: ProvenanceRecord) -> None:
        if not record.artifact_id:
            raise UnboundProvenanceError("provenance record has no ARW artifact id")
        if not record.ledger_event_id or not record.ledger_event_digest:
            raise UnboundProvenanceError("provenance record has no ARW ledger binding")
        expected = self._canonical_event_digests.get(record.ledger_event_id)
        if expected != record.ledger_event_digest:
            raise UnboundProvenanceError(
                "provenance ledger binding is absent from the canonical event stream"
            )
        accepted_artifacts = self._accepted_artifact_ids_by_event.get(
            record.ledger_event_id, frozenset()
        )
        if record.artifact_id not in accepted_artifacts:
            raise UnboundProvenanceError(
                "provenance artifact is not accepted by its canonical ledger event"
            )

    def _initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS provenance_records (
                    record_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    artifact_id TEXT NOT NULL,
                    ledger_event_id TEXT NOT NULL,
                    ledger_event_digest TEXT NOT NULL,
                    activity_id TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    derived_from_json TEXT NOT NULL,
                    payload BLOB NOT NULL,
                    checksum TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS provenance_records_entity_idx "
                "ON provenance_records(entity_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS provenance_records_ledger_idx "
                "ON provenance_records(ledger_event_id)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._database_path), timeout=5.0)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection
