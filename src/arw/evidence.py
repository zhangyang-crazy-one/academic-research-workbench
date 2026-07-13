"""Allowlisted, non-authoritative command and recovery evidence helpers."""

from __future__ import annotations

import os
import signal
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from arw.canonical import canonical_json_bytes


ALLOWLISTED_ENVIRONMENT = (
    "ARW_TEST_FAILPOINT",
    "PYTHONNOUSERSITE",
    "UV_OFFLINE",
)


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
