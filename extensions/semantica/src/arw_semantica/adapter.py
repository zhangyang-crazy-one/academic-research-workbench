"""SQLite-backed, Semantica-inspired accountability projection.

This extension intentionally implements only the reviewed Semantica
provenance subset: record checksum, source/agent/activity attribution, and
bounded lineage.  It has no embedding, graph-server, REST/MCP, or UI imports.
Its database is a disposable sidecar; ARW's canonical ledger remains the only
source of authority.
"""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from collections import deque
from collections.abc import Iterator, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from arw_ext.local_store.location import is_network_filesystem
from arw_ext.local_store.receipts import AuditFault
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
MAX_AUDIT_RECEIPTS = MAX_SIDECAR_RECORDS * 2 + 1


def _open_directory_no_follow(path: Path) -> int:
    """Open an absolute directory by walking from a trusted root descriptor."""
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if not path.is_absolute() or no_follow == 0 or os.open not in os.supports_dir_fd:
        raise OSError("descriptor-relative directory walks are unsupported")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | no_follow
    )
    descriptor = os.open(Path(path.anchor), flags)
    try:
        for component in path.parts[1:]:
            child_descriptor = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child_descriptor
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open_or_create_directory_no_follow(path: Path) -> int:
    try:
        return _open_directory_no_follow(path)
    except FileNotFoundError:
        parent_descriptor = _open_directory_no_follow(path.parent)
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_DIRECTORY", 0)
            | no_follow
        )
        try:
            with suppress(FileExistsError):
                os.mkdir(path.name, mode=0o700, dir_fd=parent_descriptor)
            return os.open(path.name, flags, dir_fd=parent_descriptor)
        finally:
            os.close(parent_descriptor)


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

    schema_version: Literal["1.0.0"]
    record_id: StableRuntimeId
    entity_id: StableRuntimeId
    entity_type: str = Field(min_length=1, max_length=96)
    artifact_id: StableRuntimeId
    ledger_event_id: EventId | None = None
    ledger_event_digest: Sha256 | None = None
    activity_id: StableRuntimeId
    agent_id: ActorId
    created_at: UtcTimestamp
    derived_from: tuple[StableRuntimeId, ...] = Field(max_length=MAX_SIDECAR_RECORDS)
    attributes: dict[str, object]

    def artifact_payload(self) -> dict[str, object]:
        return self.model_dump(
            mode="json", exclude={"ledger_event_id", "ledger_event_digest"}
        )

    def canonical_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json")

    @property
    def checksum(self) -> str:
        return sha256_hex(canonical_json_bytes(self.artifact_payload()))

    @property
    def binding_checksum(self) -> str:
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
        accepted_artifact_sha256_by_event: Mapping[str, str],
        expected_provenance_record_sha256: Mapping[str, str],
        audit_database_path: Path | None = None,
        graph_provider: KnowledgeProvider | None = None,
    ) -> None:
        self._database_path = self._validate_database_path(Path(database_path))
        self._canonical_event_digests = dict(canonical_event_digests)
        self._accepted_artifact_ids_by_event = {
            event_id: frozenset(artifact_ids)
            for event_id, artifact_ids in accepted_artifact_ids_by_event.items()
        }
        self._accepted_artifact_sha256_by_event = dict(
            accepted_artifact_sha256_by_event
        )
        missing_artifact_digests = set(self._accepted_artifact_ids_by_event) - set(
            self._accepted_artifact_sha256_by_event
        )
        if missing_artifact_digests:
            raise ValueError(
                "accepted artifact digests are required for provenance events: "
                + ", ".join(sorted(missing_artifact_digests))
            )
        self._expected_provenance_record_sha256 = dict(
            expected_provenance_record_sha256
        )
        if len(self._expected_provenance_record_sha256) > MAX_SIDECAR_RECORDS:
            raise ValueError("canonical provenance inventory exceeds the Lite limit")
        self._audit_database_path = self._validate_database_path(
            audit_database_path or self._database_path
        )
        audit_directory = Path(f"{self._audit_database_path}.audit")
        if audit_directory.exists():
            audit_status = audit_directory.lstat()
            if not stat.S_ISDIR(audit_status.st_mode) or (
                os.name != "nt" and stat.S_IMODE(audit_status.st_mode) & 0o077
            ):
                raise ValueError(
                    "Semantica audit directory must be a private 0700 directory"
                )
        self._graph_delegate = graph_provider or NullKnowledgeProvider()
        try:
            self._initialize()
        except sqlite3.Error as error:
            raise RuntimeError(
                f"Semantica sidecar initialization failed: {error}"
            ) from error

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
        # pi-lens-ignore: python-sql-injection
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
                    "SELECT CASE WHEN typeof(payload) = 'blob' AND length(payload) <= ? "
                    "THEN payload ELSE NULL END, "
                    "CASE WHEN typeof(checksum) = 'text' "
                    "AND length(CAST(checksum AS BLOB)) = 64 "
                    "THEN checksum ELSE NULL END "
                    "FROM provenance_records WHERE record_id = ?",
                    (MAX_PROVENANCE_PAYLOAD_BYTES, record.record_id),
                ).fetchone()
                if existing is not None:
                    if existing == (payload, record.binding_checksum):
                        connection.commit()
                        return record.checksum
                    raise UnboundProvenanceError(
                        "provenance record ID already binds different immutable content"
                    )
                at_limit = connection.execute(
                    "SELECT 1 FROM provenance_records LIMIT 1 OFFSET ?",
                    (MAX_SIDECAR_RECORDS - 1,),
                ).fetchone()
                if at_limit is not None:
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
                        record.binding_checksum,
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
        observed_record_ids: set[str] = set()
        for index, (record_id, payload, checksum) in enumerate(
            self._records(limit=MAX_SIDECAR_RECORDS + 1)
        ):
            if index == MAX_SIDECAR_RECORDS:
                raise RuntimeError("Semantica lineage exceeds the Lite record limit")
            if not isinstance(payload, bytes):
                raise TypeError(f"corrupt Semantica payload storage for {record_id}")
            if len(payload) > MAX_PROVENANCE_PAYLOAD_BYTES or sha256_hex(
                payload
            ) != str(checksum):
                raise RuntimeError(f"corrupt Semantica payload for {record_id}")
            record_value = _json_value(payload)
            if not isinstance(record_value, dict):
                raise TypeError(f"corrupt Semantica payload for {record_id}")
            if canonical_json_bytes(record_value) != payload:
                raise RuntimeError(
                    f"noncanonical Semantica payload encoding for {record_id}"
                )
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
            artifact_payload = dict(record_value)
            artifact_payload.pop("ledger_event_id", None)
            artifact_payload.pop("ledger_event_digest", None)
            accepted_artifacts = self._accepted_artifact_ids_by_event.get(
                str(event_id), frozenset()
            )
            artifact_sha = sha256_hex(canonical_json_bytes(artifact_payload))
            if (
                self._canonical_event_digests.get(str(event_id)) != event_digest
                or record_value.get("artifact_id") not in accepted_artifacts
                or self._accepted_artifact_sha256_by_event.get(str(event_id))
                != artifact_sha
            ):
                raise RuntimeError(
                    f"Semantica lineage record {payload_record_id} has an "
                    "invalid canonical binding"
                )
            if (
                self._expected_provenance_record_sha256.get(payload_record_id)
                != artifact_sha
            ):
                raise RuntimeError(
                    f"Semantica lineage record {payload_record_id} is outside "
                    "the canonical inventory"
                )
            by_entity.setdefault(stored_entity_id, []).append(
                (payload_record_id, tuple(parents_value), record_value, str(checksum))
            )
            observed_record_ids.add(payload_record_id)
        missing = set(self._expected_provenance_record_sha256) - observed_record_ids
        if missing:
            raise RuntimeError(
                "Semantica sidecar is missing canonical provenance records: "
                + ", ".join(sorted(missing))
            )
        queue: deque[tuple[str, int]] = deque([(entity_id, 0)])
        queued_entity_ids = {entity_id}
        visited: set[str] = set()
        results: list[dict[str, object]] = []
        while queue and len(results) < max_rows:
            current, depth = queue.popleft()
            queued_entity_ids.discard(current)
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
                        if (
                            parent in by_entity
                            and parent not in visited
                            and parent not in queued_entity_ids
                        ):
                            queue.append((parent, depth + 1))
                            queued_entity_ids.add(parent)
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

    def rebuild(self, records: list[ProvenanceRecord]) -> None:
        """Atomically replace this sidecar with fully validated canonical records."""
        if len(records) > MAX_SIDECAR_RECORDS:
            raise ValueError("Semantica sidecar record limit exceeded")
        input_inventory = {record.record_id: record.checksum for record in records}
        if (
            len(input_inventory) != len(records)
            or input_inventory != self._expected_provenance_record_sha256
        ):
            raise ValueError(
                "rebuild input does not match the canonical provenance inventory"
            )
        prepared: list[tuple[object, ...]] = []
        for record in records:
            self._validate_binding(record)
            payload = canonical_json_bytes(record.canonical_payload())
            if len(payload) > MAX_PROVENANCE_PAYLOAD_BYTES:
                raise ValueError(
                    "provenance payload exceeds the Lite profile byte limit"
                )
            prepared.append(
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
                    record.binding_checksum,
                )
            )
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DELETE FROM provenance_records")
                # pi-lens-ignore: python-sql-injection
                connection.executemany(
                    "INSERT INTO provenance_records "
                    "(record_id, entity_id, entity_type, artifact_id, ledger_event_id, "
                    "ledger_event_digest, activity_id, agent_id, created_at, "
                    "derived_from_json, payload, checksum) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    prepared,
                )
                connection.commit()
        except sqlite3.Error as error:
            raise RuntimeError(f"Semantica sidecar rebuild failed: {error}") from error

    def verify(self) -> tuple[object, ...]:
        """Detect tampering and persist a non-authoritative audit receipt."""

        faults: list[AuditFault] = []
        observed_record_ids: set[str] = set()
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
                faults.append(fault)
                break
            observed_record_ids.add(str(record_id))
            payload_bytes = (
                payload
                if isinstance(payload, bytes)
                and len(payload) <= MAX_PROVENANCE_PAYLOAD_BYTES
                else None
            )
            checksum_matches = payload_bytes is not None and sha256_hex(
                payload_bytes
            ) == str(stored_checksum)
            if checksum_matches and payload_bytes is not None:
                try:
                    payload_value = _json_value(payload_bytes)
                    canonical_payload_bytes = canonical_json_bytes(payload_value)
                except (RuntimeError, TypeError, ValueError):
                    payload_value = None
                    canonical_payload_bytes = None
                if (
                    isinstance(payload_value, dict)
                    and canonical_payload_bytes == payload_bytes
                ):
                    artifact_payload = dict(payload_value)
                    artifact_payload.pop("ledger_event_id", None)
                    artifact_payload.pop("ledger_event_digest", None)
                    artifact_sha = sha256_hex(canonical_json_bytes(artifact_payload))
                    event_id = payload_value.get("ledger_event_id")
                    expected_artifact_sha = self._accepted_artifact_sha256_by_event.get(
                        str(event_id)
                    )
                    expected_record_sha = self._expected_provenance_record_sha256.get(
                        str(record_id)
                    )
                    if (
                        payload_value.get("record_id") == str(record_id)
                        and self._canonical_event_digests.get(str(event_id))
                        == payload_value.get("ledger_event_digest")
                        and payload_value.get("artifact_id")
                        in self._accepted_artifact_ids_by_event.get(
                            str(event_id), frozenset()
                        )
                        and expected_artifact_sha == artifact_sha
                        and expected_record_sha == artifact_sha
                    ):
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
            faults.append(fault)
        for missing_record_id in sorted(
            set(self._expected_provenance_record_sha256) - observed_record_ids
        ):
            fault = AuditFault(
                code="semantica_missing_record",
                message=(
                    "Semantica sidecar is missing canonical provenance record "
                    f"{missing_record_id}"
                ),
                affected_rows=1,
                projection_name="knowledge.provenance",
                receipt_id=(
                    "semantica-missing-"
                    + sha256_hex(missing_record_id.encode("utf-8"))[:24]
                ),
            )
            faults.append(fault)
        self._replace_audit_faults(tuple(faults))
        return tuple(faults)

    def _replace_audit_faults(self, faults: tuple[AuditFault, ...]) -> None:
        audit_directory = Path(f"{self._audit_database_path}.audit")
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if no_follow == 0 or os.unlink not in os.supports_dir_fd:
            raise RuntimeError("descriptor-relative audit persistence is unsupported")
        try:
            directory_descriptor = _open_or_create_directory_no_follow(audit_directory)
        except OSError as error:
            raise RuntimeError(
                f"Semantica audit directory open failed: {error}"
            ) from error
        try:
            status = os.fstat(directory_descriptor)
            if not stat.S_ISDIR(status.st_mode):
                raise RuntimeError("Semantica audit path is not a directory")
            if os.name != "nt" and stat.S_IMODE(status.st_mode) & 0o077:
                raise RuntimeError("Semantica audit directory permissions are unsafe")

            current_receipts: set[str] = set()
            for fault in faults:
                payload = canonical_json_bytes(
                    {
                        "schema_version": "1.0.0",
                        "code": fault.code,
                        "message": fault.message,
                        "affected_rows": fault.affected_rows,
                        "projection_name": fault.projection_name,
                        "receipt_id": fault.receipt_id,
                    }
                )
                identifier = fault.receipt_id or (
                    f"{fault.projection_name}-{fault.code}"
                )
                target = (
                    "semantica-"
                    f"{sha256_hex(identifier.encode('utf-8'))[:24]}-"
                    f"{sha256_hex(payload)[:12]}.json"
                )
                temporary = f".{target}.{os.getpid()}.tmp"
                descriptor = os.open(
                    temporary,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | no_follow,
                    0o600,
                    dir_fd=directory_descriptor,
                )
                try:
                    remaining = memoryview(payload)
                    while remaining:
                        written = os.write(descriptor, remaining)
                        if written <= 0:
                            raise OSError("short Semantica audit receipt write")
                        remaining = remaining[written:]
                    os.fsync(descriptor)
                except BaseException:
                    with suppress(OSError):
                        os.unlink(temporary, dir_fd=directory_descriptor)
                    raise
                finally:
                    os.close(descriptor)
                try:
                    os.replace(
                        temporary,
                        target,
                        src_dir_fd=directory_descriptor,
                        dst_dir_fd=directory_descriptor,
                    )
                except BaseException:
                    with suppress(OSError):
                        os.unlink(temporary, dir_fd=directory_descriptor)
                    raise
                current_receipts.add(target)

            with os.scandir(directory_descriptor) as entries:
                for index, entry in enumerate(entries):
                    if index >= MAX_AUDIT_RECEIPTS * 2:
                        raise RuntimeError(
                            "Semantica audit receipt inventory exceeds the Lite limit"
                        )
                    if not (
                        entry.name.startswith("semantica-")
                        and entry.name.endswith(".json")
                    ):
                        continue
                    if entry.is_symlink():
                        raise RuntimeError(
                            "Semantica audit receipt must not be a symlink"
                        )
                    if entry.name not in current_receipts and entry.is_file(
                        follow_symlinks=False
                    ):
                        os.unlink(entry.name, dir_fd=directory_descriptor)
            os.fsync(directory_descriptor)
        except OSError as error:
            raise RuntimeError(
                f"Semantica audit fault reconciliation failed: {error}"
            ) from error
        finally:
            os.close(directory_descriptor)

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
        expected_artifact_sha = self._accepted_artifact_sha256_by_event.get(
            record.ledger_event_id
        )
        if (
            expected_artifact_sha is not None
            and record.checksum != expected_artifact_sha
        ):
            raise UnboundProvenanceError(
                "provenance assertion differs from its accepted artifact content"
            )
        expected_record_sha = self._expected_provenance_record_sha256.get(
            record.record_id
        )
        if expected_record_sha != record.checksum:
            raise UnboundProvenanceError(
                "provenance record is absent from the canonical inventory"
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
        if os.name != "nt" and stat.S_IMODE(candidate.parent.stat().st_mode) & 0o022:
            raise ValueError(
                "Semantica sidecar parent must not be group/world-writable"
            )
        if is_network_filesystem(candidate):
            raise ValueError("Semantica sidecar must not use a network filesystem")
        return candidate

    def _records(self, *, limit: int) -> Iterator[tuple[object, object, object]]:
        try:
            with self._connect() as connection:
                cursor = connection.execute(
                    "SELECT "
                    "CASE WHEN typeof(record_id) = 'text' "
                    "AND length(CAST(record_id AS BLOB)) <= 96 "
                    "THEN record_id ELSE '__arw_invalid_record_id_rowid__' "
                    "|| printf('%016x', rowid) END AS safe_record_id, "
                    "CASE WHEN typeof(payload) = 'blob' AND length(payload) <= ? "
                    "THEN payload ELSE NULL END, "
                    "CASE WHEN typeof(checksum) = 'text' "
                    "AND length(CAST(checksum AS BLOB)) = 64 "
                    "THEN checksum ELSE NULL END "
                    "FROM (SELECT rowid, record_id, payload, checksum "
                    "FROM provenance_records ORDER BY record_id LIMIT ?) AS bounded "
                    "ORDER BY safe_record_id, rowid",
                    (MAX_PROVENANCE_PAYLOAD_BYTES, limit),
                )
                yield from cursor
        except sqlite3.Error as error:
            raise RuntimeError(f"Semantica sidecar read failed: {error}") from error

    def _initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            descriptor = os.open(
                self._database_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            file_status = self._database_path.lstat()
        else:
            os.close(descriptor)
            file_status = self._database_path.lstat()
        if not stat.S_ISREG(file_status.st_mode) or (
            os.name != "nt" and stat.S_IMODE(file_status.st_mode) & 0o077
        ):
            raise ValueError("Semantica sidecar must be a private 0600 regular file")
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
            expected_columns = {
                "record_id": ("TEXT", 0, 1),
                "entity_id": ("TEXT", 1, 0),
                "entity_type": ("TEXT", 1, 0),
                "artifact_id": ("TEXT", 1, 0),
                "ledger_event_id": ("TEXT", 1, 0),
                "ledger_event_digest": ("TEXT", 1, 0),
                "activity_id": ("TEXT", 1, 0),
                "agent_id": ("TEXT", 1, 0),
                "created_at": ("TEXT", 1, 0),
                "derived_from_json": ("TEXT", 1, 0),
                "payload": ("BLOB", 1, 0),
                "checksum": ("TEXT", 1, 0),
            }
            table_info = {
                str(row[1]): (str(row[2]).upper(), row[3], row[5])
                for row in connection.execute(
                    "PRAGMA table_info(provenance_records)"
                ).fetchall()
            }
            if table_info != expected_columns:
                raise sqlite3.DatabaseError(
                    "provenance_records schema constraints are incompatible"
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
        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self._database_path, flags)
        try:
            validated = os.fstat(descriptor)
            if not stat.S_ISREG(validated.st_mode) or (
                os.name != "nt" and stat.S_IMODE(validated.st_mode) & 0o077
            ):
                raise ValueError("Semantica sidecar inode is unsafe")
            fd_aliases = (
                Path(f"/proc/self/fd/{descriptor}"),
                Path(f"/dev/fd/{descriptor}"),
            )
            connection_path = next(
                (alias for alias in fd_aliases if alias.exists()),
                self._database_path,
            )
            connection = sqlite3.connect(
                f"file:{quote(str(connection_path))}?mode=rw",
                uri=True,
                timeout=5.0,
            )
            database_row = connection.execute("PRAGMA database_list").fetchone()
            if database_row is None:
                connection.close()
                raise ValueError("Semantica sidecar connection has no main database")
            opened = Path(str(database_row[2])).stat()
            if (validated.st_dev, validated.st_ino) != (opened.st_dev, opened.st_ino):
                connection.close()
                raise ValueError("Semantica sidecar connection inode mismatch")
        finally:
            os.close(descriptor)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection
