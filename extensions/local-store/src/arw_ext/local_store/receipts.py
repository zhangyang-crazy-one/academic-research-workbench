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
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from arw.graph_models import GraphProjectionManifest, GraphProjectionReceipt
from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)

DEFAULT_MAX_AUDIT_ENTRIES = 4_096
DEFAULT_MAX_AUDIT_RECEIPT_BYTES = 65_536


def _open_directory_no_follow(path: Path) -> int:
    candidate = path if path.is_absolute() else Path.cwd() / path
    no_follow = getattr(os, "O_NOFOLLOW", 0)
    if no_follow == 0 or os.open not in os.supports_dir_fd:
        raise OSError("descriptor-relative directory walks are unsupported")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | no_follow
    )
    descriptor = os.open(Path(candidate.anchor), flags)
    for component in candidate.parts[1:]:
        try:
            child_descriptor = os.open(component, flags, dir_fd=descriptor)
        except OSError:
            os.close(descriptor)
            raise
        os.close(descriptor)
        descriptor = child_descriptor
    return descriptor


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


def persist_manifest(
    database_path: Path, generation_id: str, manifest: GraphProjectionManifest
) -> Path:
    """Persist the generation manifest next to the receipt (query-side
    consistency checks need its ``ledger_head_sha256``)."""

    target = receipts_root(database_path) / f"{generation_id}.manifest.json"
    _atomic_write(target, canonical_json_bytes(manifest.model_dump(mode="json")))
    return target


def load_manifest(
    database_path: Path, generation_id: str
) -> GraphProjectionManifest | None:
    """Load a persisted manifest, rejecting non-canonical bytes."""

    path = receipts_root(database_path) / f"{generation_id}.manifest.json"
    if not path.is_file():
        return None
    raw = path.read_bytes()
    parsed = strict_json_loads(raw)
    if canonical_json_bytes(parsed) != raw:
        return None
    return GraphProjectionManifest.model_validate(parsed)


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
    # Multiple faults from one build share the receipt_id; keying the file by
    # receipt/code alone would overwrite all but the last (review P1).  The
    # content digest keeps each distinct fault while staying idempotent for
    # identical re-emitted faults.
    payload = _serialize_audit_fault(fault)
    identifier = fault.receipt_id or f"{fault.projection_name}-{fault.code}"
    target = root / f"{identifier}-{sha256_hex(payload)[:12]}.json"
    _atomic_write(target, payload)
    return target


def load_audit_faults(
    database_path: Path,
    *,
    max_entries: int = DEFAULT_MAX_AUDIT_ENTRIES,
    max_bytes: int = DEFAULT_MAX_AUDIT_RECEIPT_BYTES,
) -> tuple[AuditFault, ...]:
    """Load bounded audit faults through a no-follow directory descriptor."""
    if max_entries < 1 or max_entries > DEFAULT_MAX_AUDIT_ENTRIES:
        raise ValueError("audit entry bound is outside the supported range")
    if max_bytes < 1 or max_bytes > DEFAULT_MAX_AUDIT_RECEIPT_BYTES:
        raise ValueError("audit receipt byte bound is outside the supported range")
    root = audit_root(database_path)
    candidate = root if root.is_absolute() else Path.cwd() / root
    current = Path(candidate.anchor)
    for component in candidate.parts[1:]:
        current /= component
        try:
            status = current.lstat()
        except FileNotFoundError:
            return ()
        if stat.S_ISLNK(status.st_mode):
            return (
                AuditFault(
                    code="audit_receipt_read_failed",
                    message="audit receipt directory path contains a symlink",
                    affected_rows=1,
                    projection_name="knowledge",
                ),
            )
    root = candidate
    try:
        directory_descriptor = _open_directory_no_follow(root)
    except FileNotFoundError:
        return ()
    except OSError as error:
        return (
            AuditFault(
                code="audit_receipt_read_failed",
                message=f"audit receipt directory is unsafe or unreadable: {error}",
                affected_rows=1,
                projection_name="knowledge",
            ),
        )
    try:
        names: list[str] = []
        with os.scandir(directory_descriptor) as entries:
            for index, entry in enumerate(entries):
                if index >= max_entries:
                    return (
                        AuditFault(
                            code="audit_receipt_inventory_truncated",
                            message="audit receipt inventory exceeds the configured limit",
                            affected_rows=1,
                            projection_name="knowledge",
                        ),
                    )
                if entry.name.endswith(".json"):
                    names.append(entry.name)

        out: list[AuditFault] = []

        def unreadable_fault(name: str) -> AuditFault:
            return AuditFault(
                code="audit_receipt_read_failed",
                message=f"audit receipt {name} is unreadable or malformed",
                affected_rows=1,
                projection_name="knowledge",
                receipt_id=("audit-read-" + sha256_hex(name.encode("utf-8"))[:24]),
            )

        no_follow = getattr(os, "O_NOFOLLOW", 0)
        file_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | no_follow
        )
        for name in sorted(names):
            try:
                descriptor = os.open(name, file_flags, dir_fd=directory_descriptor)
                try:
                    status = os.fstat(descriptor)
                    if not stat.S_ISREG(status.st_mode) or status.st_size > max_bytes:
                        out.append(unreadable_fault(name))
                        continue
                    chunks: list[bytes] = []
                    total = 0
                    while total <= max_bytes:
                        chunk = os.read(descriptor, min(16_384, max_bytes + 1 - total))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        total += len(chunk)
                    if total > max_bytes:
                        out.append(unreadable_fault(name))
                        continue
                    raw = b"".join(chunks)
                finally:
                    os.close(descriptor)
                value: Mapping[str, object] = strict_json_loads(raw)
                canonical_value = canonical_json_bytes(value)
            except (OSError, UnicodeError, ValueError):
                out.append(unreadable_fault(name))
                continue
            if not isinstance(value, dict):
                out.append(unreadable_fault(name))
                continue
            _, separator, filename_digest = name.removesuffix(".json").rpartition("-")
            if (
                not separator
                or filename_digest != sha256_hex(raw)[:12]
                or canonical_value != raw
            ):
                out.append(unreadable_fault(name))
                continue
            try:
                affected = int(str(value.get("affected_rows", 0)))
            except ValueError:
                out.append(unreadable_fault(name))
                continue
            out.append(
                AuditFault(
                    code=str(value.get("code", "audit_fault")),
                    message=str(value.get("message", "")),
                    affected_rows=affected,
                    projection_name=str(value.get("projection_name", "knowledge")),
                    receipt_id=(
                        str(value["receipt_id"])
                        if isinstance(value.get("receipt_id"), str)
                        else None
                    ),
                )
            )
        return tuple(out)
    finally:
        os.close(directory_descriptor)


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
    "load_manifest",
    "load_audit_faults",
    "load_receipt",
    "persist_audit_fault",
    "persist_manifest",
    "persist_receipt",
    "receipts_root",
]
