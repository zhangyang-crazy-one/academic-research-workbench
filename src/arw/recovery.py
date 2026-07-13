"""Recovery evidence loading and accepted-boundary validation."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from arw.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.models import CanonicalEvent, RecoveryCompletedPayload, RecoveryReceipt


class RecoveryError(RuntimeError):
    """Recovery evidence is missing, unsafe, inconsistent, or stale."""


class DamagedSegment(Protocol):
    relative_path: str
    byte_count: int
    sha256: str
    accepted_byte_end: int
    fault_offset: int | None
    fault_class: str | None


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
    receipt_path = root / f"quarantine/{payload.recovery_id}/receipt.json"
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
        raw == (root / damaged.relative_path).read_bytes(),
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
