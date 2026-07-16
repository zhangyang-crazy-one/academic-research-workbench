"""Allowlisted, non-authoritative command and recovery evidence helpers."""

from __future__ import annotations

import os
import re
import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from arw.canonical import canonical_json_bytes, sha256_hex


ALLOWLISTED_ENVIRONMENT = (
    "ARW_TEST_FAILPOINT",
    "PYTHONNOUSERSITE",
    "UV_OFFLINE",
)

_SIDEcar_SECRET_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|password|passwd|secret|authorization|bearer|private[_-]?key|sk-[a-z0-9]+)"
)


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

    payload: dict[str, object] = {
        "schema_version": "arw.phase7-fault-sidecar.v1",
        "fault_id": fault_id,
        "boundary": boundary,
        "run_relative_root": run_relative_root,
        "stdout": bounded_stream(stdout),
        "stderr": bounded_stream(stderr),
        "file_snapshots": dict(file_snapshots or {}),
        "process_state": dict(process_state or {}),
        "replay_classification": replay_classification,
        "reason_code": reason_code,
        "retry_count": retry_count,
        "event_sequence_sha256": event_sequence_sha256,
        "canonical_recovery_event_sha256": canonical_recovery_event_sha256,
    }
    _assert_bounded_fault_value(payload)
    output_root.mkdir(parents=True, exist_ok=True)
    sidecar = output_root / "sidecar.json"
    write_evidence_json(sidecar, payload)
    digest = sha256_hex(sidecar.read_bytes())
    write_evidence_bytes(output_root / "sidecar.sha256", f"{digest}\n".encode("ascii"))
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
