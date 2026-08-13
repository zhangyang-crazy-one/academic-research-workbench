"""Recovery evidence loading and accepted-boundary validation."""

from __future__ import annotations

import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from arw.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.models import (
    CanonicalEvent,
    RecoveryCompletedPayload,
    RecoveryReceipt,
    RecoveryRequest,
)


class RecoveryError(RuntimeError):
    """Recovery evidence is missing, unsafe, inconsistent, or stale."""


class DamagedSegment(Protocol):
    relative_path: str
    byte_count: int
    sha256: str
    accepted_byte_end: int
    fault_offset: int | None
    fault_class: str | None


class RecoverableReplay(Protocol):
    run_id: str
    revision: int
    last_event_sha256: str
    segments: tuple[DamagedSegment, ...]


@dataclass(frozen=True)
class PreparedRecovery:
    receipt: RecoveryReceipt
    receipt_sha256: str
    raw_sha256: str
    segment: DamagedSegment


POST_RAW_FSYNC_SIGKILL = "post-quarantine-raw-fsync-sigkill"
POST_RECEIPT_FSYNC_SIGKILL = "post-recovery-receipt-fsync-sigkill"
POST_SEGMENT_PUBLICATION_SIGKILL = "post-recovery-segment-publication-sigkill"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _trigger_failpoint(name: str) -> None:
    if os.environ.get("ARW_TEST_FAILPOINT") == name:
        os.kill(os.getpid(), signal.SIGKILL)


def _ensure_directory(root: Path, relative: Path) -> Path:
    root = root.resolve()
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RecoveryError("recovery directory path contains a symlink")
        if cursor.exists() and not cursor.is_dir():
            raise RecoveryError("recovery directory path contains a non-directory")
        if not cursor.exists():
            cursor.mkdir()
            _fsync_directory(cursor.parent)
    return cursor


def _write_immutable(path: Path, value: bytes) -> None:
    if path.is_symlink():
        raise RecoveryError("recovery evidence target must not be a symlink")
    if path.exists():
        if not path.is_file() or path.read_bytes() != value:
            raise RecoveryError("existing recovery evidence differs from this request")
        return
    try:
        with path.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as error:
        raise RecoveryError("recovery evidence was concurrently created") from error
    _fsync_directory(path.parent)


def _preflight_immutable(root: Path, relative: Path, value: bytes) -> None:
    cursor = root.resolve()
    for part in relative.parent.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RecoveryError("recovery evidence path contains a symlink")
        if cursor.exists() and not cursor.is_dir():
            raise RecoveryError("recovery evidence path contains a non-directory")
        if not cursor.exists():
            return
    target = cursor / relative.name
    if target.is_symlink():
        raise RecoveryError("recovery evidence target must not be a symlink")
    if target.exists() and (not target.is_file() or target.read_bytes() != value):
        raise RecoveryError("existing recovery evidence differs from this request")


def prepare_recovery_evidence(
    root: Path,
    request: RecoveryRequest,
    state: RecoverableReplay,
) -> PreparedRecovery:
    """Write or verify the immutable raw copy and canonical receipt."""

    if not state.segments:
        raise RecoveryError("recoverable replay has no damaged segment")
    damaged = state.segments[-1]
    if damaged.fault_offset is None or damaged.fault_class not in {
        "incomplete-record",
        "malformed-record",
        "truncated-utf8",
    }:
        raise RecoveryError("last segment is not a recoverable terminal tail")
    original_path = _safe_file(root, damaged.relative_path)
    original = original_path.read_bytes()
    if (
        sha256_hex(original) != damaged.sha256
        or len(original) != damaged.byte_count
        or request.original_segment_sha256 != damaged.sha256
    ):
        raise RecoveryError("damaged segment changed after classification")
    raw_relative = f"quarantine/{request.recovery_id}/segment.raw"
    receipt = RecoveryReceipt(
        schema_version="1.0.0",
        run_id=state.run_id,
        recovery_id=request.recovery_id,
        segment_relative_path=damaged.relative_path,
        original_segment_sha256=damaged.sha256,
        original_segment_byte_count=damaged.byte_count,
        accepted_byte_end=damaged.accepted_byte_end,
        fault_offset=damaged.fault_offset,
        fault_class=damaged.fault_class,
        quarantine_raw_path=raw_relative,
        quarantine_raw_sha256=sha256_hex(original),
        prior_valid_revision=state.revision,
        prior_valid_head_sha256=state.last_event_sha256,
        operator_id=request.actor_id,
        reason_code=request.reason_code,
        reason_text=request.reason_text,
        command_id=request.command_id,
        event_id=request.event_id,
        occurred_at=request.occurred_at,
    )
    receipt_bytes = canonical_json_bytes(receipt.model_dump(mode="json"))
    bundle_relative = Path("quarantine") / request.recovery_id
    _preflight_immutable(root, bundle_relative / "segment.raw", original)
    _preflight_immutable(root, bundle_relative / "receipt.json", receipt_bytes)
    bundle = _ensure_directory(root, bundle_relative)
    raw_path = bundle / "segment.raw"
    _write_immutable(raw_path, original)
    _trigger_failpoint(POST_RAW_FSYNC_SIGKILL)
    _write_immutable(bundle / "receipt.json", receipt_bytes)
    _trigger_failpoint(POST_RECEIPT_FSYNC_SIGKILL)
    return PreparedRecovery(
        receipt=receipt,
        receipt_sha256=sha256_hex(receipt_bytes),
        raw_sha256=sha256_hex(original),
        segment=damaged,
    )


def publish_recovery_segment(
    root: Path,
    *,
    segment_index: int,
    event: CanonicalEvent,
) -> Path:
    """Atomically publish the recovery-first continuation segment."""

    segments = root / "journal/segments"
    target = segments / f"{segment_index:08d}.jsonl"
    value = canonical_json_bytes(event.model_dump(mode="json"))
    temporary = root / "journal" / f".{target.name}.{os.getpid()}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or target.read_bytes() != value:
                raise RecoveryError("recovery segment target already differs")
        _fsync_directory(segments)
    finally:
        temporary.unlink(missing_ok=True)
    _trigger_failpoint(POST_SEGMENT_PUBLICATION_SIGKILL)
    return target


def _safe_file(root: Path, relative: str) -> Path:
    root = root.resolve()
    cursor = root
    for part in Path(relative).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise RecoveryError("recovery evidence path contains a symlink")
    try:
        resolved = cursor.resolve(strict=True)
    except OSError as error:
        raise RecoveryError(f"recovery evidence is unavailable: {error}") from error
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise RecoveryError("recovery evidence must be a regular file under the run root")
    return resolved


def load_recovery_receipt(root: Path, recovery_id: str) -> RecoveryReceipt:
    relative = f"quarantine/{recovery_id}/receipt.json"
    path = _safe_file(root, relative)
    try:
        raw = path.read_bytes()
        receipt = RecoveryReceipt.model_validate(strict_json_loads(raw))
    except (OSError, UnicodeError, ValueError, ValidationError) as error:
        raise RecoveryError(f"recovery receipt is invalid: {error}") from error
    if canonical_json_bytes(receipt.model_dump(mode="json")) != raw:
        raise RecoveryError("recovery receipt bytes are not canonical")
    if receipt.recovery_id != recovery_id:
        raise RecoveryError("recovery receipt identity differs from its path")
    return receipt


def validate_recovery_boundary(
    root: Path,
    event: CanonicalEvent,
    damaged: DamagedSegment,
) -> None:
    """Cross-check one recovery-first event against unchanged forensic evidence."""

    if event.event_type != "recovery.completed" or not isinstance(
        event.payload, RecoveryCompletedPayload
    ):
        raise RecoveryError("segment after damaged tail must begin with recovery.completed")
    payload = event.payload
    if damaged.fault_offset is None or damaged.fault_class is None:
        raise RecoveryError("recovery boundary has no classified damaged segment")
    receipt = load_recovery_receipt(root, payload.recovery_id)
    receipt_path = _safe_file(root, f"quarantine/{payload.recovery_id}/receipt.json")
    receipt_bytes = receipt_path.read_bytes()
    expected_raw_path = f"quarantine/{payload.recovery_id}/segment.raw"
    raw_path = _safe_file(root, expected_raw_path)
    raw = raw_path.read_bytes()
    checks = (
        payload.prior_valid_revision == event.expected_revision,
        payload.prior_valid_head_sha256 == event.prev_event_sha256,
        payload.original_segment_sha256 == damaged.sha256,
        payload.original_segment_byte_count == damaged.byte_count,
        payload.quarantine_sha256 == sha256_hex(raw),
        payload.quarantine_receipt_sha256 == sha256_hex(receipt_bytes),
        payload.fault_offset == damaged.fault_offset,
        payload.fault_class == damaged.fault_class,
        receipt.run_id == event.run_id,
        receipt.segment_relative_path == damaged.relative_path,
        receipt.original_segment_sha256 == damaged.sha256,
        receipt.original_segment_byte_count == damaged.byte_count,
        receipt.accepted_byte_end == damaged.accepted_byte_end,
        receipt.fault_offset == damaged.fault_offset,
        receipt.fault_class == damaged.fault_class,
        receipt.quarantine_raw_path == expected_raw_path,
        receipt.quarantine_raw_sha256 == sha256_hex(raw),
        raw == _safe_file(root, damaged.relative_path).read_bytes(),
        receipt.prior_valid_revision == event.expected_revision,
        receipt.prior_valid_head_sha256 == event.prev_event_sha256,
        receipt.operator_id == event.actor_id,
        receipt.reason_code == payload.reason_code,
        receipt.command_id == event.command_id,
        receipt.event_id == event.event_id,
        receipt.occurred_at == event.occurred_at,
    )
    if not all(checks):
        raise RecoveryError("recovery event, damaged segment, and quarantine evidence differ")
