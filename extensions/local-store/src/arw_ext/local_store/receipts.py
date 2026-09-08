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

import json
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
DEFAULT_MAX_AUDIT_INPUT_BYTES = 4 * 1024 * 1024
# Aggregate canonical UTF-8 output budget for ``load_audit_faults``.  The
# composition root serializes the returned faults into the ``arw status``
# health payload, so without a ceiling one ``max_entries=1001`` load of
# 65 KiB receipts could retain/emit ~63 MiB.  256 KiB keeps a status run
# bounded while still surfacing thousands of faults.  Operators who need a
# higher ceiling must opt in explicitly via ``max_output_bytes``.
DEFAULT_MAX_AUDIT_OUTPUT_BYTES = 262_144
# Reserved bytes for the typed truncation marker so the marker itself
# always fits inside the declared limit even when the very last kept
# entry consumes the rest of the budget.  Sized for the *full* canonical
# marker (5 ``AuditFault`` fields incl. ``receipt_id=null``) plus list
# wrap (``[`` + ``]`` + ``,`` + ``\n`` = 4 bytes), so the invariant
# ``len(canonical(marker)) + 4 <= reserve`` holds across every
# enumerated/kept/max_output_bytes combination permitted by the
# validation bounds above.
_AUDIT_OUTPUT_TRUNCATION_FAULT_RESERVE_BYTES = 256
_AUDIT_OUTPUT_LIST_OPEN_BYTES = 1  # leading '['
_AUDIT_OUTPUT_LIST_SEP_BYTES = 1  # ',' between entries
_AUDIT_OUTPUT_LIST_CLOSE_BYTES = 2  # trailing ']' + '\n'
# Distinct fault code so callers can pattern-match aggregate-output
# truncation (this budget) versus inventory-count truncation (existing
# ``audit_receipt_inventory_truncated`` raised when the directory contains
# more than ``max_entries`` files).
AUDIT_RECEIPT_OUTPUT_TRUNCATED_CODE = "audit_receipt_output_truncated"


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


def _audit_output_entry_bytes(fault: AuditFault) -> int:
    """Return the canonical UTF-8 byte size of one fault as the loader
    retains it — full dataclass, not the composition-root status
    projection.

    The composition-root ``local_store_health`` serializer in
    ``arw.composition`` drops ``receipt_id`` and ``projection_name``
    when emitting the status list, but the loader *retains* the full
    ``AuditFault`` instance — including attacker-controlled
    ``receipt_id`` values bounded only by ``max_bytes``.  Sizing on the
    projection alone would let 1001 receipts with a multi-KB
    ``receipt_id`` and tiny ``message`` retain ~50 MB while emitting
    only a few KB to the operator.  By sizing the full canonical shape
    (matching ``_serialize_audit_fault`` minus the ``schema_version``
    envelope, which is metadata not bound to any individual entry),
    this helper bounds both the retained tuple footprint and the
    eventual status serialization — the projection is always a subset
    of the dataclass.
    """

    payload = {
        "affected_rows": fault.affected_rows,
        "code": fault.code,
        "message": fault.message,
        "projection_name": fault.projection_name,
        "receipt_id": fault.receipt_id,
    }
    return len(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    )


def _audit_output_truncation_fault(
    *, enumerated: int, kept: int, max_output_bytes: int
) -> AuditFault:
    """Return the deterministic, fixed-form truncation marker.

    The message layout is bounded by ``_AUDIT_OUTPUT_TRUNCATION_FAULT_RESERVE_BYTES``:
    enumerated/kept values come from ``max_entries`` (≤ 4 096) and the
    budget value is ``max_output_bytes`` (≤ four times the default),
    so the literal length is a small fixed constant for any caller.
    """

    return AuditFault(
        code=AUDIT_RECEIPT_OUTPUT_TRUNCATED_CODE,
        message=(
            f"audit receipt output truncated: enumerated={enumerated} "
            f"kept={kept} max_output_bytes={max_output_bytes}"
        ),
        affected_rows=1,
        projection_name="knowledge",
    )


def _bounded_early_return(
    fault: AuditFault, *, max_output_bytes: int
) -> tuple[AuditFault, ...]:
    """Wrap ``fault`` as a 1-tuple bounded by ``max_output_bytes``.

    Every early-return path in :func:`load_audit_faults` routes through
    this helper so no fault tuple can bypass the output-budget
    invariant — if the fault's own canonical size would exceed the
    declared ceiling (e.g. an ``OSError`` carrying a long ``strerror``),
    the helper substitutes a single ``audit_receipt_output_truncated``
    marker so the operator still sees a typed budget fault instead of a
    silent overflow.
    """

    size = (
        _audit_output_entry_bytes(fault)
        + _AUDIT_OUTPUT_LIST_OPEN_BYTES
        + _AUDIT_OUTPUT_LIST_CLOSE_BYTES
    )
    if size <= max_output_bytes:
        return (fault,)
    return (
        _audit_output_truncation_fault(
            enumerated=0,
            kept=0,
            max_output_bytes=max_output_bytes,
        ),
    )


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
    max_output_bytes: int = DEFAULT_MAX_AUDIT_OUTPUT_BYTES,
    max_input_bytes: int = DEFAULT_MAX_AUDIT_INPUT_BYTES,
) -> tuple[AuditFault, ...]:
    """Load bounded audit faults through a no-follow directory descriptor.

    The aggregate canonical UTF-8 size of the returned tuple is bounded by
    ``max_output_bytes`` (default 256 KiB).  When adding another fault
    would exceed the budget, the loader appends one typed truncation
    marker — :data:`AUDIT_RECEIPT_OUTPUT_TRUNCATED_CODE` — and stops
    reading further entries.  The marker always fits inside the declared
    ceiling; the final canonical JSON serialization never exceeds the
    declared bound.  The budget covers both valid receipt faults and
    generated malformed-receipt faults (``unreadable_fault``).
    Raw input reads are independently capped by ``max_input_bytes`` (4 MiB
    by default), including malformed payloads and fields discarded by parsing.
    Reaching that ceiling retains prior faults and adds a typed input marker.
    """
    if max_entries < 1 or max_entries > DEFAULT_MAX_AUDIT_ENTRIES:
        raise ValueError("audit entry bound is outside the supported range")
    if max_bytes < 1 or max_bytes > DEFAULT_MAX_AUDIT_RECEIPT_BYTES:
        raise ValueError("audit receipt byte bound is outside the supported range")
    if not 1 <= max_input_bytes <= DEFAULT_MAX_AUDIT_INPUT_BYTES:
        raise ValueError("audit input byte bound is outside the supported range")
    if max_output_bytes < _AUDIT_OUTPUT_TRUNCATION_FAULT_RESERVE_BYTES + 1:
        raise ValueError("audit output budget is below the truncation reserve")
    max_output_bytes_cap = DEFAULT_MAX_AUDIT_OUTPUT_BYTES * 4
    if max_output_bytes > max_output_bytes_cap:
        raise ValueError("audit output budget exceeds the supported ceiling")
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
            return _bounded_early_return(
                AuditFault(
                    code="audit_receipt_read_failed",
                    message="audit receipt directory path contains a symlink",
                    affected_rows=1,
                    projection_name="knowledge",
                ),
                max_output_bytes=max_output_bytes,
            )
    root = candidate
    directory_descriptor: int | None = None
    if os.name != "nt":
        try:
            directory_descriptor = _open_directory_no_follow(root)
        except FileNotFoundError:
            return ()
        except OSError as error:
            return _bounded_early_return(
                AuditFault(
                    code="audit_receipt_read_failed",
                    message=(
                        f"audit receipt directory is unsafe or unreadable: {error}"
                    ),
                    affected_rows=1,
                    projection_name="knowledge",
                ),
                max_output_bytes=max_output_bytes,
            )
    try:
        names: list[str] = []
        scan_target = root if directory_descriptor is None else directory_descriptor
        try:
            with os.scandir(scan_target) as entries:
                for index, entry in enumerate(entries):
                    if index >= max_entries:
                        return _bounded_early_return(
                            AuditFault(
                                code="audit_receipt_inventory_truncated",
                                message=(
                                    "audit receipt inventory exceeds the "
                                    "configured limit"
                                ),
                                affected_rows=1,
                                projection_name="knowledge",
                            ),
                            max_output_bytes=max_output_bytes,
                        )
                    if entry.name.endswith(".json"):
                        names.append(entry.name)
        except OSError as error:
            return _bounded_early_return(
                AuditFault(
                    code="audit_receipt_read_failed",
                    message=f"audit receipt directory cannot be enumerated: {error}",
                    affected_rows=1,
                    projection_name="knowledge",
                ),
                max_output_bytes=max_output_bytes,
            )

        out: list[AuditFault] = []

        def unreadable_fault(name: str) -> AuditFault:
            return AuditFault(
                code="audit_receipt_read_failed",
                message=f"audit receipt {name!a} is unreadable or malformed",
                affected_rows=1,
                projection_name="knowledge",
                receipt_id=("audit-read-" + sha256_hex(os.fsencode(name))[:24]),
            )

        no_follow = getattr(os, "O_NOFOLLOW", 0)
        file_flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | no_follow
        )

        input_bytes = 0

        class InputBudgetExceeded(Exception):
            pass

        def decode_audit_fault(name: str) -> AuditFault:
            """Parse one receipt file into an :class:`AuditFault`.

            Returns either the canonicalized receipt payload or a typed
            ``audit_receipt_read_failed`` marker when the file is missing,
            oversized, non-regular, symlinked, or non-canonical.  The
            caller is responsible for the output-budget gate; this helper
            is side-effect-free aside from the read syscall itself.
            """

            nonlocal input_bytes
            try:
                if directory_descriptor is None:
                    receipt_path = root / name
                    if receipt_path.is_symlink():
                        raise OSError("audit receipt must not be a symlink")
                    descriptor = os.open(receipt_path, file_flags)
                else:
                    descriptor = os.open(name, file_flags, dir_fd=directory_descriptor)
                try:
                    status = os.fstat(descriptor)
                    if not stat.S_ISREG(status.st_mode) or status.st_size > max_bytes:
                        return unreadable_fault(name)
                    if status.st_size > max_input_bytes - input_bytes:
                        raise InputBudgetExceeded
                    if directory_descriptor is None:
                        live = os.stat(root / name, follow_symlinks=False)
                        if (
                            live.st_dev != status.st_dev
                            or live.st_ino != status.st_ino
                            or live.st_mode != status.st_mode
                        ):
                            return unreadable_fault(name)
                    chunks: list[bytes] = []
                    total = 0
                    while total <= max_bytes:
                        remaining = max_input_bytes - input_bytes
                        if remaining == 0:
                            if total == status.st_size == os.fstat(descriptor).st_size:
                                break
                            raise InputBudgetExceeded
                        chunk = os.read(
                            descriptor, min(16_384, max_bytes + 1 - total, remaining)
                        )
                        if not chunk:
                            break
                        chunks.append(chunk)
                        total += len(chunk)
                        input_bytes += len(chunk)
                    if total > max_bytes:
                        return unreadable_fault(name)
                    raw = b"".join(chunks)
                finally:
                    os.close(descriptor)
                value: Mapping[str, object] = strict_json_loads(raw)
                canonical_value = canonical_json_bytes(value)
            except (OSError, UnicodeError, ValueError):
                return unreadable_fault(name)
            if not isinstance(value, dict):
                return unreadable_fault(name)
            _, separator, filename_digest = name.removesuffix(".json").rpartition("-")
            if (
                not separator
                or filename_digest != sha256_hex(raw)[:12]
                or canonical_value != raw
            ):
                return unreadable_fault(name)
            try:
                affected = int(str(value.get("affected_rows", 0)))
            except ValueError:
                return unreadable_fault(name)
            return AuditFault(
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

        used_bytes = 0
        for enumerated, name in enumerate(sorted(names), 1):
            try:
                candidate = decode_audit_fault(name)
            except InputBudgetExceeded:
                out.append(
                    AuditFault(
                        code="audit_receipt_input_truncated",
                        message=f"audit receipt input truncated: max_input_bytes={max_input_bytes}",
                        affected_rows=1,
                        projection_name="knowledge",
                    )
                )
                break
            entry_bytes = _audit_output_entry_bytes(candidate)
            projected = entry_bytes + (
                _AUDIT_OUTPUT_LIST_SEP_BYTES if out else _AUDIT_OUTPUT_LIST_OPEN_BYTES
            )
            if (
                used_bytes + projected + _AUDIT_OUTPUT_TRUNCATION_FAULT_RESERVE_BYTES
                > max_output_bytes
            ):
                out.append(
                    _audit_output_truncation_fault(
                        enumerated=enumerated,
                        kept=len(out),
                        max_output_bytes=max_output_bytes,
                    )
                )
                break
            out.append(candidate)
            used_bytes += projected
        return tuple(out)
    finally:
        if directory_descriptor is not None:
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
    "load_audit_faults",
    "load_manifest",
    "load_receipt",
    "persist_audit_fault",
    "persist_manifest",
    "persist_receipt",
    "receipts_root",
]
