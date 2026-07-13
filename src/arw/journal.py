"""Sole-writer initialization, append, fsync, and replay for Phase 1."""

from __future__ import annotations

import os
import signal
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import portalocker
from pydantic import ValidationError

from arw.canonical import (
    canonical_event_bytes,
    canonical_json_bytes,
    seal_event,
    sha256_hex,
    strict_json_loads,
)
from arw.models import (
    AppendProbeRequest,
    BaselineProbePayload,
    CanonicalEvent,
    InitRunRequest,
    RunInitializedPayload,
    RunManifest,
    ZERO_HASH,
)


MANIFEST_NAME = "run-manifest.json"
JOURNAL_NAME = "events.jsonl"
LOCK_NAME = ".journal.lock"
FAILPOINT_ENV = "ARW_TEST_FAILPOINT"
POST_FSYNC_SIGKILL = "post-journal-fsync-sigkill"


class JournalError(RuntimeError):
    """Canonical run bytes are absent, malformed, stale, or unsafe to mutate."""


@dataclass(frozen=True)
class ReplayState:
    run_id: str
    revision: int
    last_event_sha256: str
    event_count: int
    event_ids: frozenset[str]
    command_ids: frozenset[str]

    def public_dict(self) -> dict[str, object]:
        return {
            "event_count": self.event_count,
            "last_event_sha256": self.last_event_sha256,
            "revision": self.revision,
            "run_id": self.run_id,
        }


def _validated_root(run_root: Path) -> Path:
    if run_root.is_symlink():
        raise JournalError("run root must not be a symlink")
    run_root.mkdir(parents=True, exist_ok=True)
    if not run_root.is_dir():
        raise JournalError("run root is not a directory")
    return run_root.resolve()


def _lock(run_root: Path, timeout: float) -> portalocker.Lock:
    if timeout < 0:
        raise JournalError("lock timeout must be non-negative")
    return portalocker.Lock(
        run_root / LOCK_NAME,
        mode="a+b",
        timeout=timeout,
        check_interval=0.01,
    )


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_exclusive(path: Path, value: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())


def _input_digest_matches(root: Path, manifest_input: Any) -> None:
    lexical = root.joinpath(*Path(manifest_input.path).parts)
    cursor = root
    for part in Path(manifest_input.path).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise JournalError("immutable input path must not contain symlinks")
    try:
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        raise JournalError(f"immutable input is unavailable: {error}") from error
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise JournalError("immutable input must resolve to a file under the run root")
    actual = sha256_hex(resolved.read_bytes())
    if actual != manifest_input.sha256:
        raise JournalError("immutable input digest mismatch")


def _event_from_unsigned(unsigned: dict[str, object]) -> CanonicalEvent:
    sealed = seal_event(unsigned)
    try:
        return CanonicalEvent.model_validate(sealed)
    except ValidationError as error:
        raise JournalError(f"writer constructed an invalid event: {error}") from error


def _requested_failpoint() -> str | None:
    value = os.environ.get(FAILPOINT_ENV)
    if value in {None, ""}:
        return None
    if value != POST_FSYNC_SIGKILL:
        raise JournalError(f"unsupported test failpoint: {value}")
    if not hasattr(signal, "SIGKILL"):
        raise JournalError("post-fsync SIGKILL failpoint is unsupported on this OS")
    return value


def initialize_run(
    run_root: Path,
    request: InitRunRequest,
    *,
    lock_timeout: float = 0.2,
) -> ReplayState:
    """Write an immutable manifest and the first hash-chained event once."""

    root = _validated_root(run_root)
    _input_digest_matches(root, request.immutable_input)
    manifest = RunManifest(
        schema_version=request.schema_version,
        run_id=request.run_id,
        created_at=request.occurred_at,
        immutable_input=request.immutable_input,
        workflow_family=request.workflow_family,
        workflow_mode=request.workflow_mode,
        capabilities=request.capabilities,
    )
    manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json"))
    initial = _event_from_unsigned(
        {
            "schema_version": request.schema_version,
            "event_type": "run.initialized",
            "event_id": request.event_id,
            "command_id": request.command_id,
            "run_id": request.run_id,
            "sequence": 1,
            "occurred_at": request.occurred_at,
            "expected_revision": 0,
            "resulting_revision": 1,
            "actor_id": request.actor_id,
            "prev_event_sha256": ZERO_HASH,
            "payload": RunInitializedPayload(
                manifest_sha256=sha256_hex(manifest_bytes)
            ).model_dump(mode="json"),
        }
    )
    event_bytes = canonical_json_bytes(initial.model_dump(mode="json"))
    manifest_path = root / MANIFEST_NAME
    journal_path = root / JOURNAL_NAME
    try:
        with _lock(root, lock_timeout):
            if manifest_path.exists() or journal_path.exists():
                raise JournalError("run is already initialized or partially present")
            _write_exclusive(manifest_path, manifest_bytes)
            try:
                _write_exclusive(journal_path, event_bytes)
            except BaseException:
                manifest_path.unlink(missing_ok=True)
                raise
            _fsync_directory(root)
    except portalocker.exceptions.LockException as error:
        raise JournalError("canonical writer lock is held") from error
    return ReplayState(
        run_id=request.run_id,
        revision=1,
        last_event_sha256=initial.event_sha256,
        event_count=1,
        event_ids=frozenset({request.event_id}),
        command_ids=frozenset({request.command_id}),
    )


def _strict_model(model: type[Any], value: object, label: str) -> Any:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise JournalError(f"invalid {label}: {error}") from error


def _replay_unlocked(root: Path) -> ReplayState:
    manifest_path = root / MANIFEST_NAME
    journal_path = root / JOURNAL_NAME
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest_payload = strict_json_loads(manifest_bytes)
    except (OSError, UnicodeError, ValueError) as error:
        raise JournalError(f"manifest is missing or malformed: {error}") from error
    manifest: RunManifest = _strict_model(RunManifest, manifest_payload, "manifest")
    if canonical_json_bytes(manifest.model_dump(mode="json")) != manifest_bytes:
        raise JournalError("manifest bytes are not canonical")

    try:
        journal_bytes = journal_path.read_bytes()
    except OSError as error:
        raise JournalError(f"journal is missing: {error}") from error
    if not journal_bytes or not journal_bytes.endswith(b"\n"):
        raise JournalError("journal has an empty or incomplete tail")

    revision = 0
    previous_hash = ZERO_HASH
    event_ids: set[str] = set()
    command_ids: set[str] = set()
    lines = journal_bytes.splitlines(keepends=True)
    manifest_hash = sha256_hex(manifest_bytes)
    for index, line in enumerate(lines, start=1):
        try:
            payload = strict_json_loads(line)
        except (UnicodeError, ValueError) as error:
            raise JournalError(f"journal event {index} is malformed: {error}") from error
        event: CanonicalEvent = _strict_model(CanonicalEvent, payload, f"event {index}")
        if canonical_json_bytes(event.model_dump(mode="json")) != line:
            raise JournalError(f"journal event {index} bytes are not canonical")
        actual_hash = sha256_hex(canonical_event_bytes(event.model_dump(mode="json")))
        if event.event_sha256 != actual_hash:
            raise JournalError(f"journal event {index} hash does not cover its bytes")
        if event.run_id != manifest.run_id:
            raise JournalError(f"journal event {index} run identity differs from manifest")
        if event.sequence != index:
            raise JournalError(f"journal event {index} sequence is not contiguous")
        if event.expected_revision != revision or event.resulting_revision != revision + 1:
            raise JournalError(f"journal event {index} revision is not contiguous")
        if event.prev_event_sha256 != previous_hash:
            raise JournalError(f"journal event {index} previous hash does not match")
        if event.event_id in event_ids or event.command_id in command_ids:
            raise JournalError(f"journal event {index} repeats an accepted identity")
        if index == 1:
            if event.event_type != "run.initialized":
                raise JournalError("first journal event must initialize the run")
            if not isinstance(event.payload, RunInitializedPayload):
                raise JournalError("first journal event has the wrong payload")
            if event.payload.manifest_sha256 != manifest_hash:
                raise JournalError("first journal event does not bind the manifest bytes")
        elif event.event_type != "baseline.probe_recorded":
            raise JournalError("Phase 1 journal contains an unsupported later event")
        revision = event.resulting_revision
        previous_hash = event.event_sha256
        event_ids.add(event.event_id)
        command_ids.add(event.command_id)

    return ReplayState(
        run_id=manifest.run_id,
        revision=revision,
        last_event_sha256=previous_hash,
        event_count=len(lines),
        event_ids=frozenset(event_ids),
        command_ids=frozenset(command_ids),
    )


def replay_run(run_root: Path, *, lock_timeout: float = 0.2) -> ReplayState:
    """Validate and replay solely from immutable manifest and canonical JSONL."""

    root = _validated_root(run_root)
    try:
        with _lock(root, lock_timeout):
            return _replay_unlocked(root)
    except portalocker.exceptions.LockException as error:
        raise JournalError("canonical writer lock is held") from error


def append_probe(
    run_root: Path,
    request: AppendProbeRequest,
    *,
    lock_timeout: float = 0.2,
) -> ReplayState:
    """Replay under lock and append exactly one fsynced baseline event."""

    failpoint = _requested_failpoint()
    root = _validated_root(run_root)
    journal_path = root / JOURNAL_NAME
    try:
        with _lock(root, lock_timeout):
            before_size = journal_path.stat().st_size
            state = _replay_unlocked(root)
            if request.run_id != state.run_id:
                raise JournalError("append run identity differs from manifest")
            if request.expected_revision != state.revision:
                raise JournalError(
                    f"stale revision: expected {request.expected_revision}, current {state.revision}"
                )
            if request.event_id in state.event_ids:
                raise JournalError("event_id was already accepted")
            if request.command_id in state.command_ids:
                raise JournalError("command_id was already accepted")
            event = _event_from_unsigned(
                {
                    "schema_version": request.schema_version,
                    "event_type": request.event_type,
                    "event_id": request.event_id,
                    "command_id": request.command_id,
                    "run_id": request.run_id,
                    "sequence": state.event_count + 1,
                    "occurred_at": request.occurred_at,
                    "expected_revision": request.expected_revision,
                    "resulting_revision": request.expected_revision + 1,
                    "actor_id": request.actor_id,
                    "prev_event_sha256": state.last_event_sha256,
                    "payload": request.payload.model_dump(mode="json"),
                }
            )
            event_bytes = canonical_json_bytes(event.model_dump(mode="json"))
            if journal_path.stat().st_size != before_size:
                raise JournalError("journal changed during locked replay")
            with journal_path.open("ab") as handle:
                handle.write(event_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            if failpoint == POST_FSYNC_SIGKILL:
                os.kill(os.getpid(), signal.SIGKILL)
            return ReplayState(
                run_id=state.run_id,
                revision=event.resulting_revision,
                last_event_sha256=event.event_sha256,
                event_count=state.event_count + 1,
                event_ids=state.event_ids | {event.event_id},
                command_ids=state.command_ids | {event.command_id},
            )
    except portalocker.exceptions.LockException as error:
        raise JournalError("canonical writer lock is held") from error
