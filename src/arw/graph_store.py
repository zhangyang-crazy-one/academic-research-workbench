"""Disposable SQLite graph generations and bounded read-only evidence traces."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from arw.canonical import canonical_json_bytes, strict_json_loads
from arw.graph_models import (
    GraphProjectionInput,
    GraphProjectionManifest,
    GraphProjectionReceipt,
    GraphQueryRequest,
    GraphQueryResult,
)


class GraphStoreError(RuntimeError):
    """A selected graph generation is missing, stale, or corrupt."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


@dataclass(frozen=True)
class SelectedGraphGeneration:
    generation_id: str
    generation_root: Path
    manifest_path: Path
    database_path: Path
    manifest: GraphProjectionManifest


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    os.replace(temporary, path)
    _fsync_directory(path.parent)


class GraphStore:
    """Parent-owned generation publisher plus a read-only query adapter."""

    def __init__(self, control_root: Path, root_id: str) -> None:
        self.control_root = control_root.resolve()
        self.root_id = root_id
        self.root_control = self.control_root / "roots" / root_id
        self.generations = self.root_control / "generations"
        self.receipts = self.root_control / "receipts"
        self.selected_path = self.root_control / "selected-generation.json"

    def _generation_id(self) -> str:
        return f"graph-generation-{uuid.uuid4().hex[:16]}"

    def _receipt_for(self, generation_id: str) -> GraphProjectionReceipt | None:
        path = self.receipts / f"{generation_id}.json"
        if path.is_symlink() or not path.is_file():
            return None
        try:
            raw = path.read_bytes()
            value = strict_json_loads(raw)
            receipt = GraphProjectionReceipt.model_validate(value, strict=True)
            if canonical_json_bytes(receipt.model_dump(mode="json")) != raw:
                return None
            return receipt
        except (OSError, UnicodeError, ValueError, ValidationError):
            return None

    def build(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        """Build a sibling SQLite generation and atomically select it."""

        self.generations.mkdir(parents=True, exist_ok=True)
        self.receipts.mkdir(parents=True, exist_ok=True)
        previous = self.selected_generation()
        if previous is not None and previous.manifest.input_sha256 == projection.input_sha256:
            receipt = self._receipt_for(previous.generation_id)
            if receipt is not None and receipt.status == "PASS":
                return receipt
        generation_id = self._generation_id()
        candidate = self.generations / f".building-{generation_id}"
        final = self.generations / generation_id
        candidate.mkdir()
        try:
            input_bytes = projection.canonical_bytes()
            _atomic_write(candidate / "projection-input.json", input_bytes)
            database = candidate / "graph.sqlite3"
            connection = sqlite3.connect(database)
            try:
                connection.executescript(
                    """
                    PRAGMA journal_mode=DELETE;
                    PRAGMA foreign_keys=ON;
                    CREATE TABLE nodes (
                      entity_type TEXT NOT NULL,
                      entity_id TEXT PRIMARY KEY,
                      source_digest TEXT NOT NULL,
                      payload_digest TEXT NOT NULL,
                      supersession_state TEXT NOT NULL,
                      ledger_watermark INTEGER NOT NULL,
                      attributes_json TEXT NOT NULL
                    );
                    CREATE TABLE edges (
                      edge_type TEXT NOT NULL,
                      from_entity_id TEXT NOT NULL,
                      to_entity_id TEXT NOT NULL,
                      evidence_digest TEXT NOT NULL,
                      source_digest TEXT NOT NULL,
                      supersession_state TEXT NOT NULL,
                      ledger_watermark INTEGER NOT NULL,
                      attributes_json TEXT NOT NULL,
                      PRIMARY KEY(edge_type, from_entity_id, to_entity_id, evidence_digest),
                      FOREIGN KEY(from_entity_id) REFERENCES nodes(entity_id),
                      FOREIGN KEY(to_entity_id) REFERENCES nodes(entity_id)
                    );
                    CREATE INDEX edges_from_idx ON edges(from_entity_id);
                    CREATE INDEX edges_to_idx ON edges(to_entity_id);
                    """
                )
                connection.executemany(
                    "INSERT INTO nodes VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            node.entity_type,
                            node.entity_id,
                            node.source_digest,
                            node.payload_digest,
                            node.supersession_state,
                            node.ledger_watermark,
                            json.dumps(node.attributes, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                        )
                        for node in projection.nodes
                    ],
                )
                connection.executemany(
                    "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    [
                        (
                            edge.edge_type,
                            edge.from_entity_id,
                            edge.to_entity_id,
                            edge.evidence_digest,
                            edge.source_digest,
                            edge.supersession_state,
                            edge.ledger_watermark,
                            json.dumps(edge.attributes, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                        )
                        for edge in projection.edges
                    ],
                )
                connection.commit()
                integrity = connection.execute("PRAGMA integrity_check").fetchone()
                if integrity != ("ok",):
                    raise GraphStoreError("generation_integrity_blocked", "SQLite integrity check failed")
            finally:
                connection.close()
            database_digest = _sha256(database)
            manifest = GraphProjectionManifest(
                schema_version="1.0.0",
                generation_id=generation_id,
                input_sha256=projection.input_sha256,
                ledger_watermark=projection.ledger_watermark,
                ledger_head_sha256=projection.ledger_head_sha256,
                node_count=len(projection.nodes),
                edge_count=len(projection.edges),
                projection_algorithm=projection.projection_algorithm,
                database_sha256=database_digest,
                status="closed",
            )
            manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json"))
            _atomic_write(candidate / "generation-manifest.json", manifest_bytes)
            os.replace(candidate, final)
            _fsync_directory(self.generations)
            receipt = GraphProjectionReceipt(
                schema_version="1.0.0",
                root_id=self.root_id,
                candidate_generation_id=generation_id,
                previous_generation_id=previous.generation_id if previous else None,
                selected_generation_id=generation_id,
                projection_manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                input_sha256=projection.input_sha256,
                ledger_watermark=projection.ledger_watermark,
                status="PASS",
                reason_codes=[],
            )
            _atomic_write(
                self.receipts / f"{generation_id}.json",
                canonical_json_bytes(receipt.model_dump(mode="json")),
            )
            pointer = {
                "schema_version": "1.0.0",
                "root_id": self.root_id,
                "generation_id": generation_id,
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            }
            _atomic_write(self.selected_path, canonical_json_bytes(pointer))
            return receipt
        except Exception:
            if candidate.exists():
                for child in candidate.rglob("*"):
                    if child.is_file():
                        child.unlink()
                for child in sorted(candidate.rglob("*"), reverse=True):
                    if child.is_dir():
                        child.rmdir()
                candidate.rmdir()
            raise

    def build_full(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        """Build a complete projection from the canonical input bundle."""

        return self.build(projection)

    def build_incremental(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        """Build from a newer canonical watermark without mutating the prior generation."""

        previous = self.selected_generation()
        if previous is not None and projection.ledger_watermark < previous.manifest.ledger_watermark:
            raise GraphStoreError(
                "projection_stale",
                "incremental input watermark is older than the selected generation",
            )
        return self.build(projection)

    def delete_and_rebuild(self, projection: GraphProjectionInput) -> GraphProjectionReceipt:
        """Publish a replacement, then remove the old disposable generation."""

        previous = self.selected_generation()
        receipt = self.build(projection)
        if previous is not None and previous.generation_id != receipt.selected_generation_id:
            shutil.rmtree(previous.generation_root, ignore_errors=False)
            _fsync_directory(self.generations)
        return receipt

    def delete_selected_generation(self) -> None:
        """Explicitly remove the selected disposable index; never used by queries."""

        selected = self.selected_generation()
        if selected is None:
            return
        if self.selected_path.exists():
            self.selected_path.unlink()
        shutil.rmtree(selected.generation_root, ignore_errors=False)
        _fsync_directory(self.generations)

    def selected_generation(self) -> SelectedGraphGeneration | None:
        if not self.selected_path.exists():
            return None
        if self.selected_path.is_symlink():
            raise GraphStoreError("projection_corrupt", "selected graph pointer is a symlink")
        try:
            raw = self.selected_path.read_bytes()
            pointer = strict_json_loads(raw)
            if canonical_json_bytes(pointer) != raw or not isinstance(pointer, dict):
                raise GraphStoreError("projection_corrupt", "selected graph pointer is not canonical")
            if pointer.get("root_id") != self.root_id or not isinstance(pointer.get("generation_id"), str):
                raise GraphStoreError("projection_corrupt", "selected graph pointer root binding is invalid")
            generation_id = pointer["generation_id"]
            root = self.generations / generation_id
            if root.is_symlink() or not root.is_dir():
                raise GraphStoreError("projection_unavailable", "selected graph generation is missing")
            manifest_path = root / "generation-manifest.json"
            database_path = root / "graph.sqlite3"
            if manifest_path.is_symlink() or database_path.is_symlink() or not manifest_path.is_file() or not database_path.is_file():
                raise GraphStoreError("projection_unavailable", "selected graph generation files are missing")
            manifest_raw = manifest_path.read_bytes()
            manifest = GraphProjectionManifest.model_validate(strict_json_loads(manifest_raw))
            manifest_digest = hashlib.sha256(manifest_raw).hexdigest()
            if manifest_digest != pointer.get("manifest_sha256") or manifest.generation_id != generation_id or manifest.status != "closed":
                raise GraphStoreError("projection_corrupt", "selected graph manifest binding is invalid")
            if manifest.database_sha256 != _sha256(database_path):
                raise GraphStoreError("projection_corrupt", "selected graph database digest mismatch")
            self._validate_counts(database_path, manifest)
            return SelectedGraphGeneration(generation_id, root, manifest_path, database_path, manifest)
        except GraphStoreError:
            raise
        except (OSError, UnicodeError, ValueError, ValidationError, sqlite3.Error) as error:
            raise GraphStoreError("projection_corrupt", f"selected graph generation is invalid: {error}") from error

    @staticmethod
    def _validate_counts(database_path: Path, manifest: GraphProjectionManifest) -> None:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity != ("ok",):
                raise GraphStoreError("projection_corrupt", "selected graph database failed integrity check")
            nodes = connection.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            edges = connection.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            if nodes != manifest.node_count or edges != manifest.edge_count:
                raise GraphStoreError("projection_corrupt", "selected graph counts differ from manifest")
        finally:
            connection.close()

    def query(self, request: GraphQueryRequest) -> GraphQueryResult:
        try:
            selected = self.selected_generation()
        except GraphStoreError as error:
            return self._error_result(request, error.code, str(error))
        if selected is None:
            return self._error_result(request, "projection_unavailable", "no graph generation is selected")
        if request.expected_ledger_watermark is not None and request.expected_ledger_watermark != selected.manifest.ledger_watermark:
            return self._error_result(request, "projection_stale", "selected graph watermark differs from request")
        deadline = time.monotonic() + request.timeout_ms / 1000
        try:
            connection = sqlite3.connect(f"file:{selected.database_path}?mode=ro", uri=True)
            try:
                if request.operation == "graph_health":
                    rows = [{
                        "generation_id": selected.generation_id,
                        "ledger_watermark": selected.manifest.ledger_watermark,
                        "node_count": selected.manifest.node_count,
                        "edge_count": selected.manifest.edge_count,
                    }]
                else:
                    rows = self._trace(connection, request, deadline)
            finally:
                connection.close()
            encoded = canonical_json_bytes(rows)
            if len(encoded) > request.max_bytes:
                return self._error_result(request, "query_budget_exceeded", "query result exceeds byte ceiling")
            return GraphQueryResult(
                schema_version="1.0.0",
                operation=request.operation,
                status="ok",
                projection_generation_id=selected.generation_id,
                projection_manifest_sha256=hashlib.sha256(selected.manifest_path.read_bytes()).hexdigest(),
                ledger_watermark=selected.manifest.ledger_watermark,
                rows=rows[: request.max_rows],
                next_cursor=None,
                reason_code=None,
            )
        except GraphStoreError as error:
            return self._error_result(request, error.code, str(error))
        except sqlite3.Error as error:
            return self._error_result(request, "projection_corrupt", f"read-only graph query failed: {error}")

    @staticmethod
    def _trace(connection: sqlite3.Connection, request: GraphQueryRequest, deadline: float) -> list[dict[str, Any]]:
        if request.entity_id is None:
            raise GraphStoreError("invalid_query", "trace operation requires entity_id")
        allowed: dict[str, set[str]] = {
            "trace_claim": {"supported_by", "uses_dataset", "uses_experiment", "uses_figure", "corrects", "supersedes", "derived_from"},
            "trace_source": {"supported_by", "derived_from", "supersedes"},
            "trace_experiment": {"uses_experiment", "derived_from", "supersedes"},
            "trace_review": {"reviews", "dissent_for", "synthesizes", "evidenced_by", "supersedes"},
            "trace_gate_evidence": {"evidenced_by", "requires", "supersedes"},
        }
        if request.operation not in allowed:
            raise GraphStoreError("invalid_query", "operation is not a trace operation")
        pending = [(request.entity_id, 0)]
        visited = {request.entity_id}
        rows: list[dict[str, Any]] = []
        while pending:
            if time.monotonic() > deadline:
                raise GraphStoreError("query_timeout", "graph query exceeded its deadline")
            entity_id, depth = pending.pop(0)
            node = connection.execute(
                "SELECT entity_type, entity_id, source_digest, payload_digest, supersession_state, ledger_watermark, attributes_json FROM nodes WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
            if node is None:
                raise GraphStoreError("entity_not_found", "requested graph entity is not present")
            relationships: list[dict[str, Any]] = []
            outgoing = connection.execute(
                "SELECT edge_type, to_entity_id, evidence_digest, supersession_state, ledger_watermark "
                "FROM edges WHERE from_entity_id = ? ORDER BY edge_type, to_entity_id LIMIT ?",
                (entity_id, request.max_fanout + 1),
            ).fetchall()
            incoming = connection.execute(
                "SELECT edge_type, from_entity_id, evidence_digest, supersession_state, ledger_watermark "
                "FROM edges WHERE to_entity_id = ? ORDER BY edge_type, from_entity_id LIMIT ?",
                (entity_id, request.max_fanout + 1),
            ).fetchall()
            if len(outgoing) > request.max_fanout or len(incoming) > request.max_fanout:
                raise GraphStoreError("query_budget_exceeded", "edge fanout exceeds the server ceiling")
            for edge_type, target, evidence_digest, state, watermark in outgoing:
                relationships.append({
                    "direction": "outgoing",
                    "edge_type": edge_type,
                    "entity_id": target,
                    "evidence_digest": evidence_digest,
                    "supersession_state": state,
                    "ledger_watermark": watermark,
                })
            for edge_type, source, evidence_digest, state, watermark in incoming:
                relationships.append({
                    "direction": "incoming",
                    "edge_type": edge_type,
                    "entity_id": source,
                    "evidence_digest": evidence_digest,
                    "supersession_state": state,
                    "ledger_watermark": watermark,
                })
            rows.append({
                "entity_type": node[0],
                "entity_id": node[1],
                "source_digest": node[2],
                "payload_digest": node[3],
                "supersession_state": node[4],
                "ledger_watermark": node[5],
                "attributes": strict_json_loads(node[6]),
                "relationships": sorted(relationships, key=lambda item: (item["direction"], item["edge_type"], item["entity_id"])),
            })
            if depth >= request.max_depth:
                continue
            for relationship in relationships:
                target = relationship["entity_id"]
                if relationship["edge_type"] not in allowed[request.operation] or target in visited:
                    continue
                visited.add(target)
                pending.append((target, depth + 1))
                if len(visited) >= request.max_rows:
                    return rows
        return rows

    @staticmethod
    def _error_result(request: GraphQueryRequest, code: str, message: str) -> GraphQueryResult:
        status = code if code in {"projection_stale", "projection_corrupt", "projection_unavailable"} else "projection_unavailable"
        return GraphQueryResult(
            schema_version="1.0.0",
            operation=request.operation,
            status=status,
            projection_generation_id=None,
            projection_manifest_sha256=None,
            ledger_watermark=None,
            rows=[],
            next_cursor=None,
            reason_code=code,
        )
