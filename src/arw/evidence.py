"""Allowlisted, non-authoritative command and recovery evidence helpers."""

from __future__ import annotations

import os
import re
import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from arw.canonical import canonical_json_bytes, sha256_hex, strict_json_loads
from arw.faults import FAULT_SPECS


ALLOWLISTED_ENVIRONMENT = (
    "ARW_TEST_FAILPOINT",
    "PYTHONNOUSERSITE",
    "UV_OFFLINE",
)

_SIDEcar_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|password|passwd|secret|authorization|bearer|private[_-]?key|\bsk-[a-z0-9]+)"
)
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FAULT_CLASSIFICATIONS = frozenset(
    {"RETRYABLE", "DURABLE_OBSERVATION", "BLOCKED", "RECOVERABLE", "RECOVERED_TAIL", "REJECTED"}
)


def _validate_relative_path(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
        raise ValueError(f"{label} must be a relative path")
    if ".." in Path(value).parts:
        raise ValueError(f"{label} cannot contain '..'")
    return value


def _validate_digest(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return value


def validate_fault_sidecar_payload(payload: Mapping[str, object]) -> None:
    """Validate the parent-owned fault sidecar contract before publication."""

    fault_id = payload.get("fault_id")
    if not isinstance(fault_id, str) or fault_id not in FAULT_SPECS:
        raise ValueError("fault sidecar fault_id is not registered")
    boundary = payload.get("boundary")
    if boundary != FAULT_SPECS[fault_id].boundary:
        raise ValueError("fault sidecar boundary does not match registered fault")
    _validate_relative_path(payload.get("run_relative_root"), label="run_relative_root")
    if payload.get("replay_classification") not in _FAULT_CLASSIFICATIONS:
        raise ValueError("fault sidecar replay classification is not registered")
    reason = payload.get("reason_code")
    if not isinstance(reason, str) or not re.fullmatch(r"[a-z][a-z0-9._-]{2,95}", reason):
        raise ValueError("fault sidecar reason_code is malformed")
    retry_count = payload.get("retry_count")
    if isinstance(retry_count, bool) or not isinstance(retry_count, int) or not 0 <= retry_count <= 1:
        raise ValueError("fault sidecar retry_count must be between 0 and 1")
    _validate_digest(payload.get("event_sequence_sha256"), label="event_sequence_sha256")
    recovery_classification = str(payload.get("replay_classification", ""))
    recovery_digest = payload.get("canonical_recovery_event_sha256")
    if recovery_classification.startswith("RECOVERED_"):
        _validate_digest(recovery_digest, label="canonical_recovery_event_sha256")
    elif recovery_digest is not None:
        _validate_digest(recovery_digest, label="canonical_recovery_event_sha256")
    snapshots = payload.get("file_snapshots")
    if not isinstance(snapshots, Mapping):
        raise ValueError("fault sidecar file_snapshots must be an object")
    for relative, digest in snapshots.items():
        _validate_relative_path(relative, label="file snapshot path")
        _validate_digest(digest, label=f"file snapshot {relative}")
    process_state = payload.get("process_state")
    if not isinstance(process_state, Mapping):
        raise ValueError("fault sidecar process_state must be an object")
    returncode = process_state.get("returncode")
    if returncode is not None and (isinstance(returncode, bool) or not isinstance(returncode, int)):
        raise ValueError("fault sidecar process returncode is malformed")


def validate_fault_sidecar(
    path: Path,
    *,
    run_root: Path | None = None,
    expected_event_sequence: Sequence[object] | None = None,
    expected_recovery_event: Mapping[str, object] | None = None,
) -> Mapping[str, object]:
    """Cold-validate a sidecar and its sibling digest before replay accepts it."""

    if path.is_symlink() or not path.is_file():
        raise ValueError("fault sidecar is missing or unsafe")
    raw = path.read_bytes()
    payload = strict_json_loads(raw)
    if not isinstance(payload, Mapping) or payload.get("schema_version") != "arw.phase7-fault-sidecar.v1":
        raise ValueError("fault sidecar schema is invalid")
    if raw != canonical_json_bytes(payload):
        raise ValueError("fault sidecar JSON is not canonical")
    validate_fault_sidecar_payload(payload)
    event_sequence = payload.get("event_sequence")
    if not isinstance(event_sequence, Sequence) or isinstance(event_sequence, (str, bytes, bytearray)) or not event_sequence:
        raise ValueError("fault sidecar event_sequence is missing")
    for encoded_event in event_sequence:
        if not isinstance(encoded_event, str):
            raise ValueError("fault sidecar event_sequence is not a canonical ledger sequence")
        try:
            event = strict_json_loads(encoded_event.encode("utf-8"))
        except (TypeError, ValueError) as error:
            raise ValueError("fault sidecar event_sequence contains invalid event JSON") from error
        if not isinstance(event, Mapping) or not isinstance(event.get("event_sha256"), str):
            raise ValueError("fault sidecar event_sequence contains a non-ledger event")
        unsigned = dict(event)
        event_hash = unsigned.pop("event_sha256")
        if sha256_hex(canonical_json_bytes(unsigned)) != event_hash:
            raise ValueError("fault sidecar event_sequence contains an unsealed event")
    if sha256_hex(canonical_json_bytes(event_sequence)) != payload.get("event_sequence_sha256"):
        raise ValueError("fault sidecar event sequence digest is not bound")
    if expected_event_sequence is not None and list(expected_event_sequence) != list(event_sequence):
        raise ValueError("fault sidecar event sequence does not match replay")
    if run_root is not None:
        try:
            from arw.journal import replay_run

            replayed = replay_run(run_root)
            replay_sequence = [
                canonical_json_bytes(event.model_dump(mode="json")).decode("utf-8")
                for event in replayed.events
            ]
        except (OSError, ValueError, RuntimeError) as error:
            raise ValueError("fault sidecar run replay is unavailable") from error
        if replay_sequence != list(event_sequence):
            raise ValueError("fault sidecar event sequence does not match run replay")
        if expected_recovery_event is None and str(payload.get("replay_classification", "")).startswith("RECOVERED_"):
            expected_recovery_event = next(
                (
                    event.model_dump(mode="json")
                    for event in replayed.events
                    if event.event_sha256 == payload.get("canonical_recovery_event_sha256")
                ),
                None,
            )
            if expected_recovery_event is None:
                raise ValueError("fault sidecar recovery event is absent from run replay")
    recovery_event = payload.get("recovery_event")
    if str(payload.get("replay_classification", "")).startswith("RECOVERED_"):
        if not isinstance(recovery_event, Mapping):
            raise ValueError("fault sidecar recovery event is missing")
        recovery_hash = recovery_event.get("event_sha256")
        if recovery_hash != payload.get("canonical_recovery_event_sha256"):
            raise ValueError("fault sidecar recovery event digest is not bound")
        unsigned_recovery = dict(recovery_event)
        sealed_hash = unsigned_recovery.pop("event_sha256", None)
        if not isinstance(sealed_hash, str) or sha256_hex(canonical_json_bytes(unsigned_recovery)) != sealed_hash:
            raise ValueError("fault sidecar recovery event is not canonically sealed")
        if expected_recovery_event is not None and dict(expected_recovery_event) != dict(recovery_event):
            raise ValueError("fault sidecar recovery event does not match replay")
    digest_path = path.with_name("sidecar.sha256")
    if digest_path.is_symlink() or not digest_path.is_file():
        raise ValueError("fault sidecar digest is missing or unsafe")
    expected = digest_path.read_text(encoding="ascii").strip()
    actual = sha256_hex(path.read_bytes())
    if expected != actual:
        raise ValueError("fault sidecar digest mismatch")
    return payload


def _assert_bounded_fault_value(value: object, *, key: str = "") -> None:
    """Reject secrets and absolute/private paths from retained sidecars."""

    if isinstance(value, Mapping):
        for name, child in value.items():
            text_name = str(name)
            if _SIDEcar_SECRET_PATTERN.search(text_name):
                raise ValueError(f"fault sidecar field is secret-bearing: {text_name}")
            _assert_bounded_fault_value(child, key=text_name)
        return
    if isinstance(value, (list, tuple)):
        for child in value:
            _assert_bounded_fault_value(child, key=key)
        return
    if isinstance(value, str):
        if _SIDEcar_SECRET_PATTERN.search(value):
            raise ValueError("fault sidecar contains secret-like content")
        if value.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:[\\/]", value):
            raise ValueError("fault sidecar contains an absolute path")


def write_fault_sidecar(
    output_root: Path,
    *,
    fault_id: str,
    boundary: str,
    run_relative_root: str,
    stdout: bytes | str = b"",
    stderr: bytes | str = b"",
    file_snapshots: Mapping[str, str] | None = None,
    process_state: Mapping[str, object] | None = None,
    replay_classification: str,
    reason_code: str,
    retry_count: int,
    event_sequence_sha256: str,
    canonical_recovery_event_sha256: str | None = None,
    event_sequence: Sequence[object] | None = None,
    recovery_event: Mapping[str, object] | None = None,
    run_root: Path | None = None,
) -> str:
    """Write one parent-owned, hash-bound fault receipt.

    The sidecar is deliberately outside the run ledger.  It records only
    relative paths and bounded streams; canonical authority is established by
    ``event_sequence_sha256`` and (when present) the recovery event digest.
    ``sidecar.sha256`` is written after the immutable JSON receipt.
    """

    def bounded_stream(value: bytes | str) -> str:
        raw = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
        # Streams are evidence, not a transcript.  Keep enough context to
        # diagnose the boundary while preventing unbounded output retention.
        return raw[:4096]

    snapshots = dict(file_snapshots or {})
    if event_sequence is None:
        snapshot_digest = sha256_hex(canonical_json_bytes(sorted(snapshots.items())))
        unsigned_observation = {"event_type": "fault-observation", "snapshot_sha256": snapshot_digest}
        sealed_observation = dict(unsigned_observation)
        sealed_observation["event_sha256"] = sha256_hex(canonical_json_bytes(unsigned_observation))
        sequence_payload: Sequence[object] = [canonical_json_bytes(sealed_observation).decode("utf-8")]
    else:
        sequence_payload = event_sequence
    derived_event_sequence_sha256 = sha256_hex(canonical_json_bytes(sequence_payload))
    if event_sequence is not None and event_sequence_sha256 != derived_event_sequence_sha256:
        raise ValueError("event_sequence_sha256 does not match canonical event sequence")
    # A caller that has no replayable sequence is still bound to the immutable
    # bounded snapshot fallback.  The normal parent path supplies the exact
    # canonical ledger event sequence above.
    event_sequence_sha256 = derived_event_sequence_sha256
    if recovery_event is not None:
        recovery_digest = recovery_event.get("event_sha256")
        if recovery_digest != canonical_recovery_event_sha256:
            raise ValueError("canonical recovery event digest does not match event")
    elif str(replay_classification).startswith("RECOVERED_"):
        raise ValueError("recovered fault sidecar requires canonical recovery event")
    payload: dict[str, object] = {
        "schema_version": "arw.phase7-fault-sidecar.v1",
        "fault_id": fault_id,
        "boundary": boundary,
        "run_relative_root": run_relative_root,
        "stdout": bounded_stream(stdout),
        "stderr": bounded_stream(stderr),
        "file_snapshots": snapshots,
        "process_state": dict(process_state or {}),
        "replay_classification": replay_classification,
        "reason_code": reason_code,
        "retry_count": retry_count,
        "event_sequence_sha256": event_sequence_sha256,
        "canonical_recovery_event_sha256": canonical_recovery_event_sha256,
        "event_sequence": sequence_payload,
    }
    if recovery_event is not None:
        payload["recovery_event"] = dict(recovery_event)
    validate_fault_sidecar_payload(payload)
    _assert_bounded_fault_value(payload)
    output_root.mkdir(parents=True, exist_ok=True)
    sidecar = output_root / "sidecar.json"
    write_evidence_json(sidecar, payload)
    digest = sha256_hex(sidecar.read_bytes())
    write_evidence_bytes(output_root / "sidecar.sha256", f"{digest}\n".encode("ascii"))
    # Publication is not complete until the same cold validator used by
    # recovery has replay-bound the bytes and sealed event envelope.
    validate_fault_sidecar(
        sidecar,
        run_root=run_root,
        expected_event_sequence=sequence_payload,
        expected_recovery_event=recovery_event,
    )
    return digest


def _write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        with temporary.open("xb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_evidence_bytes(path: Path, value: bytes) -> None:
    """Preserve an exact raw evidence stream or byte snapshot."""

    _write_bytes(path, value)


def write_evidence_json(path: Path, value: object) -> None:
    """Preserve stable machine-readable evidence outside canonical authority."""

    _write_bytes(path, canonical_json_bytes(value))


def _signal_name(returncode: int) -> str | None:
    if returncode >= 0:
        return None
    try:
        return signal.Signals(-returncode).name
    except ValueError:
        return f"UNKNOWN_{-returncode}"


def record_command_result(
    output_root: Path,
    *,
    argv: Sequence[str],
    cwd: Path,
    cwd_base: Path,
    environment: Mapping[str, str],
    result: subprocess.CompletedProcess[bytes],
) -> None:
    """Record argv, relative cwd, selected environment, streams, and status."""

    resolved_cwd = cwd.resolve()
    resolved_base = cwd_base.resolve()
    try:
        relative_cwd = resolved_cwd.relative_to(resolved_base).as_posix() or "."
    except ValueError as error:
        raise ValueError("evidence cwd must be under its declared base") from error
    if relative_cwd == ".":
        display_cwd = "."
    else:
        display_cwd = relative_cwd
    selected_environment = {
        key: environment[key]
        for key in ALLOWLISTED_ENVIRONMENT
        if key in environment
    }
    write_evidence_json(
        output_root / "command.json",
        {
            "argv": list(argv),
            "cwd": display_cwd,
            "environment": selected_environment,
        },
    )
    write_evidence_bytes(output_root / "stdout.log", result.stdout)
    write_evidence_bytes(output_root / "stderr.log", result.stderr)
    write_evidence_json(
        output_root / "exit.json",
        {
            "returncode": result.returncode,
            "signal": _signal_name(result.returncode),
        },
    )
