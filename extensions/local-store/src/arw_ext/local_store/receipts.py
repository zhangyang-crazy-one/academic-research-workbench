"""Receipt + audit-fault persistence for the local projection store.

The v1 graph_store persists ``GraphProjectionReceipt`` documents as sibling
JSON files under ``receipts/{generation_id}.json``.  This module mirrors the
shape: receipts and audit faults are written atomically into
``<database_path>.receipts/`` and ``<database_path>.audit/`` respectively.
The directory is sibling to the SQLite file so the DB remains the only
canonical projection store; receipts are *evidence* of operator-visible
projection outcomes.

Receipts are persisted as the canonical JSON bytes produced by
``arw.kernel.core.canonical.canonical_json_bytes`` so any tampering
(including a non-canonical rewrite) makes the file unusable as a receipt.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from arw.graph_models import GraphProjectionReceipt
from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{os.getpid()}.tmp"
    descriptor = os.open(
        str(temporary),
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


def receipts_root(database_path: Path) -> Path:
    """Return the receipts sidecar directory for ``database_path``.

    The directory is sibling to the SQLite file (mirroring v1's
    ``receipts/`` subdirectory layout); the database path's stem + the
    ``.receipts`` suffix forms a deterministic, run-local identity.
    """

    return database_path.with_suffix(database_path.suffix + ".receipts")


def audit_root(database_path: Path) -> Path:
    """Return the audit-fault sidecar directory for ``database_path``."""

    return database_path.with_suffix(database_path.suffix + ".audit")


def persist_receipt(database_path: Path, receipt: GraphProjectionReceipt) -> Path:
    """Persist one receipt as canonical JSON; returns the written path."""

    payload = receipt.model_dump(mode="json")
    bytes_payload = canonical_json_bytes(payload)
    target = receipts_root(database_path) / f"{receipt.candidate_generation_id}.json"
    _atomic_write(target, bytes_payload)
    return target


def load_receipt(
    database_path: Path, generation_id: str
) -> GraphProjectionReceipt | None:
    """Load one receipt by generation id, validating canonical bytes."""

    path = receipts_root(database_path) / f"{generation_id}.json"
    if not path.is_file():
        return None
    raw = path.read_bytes()
    parsed = strict_json_loads(raw)
    if canonical_json_bytes(parsed) != raw:
        return None
    return GraphProjectionReceipt.model_validate(parsed)


def list_receipts(database_path: Path) -> tuple[str, ...]:
    """Return every persisted receipt id (filename stem)."""

    root = receipts_root(database_path)
    if not root.is_dir():
        return ()
    out: list[str] = []
    for child in sorted(root.iterdir()):
        if child.is_file() and child.suffix == ".json":
            out.append(child.stem)
    return tuple(out)


# ---------------------------------------------------------------------------
# Audit fault receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditFault:
    """A non-blocking fault surfaced from the apply / verify path.

    Mirrors a graph-store "reason_code" but is an independently-recorded
    document because the local store tracks many more kinds of fault than
    the v1 store (unbound provenance, checksum drift, schema drift, ...).
    """

    code: str
    message: str
    affected_rows: int
    projection_name: str
    receipt_id: str | None = None


def _serialize_audit_fault(fault: AuditFault) -> bytes:
    payload = {
        "schema_version": "1.0.0",
        "code": fault.code,
        "message": fault.message,
        "affected_rows": fault.affected_rows,
        "projection_name": fault.projection_name,
        "receipt_id": fault.receipt_id,
    }
    return canonical_json_bytes(payload)


def persist_audit_fault(database_path: Path, fault: AuditFault) -> Path:
    """Persist one audit fault as canonical JSON; returns the written path."""

    root = audit_root(database_path)
    root.mkdir(parents=True, exist_ok=True)
    identifier = fault.receipt_id or f"{fault.projection_name}-{fault.code}"
    target = root / f"{identifier}.json"
    _atomic_write(target, _serialize_audit_fault(fault))
    return target


def load_audit_faults(database_path: Path) -> tuple[AuditFault, ...]:
    """Load every persisted audit fault in deterministic (filename) order."""

    root = audit_root(database_path)
    if not root.is_dir():
        return ()
    out: list[AuditFault] = []
    for path in sorted(root.iterdir()):
        if path.suffix != ".json" or not path.is_file():
            continue
        try:
            raw = path.read_bytes()
            value: Mapping[str, object] = strict_json_loads(raw)
        except (OSError, UnicodeError, ValueError):
            continue
        if not isinstance(value, dict):
            continue
        out.append(
            AuditFault(
                code=str(value.get("code", "audit_fault")),
                message=str(value.get("message", "")),
                affected_rows=int(str(value.get("affected_rows", 0))),
                projection_name=str(value.get("projection_name", "knowledge")),
            receipt_id=str(value["receipt_id"])
                if isinstance(value.get("receipt_id"), str)
                else None,
            )
        )
    return tuple(out)


def clear_audit_faults(database_path: Path, *, receipt_id: str | None = None) -> int:
    """Remove audit faults scoped to a receipt (or every fault when None).

    Returns the number of files removed.  Used by rebuild paths so the
    fault log does not carry stale entries from prior receipts.
    """

    root = audit_root(database_path)
    if not root.is_dir():
        return 0
    removed = 0
    for path in list(root.iterdir()):
        if path.suffix != ".json" or not path.is_file():
            continue
        if receipt_id is not None and not path.stem.startswith(receipt_id):
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:
            continue
    if root.exists() and not any(root.iterdir()):
        import contextlib

        with contextlib.suppress(OSError):
            root.rmdir()
    return removed


__all__ = [
    "AuditFault",
    "audit_root",
    "clear_audit_faults",
    "list_receipts",
    "load_audit_faults",
    "load_receipt",
    "persist_audit_fault",
    "persist_receipt",
    "receipts_root",
]
