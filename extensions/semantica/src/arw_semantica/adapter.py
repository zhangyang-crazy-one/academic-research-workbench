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
from collections.abc import Iterator, Mapping
from pathlib import Path

from arw_ext.local_store.location import is_network_filesystem
from pydantic import Field

from arw.graph_models import (
    GraphProjectionInput,
    GraphProjectionReceipt,
    GraphQueryRequest,
    GraphQueryResult,
)
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.state.models import (
    ActorId,
    EventId,
    Sha256,
    StableRuntimeId,
    StrictModel,
    UtcTimestamp,
)
from arw.ports.knowledge import KnowledgeProvider, NullKnowledgeProvider

MAX_SIDECAR_RECORDS = 500
MAX_PROVENANCE_PAYLOAD_BYTES = 65_536


def _json_value(value: str | bytes) -> object:
    """Parse a sidecar value, turning corrupt JSON into a typed read failure."""

    try:
        return json.loads(value)
    except (TypeError, ValueError) as error:
        raise RuntimeError("corrupt Semantica sidecar JSON") from error


class UnboundProvenanceError(ValueError):
    """Raised when a record lacks a verified ARW artifact/ledger binding."""


class ProvenanceRecord(StrictModel):
    """One Lite-profile provenance assertion."""

    record_id: StableRuntimeId
    entity_id: StableRuntimeId
    entity_type: str = Field(min_length=1, max_length=96)
    artifact_id: StableRuntimeId
    ledger_event_id: EventId
    ledger_event_digest: Sha256
    activity_id: StableRuntimeId
    agent_id: ActorId
    created_at: UtcTimestamp
    derived_from: tuple[StableRuntimeId, ...] = Field(
        default_factory=tuple, max_length=MAX_SIDECAR_RECORDS
    )
    attributes: dict[str, object] = Field(default_factory=dict)

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

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
        self._database_path = self._validate_database_path(Path(database_path))
        self._canonical_event_digests = dict(canonical_event_digests)
        self._accepted_artifact_ids_by_event = {
            event_id: frozenset(artifact_ids)
            for event_id, artifact_ids in accepted_artifact_ids_by_event.items()
        }
        self._audit_database_path = self._validate_database_path(
            audit_database_path or self._database_path
        )
        audit_directory = Path(f"{self._audit_database_path}.audit")
        if audit_directory.is_symlink():
            raise ValueError("Semantica audit directory must not be a symlink")
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
        if len(payload) > MAX_PROVENANCE_PAYLOAD_BYTES:
            raise ValueError("provenance payload exceeds the Lite profile byte limit")
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT payload, checksum FROM provenance_records WHERE record_id = ?",
                    (record.record_id,),
                ).fetchone()
                if existing is not None:
                    if existing == (payload, record.checksum):
                        connection.commit()
                        return record.checksum
                    raise UnboundProvenanceError(
                        "provenance record ID already binds different immutable content"
                    )
                count = connection.execute(
                    "SELECT COUNT(*) FROM provenance_records"
                ).fetchone()
                if count is None or int(count[0]) >= MAX_SIDECAR_RECORDS:
                    raise ValueError("Semantica sidecar record limit exceeded")
                connection.execute(
                    """
                    INSERT INTO provenance_records(
                        record_id, entity_id, entity_type, artifact_id,
                        ledger_event_id, ledger_event_digest, activity_id,
                        agent_id, created_at, derived_from_json, payload, checksum
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        by_entity: dict[
            str, list[tuple[str, tuple[str, ...], dict[str, object], str]]
        ] = {}
        for record_id, payload, checksum in self._records(limit=MAX_SIDECAR_RECORDS):
            if not isinstance(payload, bytes):
                raise TypeError(f"corrupt Semantica payload storage for {record_id}")
            if len(payload) > MAX_PROVENANCE_PAYLOAD_BYTES or sha256_hex(
                payload
            ) != str(checksum):
                raise RuntimeError(f"corrupt Semantica payload for {record_id}")
            record_value = _json_value(payload)
            if not isinstance(record_value, dict):
                raise TypeError(f"corrupt Semantica payload for {record_id}")
            payload_record_id = record_value.get("record_id")
            stored_entity_id = record_value.get("entity_id")
            parents_value = record_value.get("derived_from")
            event_id = record_value.get("ledger_event_id")
            event_digest = record_value.get("ledger_event_digest")
            if (
                not isinstance(payload_record_id, str)
                or payload_record_id != str(record_id)
                or not isinstance(stored_entity_id, str)
                or not isinstance(parents_value, list)
                or not all(isinstance(parent, str) for parent in parents_value)
            ):
                raise RuntimeError(f"corrupt Semantica lineage payload for {record_id}")
            if self._canonical_event_digests.get(str(event_id)) != event_digest:
                continue
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
            for record_id, parents, record_value, checksum in by_entity.get(
                current, []
            ):
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
                    for parent in parents:
                        if len(queue) + len(results) >= max_rows:
                            break
                        if parent not in visited and parent not in queue:
                            queue.append((parent, depth + 1))
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

    def reset(self) -> None:
        """Atomically clear this run's rebuildable sidecar projection."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM provenance_records")
            connection.commit()

    def verify(self) -> tuple[object, ...]:
        """Detect tampering and persist a non-authoritative audit receipt."""

        from arw_ext.local_store.receipts import AuditFault, persist_audit_fault

        faults: list[AuditFault] = []
        for index, (record_id, payload, stored_checksum) in enumerate(
            self._records(limit=MAX_SIDECAR_RECORDS + 1)
        ):
            if index == MAX_SIDECAR_RECORDS:
                fault = AuditFault(
                    code="semantica_verification_truncated",
                    message="Semantica verification stopped at the Lite record limit",
                    affected_rows=1,
                    projection_name="knowledge.provenance",
                    receipt_id="semantica-verification-truncated",
                )
                persist_audit_fault(self._audit_database_path, fault)
                faults.append(fault)
                break
            payload_bytes = (
                payload
                if isinstance(payload, bytes)
                and len(payload) <= MAX_PROVENANCE_PAYLOAD_BYTES
                else None
            )
            checksum_matches = payload_bytes is not None and sha256_hex(
                payload_bytes
            ) == str(stored_checksum)
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

    @staticmethod
    def _validate_database_path(path: Path) -> Path:
        candidate = path if path.is_absolute() else Path.cwd() / path
        if candidate.is_symlink() or any(
            ancestor.is_symlink() for ancestor in candidate.parents
        ):
            raise ValueError("Semantica sidecar path or ancestor must not be a symlink")
        if not candidate.parent.is_dir():
            raise ValueError("Semantica sidecar parent directory does not exist")
        if is_network_filesystem(candidate):
            raise ValueError("Semantica sidecar must not use a network filesystem")
        return candidate

    def _records(self, *, limit: int) -> Iterator[tuple[object, object, object]]:
        with self._connect() as connection:
            cursor = connection.execute(
                "SELECT record_id, payload, checksum FROM provenance_records "
                "ORDER BY record_id LIMIT ?",
                (limit,),
            )
            yield from cursor

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
