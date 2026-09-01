"""Legacy-compatible segmented journal discovery, append, and replay."""

from __future__ import annotations

import os
import re
import signal
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import portalocker
from pydantic import ValidationError

from arw.kernel.core.canonical import (
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
    RecoveryHealth,
    RunInitializedPayload,
    RunManifest,
    ZERO_HASH,
)
from arw.manifests import (
    ManifestError,
    validate_accepted_event_manifests,
    validate_event_manifest_semantics,
)
from arw.recovery import (
    RecoveryError,
    publish_recovery_segment,
    validate_recovery_boundary,
)
from arw.kernel.core.faults import active_fault, inject
from arw.workflows import LEGACY_WORKFLOW_ID, WorkflowDefinitionError, require_workflow


MANIFEST_NAME = "run-manifest.json"
JOURNAL_NAME = "events.jsonl"
SEGMENTS_RELATIVE = Path("journal/segments")
SEGMENT_PATTERN = re.compile(r"^(?P<index>[0-9]{8})\.jsonl$")
LOCK_NAME = ".journal.lock"
FAILPOINT_ENV = "ARW_TEST_FAILPOINT"
POST_FSYNC_SIGKILL = "post-journal-fsync-sigkill"
PARTIAL_RUNTIME_APPEND_SIGKILL = "partial-runtime-append-sigkill"


class JournalError(RuntimeError):
    """Canonical run bytes are absent, malformed, stale, or unsafe to mutate."""


@dataclass(frozen=True)
class SegmentScan:
    index: int
    name: str
    relative_path: str
    byte_count: int
    sha256: str
    accepted_byte_end: int
    events: tuple[CanonicalEvent, ...]
    fault_offset: int | None = None
    fault_class: str | None = None
    raw_tail: bytes = b""


@dataclass(frozen=True)
class ReplayState:
    run_id: str
    revision: int
    last_event_sha256: str
    event_count: int
    event_ids: frozenset[str]
    command_ids: frozenset[str]
    workflow_definition_id: str = LEGACY_WORKFLOW_ID
    events: tuple[CanonicalEvent, ...] = ()
    segments: tuple[SegmentScan, ...] = ()
    journal_layout: str | None = None
    recovery_health: RecoveryHealth = "healthy"
    recovery_message: str | None = None
    # Set only by replay_run/_replay_unlocked after validating canonical
    # manifest, journal segments, and accepted manifests.  Callers cannot
    # launder an arbitrary state object into dossier authority.
    validated: bool = False

    def public_dict(self) -> dict[str, object]:
        return {
            "event_count": self.event_count,
            "last_event_sha256": self.last_event_sha256,
            "revision": self.revision,
            "run_id": self.run_id,
        }


def prepare_new_run_root(run_root: Path) -> Path:
    if run_root.is_symlink():
        raise JournalError("run root must not be a symlink")
    run_root.mkdir(parents=True, exist_ok=True)
    if not run_root.is_dir():
        raise JournalError("run root is not a directory")
    return run_root.resolve()


_validated_root = prepare_new_run_root


def require_existing_run_root(run_root: Path) -> Path:
    if run_root.is_symlink():
        raise JournalError("run root must not be a symlink")
    if not run_root.exists():
        raise JournalError("run root does not exist")
    if not run_root.is_dir():
        raise JournalError("run root is not a directory")
    return run_root.resolve()


_existing_root = require_existing_run_root


def _lock(run_root: Path, timeout: float) -> portalocker.Lock:
    if timeout < 0:
        raise JournalError("lock timeout must be non-negative")
    lock_path = run_root / LOCK_NAME
    if lock_path.is_symlink() or (lock_path.exists() and not lock_path.is_file()):
        raise JournalError("canonical writer lock file is unsafe")
    return portalocker.Lock(
        lock_path,
        mode="a+b",
        timeout=timeout,
        check_interval=0.01,
    )


def _read_lock(run_root: Path, timeout: float) -> portalocker.Lock:
    if timeout < 0:
        raise JournalError("lock timeout must be non-negative")
    lock_path = run_root / LOCK_NAME
    if lock_path.is_symlink() or not lock_path.is_file():
        raise JournalError("canonical writer lock file is missing or unsafe")
    return portalocker.Lock(
        lock_path,
        mode="rb",
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


def _event_wire_mapping(event: CanonicalEvent) -> dict[str, object]:
    value = event.model_dump(mode="json")
    if event.actor_role is None:
        value.pop("actor_role")
    return value


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

    root = prepare_new_run_root(run_root)
    _input_digest_matches(root, request.immutable_input)
    if request.workflow_definition_id is not None:
        try:
            definition = require_workflow(request.workflow_definition_id)
        except WorkflowDefinitionError as error:
            raise JournalError(str(error)) from error
        if definition.sha256 != request.workflow_definition_sha256:
            raise JournalError("workflow definition digest does not match the registry")
    manifest = RunManifest(
        schema_version=request.schema_version,
        run_id=request.run_id,
        created_at=request.occurred_at,
        immutable_input=request.immutable_input,
        workflow_family=request.workflow_family,
        workflow_mode=request.workflow_mode,
        workflow_definition_id=request.workflow_definition_id,
        workflow_definition_sha256=request.workflow_definition_sha256,
        journal_layout=request.journal_layout,
        capabilities=request.capabilities,
    )
    manifest_bytes = canonical_json_bytes(manifest.model_dump(mode="json", exclude_none=True))
    unsigned: dict[str, object] = {
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
        "payload": RunInitializedPayload(manifest_sha256=sha256_hex(manifest_bytes)).model_dump(
            mode="json"
        ),
    }
    if request.journal_layout is not None:
        unsigned["actor_role"] = "parent_control_plane"
    initial = _event_from_unsigned(unsigned)
    event_bytes = canonical_json_bytes(_event_wire_mapping(initial))
    manifest_path = root / MANIFEST_NAME
    segmented = request.journal_layout == "segmented-v1"
    journal_path = root / SEGMENTS_RELATIVE / "00000001.jsonl" if segmented else root / JOURNAL_NAME
    journal_root = root / "journal"
    segments_root = root / SEGMENTS_RELATIVE
    try:
        with _lock(root, lock_timeout):
            if (
                manifest_path.exists()
                or (root / JOURNAL_NAME).exists()
                or journal_root.exists()
            ):
                raise JournalError("run is already initialized or partially present")
            if segmented:
                journal_root.mkdir()
                segments_root.mkdir()
                _fsync_directory(segments_root)
                _fsync_directory(journal_root)
            _write_exclusive(manifest_path, manifest_bytes)
            try:
                _write_exclusive(journal_path, event_bytes)
            except BaseException:
                manifest_path.unlink(missing_ok=True)
                if segmented:
                    segments_root.rmdir()
                    journal_root.rmdir()
                raise
            if segmented:
                _fsync_directory(segments_root)
                _fsync_directory(journal_root)
            _fsync_directory(root)
            return _replay_unlocked(root)
    except portalocker.exceptions.LockException as error:
        raise JournalError("canonical writer lock is held") from error


def _strict_model(model: type[Any], value: object, label: str) -> Any:
    try:
        return model.model_validate(value)
    except ValidationError as error:
        raise JournalError(f"invalid {label}: {error}") from error


def _read_manifest(root: Path) -> tuple[RunManifest, bytes]:
    manifest_path = root / MANIFEST_NAME
    if manifest_path.is_symlink():
        raise JournalError("manifest must not be a symlink")
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest_payload = strict_json_loads(manifest_bytes)
    except (OSError, UnicodeError, ValueError) as error:
        raise JournalError(f"manifest is missing or malformed: {error}") from error
    manifest: RunManifest = _strict_model(RunManifest, manifest_payload, "manifest")
    if canonical_json_bytes(manifest.model_dump(mode="json", exclude_none=True)) != manifest_bytes:
        raise JournalError("manifest bytes are not canonical")
    if manifest.workflow_definition_id is not None:
        try:
            definition = require_workflow(manifest.workflow_definition_id)
        except WorkflowDefinitionError as error:
            raise JournalError(str(error)) from error
        if definition.sha256 != manifest.workflow_definition_sha256:
            raise JournalError("manifest workflow definition digest does not match the registry")
    return manifest, manifest_bytes


def _discover_segments(root: Path, manifest: RunManifest) -> tuple[Path, ...]:
    legacy_path = root / JOURNAL_NAME
    journal_root = root / "journal"
    if manifest.journal_layout is None:
        if journal_root.exists() or journal_root.is_symlink():
            raise JournalError("legacy run contains an undeclared journal directory")
        if legacy_path.is_symlink() or not legacy_path.is_file():
            raise JournalError("legacy journal is missing or unsafe")
        return (legacy_path,)

    if legacy_path.exists() or legacy_path.is_symlink():
        raise JournalError("segmented run contains an undeclared legacy journal")
    segments_root = root / SEGMENTS_RELATIVE
    if (
        journal_root.is_symlink()
        or not journal_root.is_dir()
        or segments_root.is_symlink()
        or not segments_root.is_dir()
    ):
        raise JournalError("segmented journal directories are missing or unsafe")
    discovered: list[tuple[int, Path]] = []
    for candidate in segments_root.iterdir():
        match = SEGMENT_PATTERN.fullmatch(candidate.name)
        if candidate.is_symlink() or not candidate.is_file() or match is None:
            raise JournalError(f"unexpected or unsafe segment entry: {candidate.name}")
        discovered.append((int(match.group("index")), candidate))
    discovered.sort(key=lambda item: item[0])
    if not discovered:
        raise JournalError("segmented journal has no segments")
    for expected, (actual, _) in enumerate(discovered, start=1):
        if actual != expected:
            raise JournalError(
                f"segment sequence is not contiguous: expected {expected:08d}, found {actual:08d}"
            )
    return tuple(path for _, path in discovered)


def _replay_unlocked(root: Path) -> ReplayState:
    manifest, manifest_bytes = _read_manifest(root)
    segment_paths = _discover_segments(root, manifest)
    revision = 0
    previous_hash = ZERO_HASH
    event_ids: set[str] = set()
    command_ids: set[str] = set()
    events: list[CanonicalEvent] = []
    segments: list[SegmentScan] = []
    manifest_hash = sha256_hex(manifest_bytes)
    recovery_health: RecoveryHealth = "healthy"
    recovery_message: str | None = None
    pending_damaged: SegmentScan | None = None
    reduced_state = None
    candidate_reduced_state = None

    def validate_event(payload: object, line: bytes, event_number: int) -> CanonicalEvent:
        nonlocal candidate_reduced_state, revision, previous_hash
        event: CanonicalEvent = _strict_model(
            CanonicalEvent, payload, f"event {event_number}"
        )
        wire_event = _event_wire_mapping(event)
        if canonical_json_bytes(wire_event) != line:
            raise JournalError(f"journal event {event_number} bytes are not canonical")
        actual_hash = sha256_hex(canonical_event_bytes(wire_event))
        if event.event_sha256 != actual_hash:
            raise JournalError(f"journal event {event_number} hash does not cover its bytes")
        if event.run_id != manifest.run_id:
            raise JournalError(f"journal event {event_number} run identity differs from manifest")
        if event.sequence != event_number:
            raise JournalError(f"journal event {event_number} sequence is not contiguous")
        if event.expected_revision != revision or event.resulting_revision != revision + 1:
            raise JournalError(f"journal event {event_number} revision is not contiguous")
        if event.prev_event_sha256 != previous_hash:
            raise JournalError(f"journal event {event_number} previous hash does not match")
        if event.event_id in event_ids or event.command_id in command_ids:
            raise JournalError(f"journal event {event_number} repeats an accepted identity")
        if event_number == 1:
            if event.event_type != "run.initialized":
                raise JournalError("first journal event must initialize the run")
            if not isinstance(event.payload, RunInitializedPayload):
                raise JournalError("first journal event has the wrong payload")
            if event.payload.manifest_sha256 != manifest_hash:
                raise JournalError("first journal event does not bind the manifest bytes")
        elif manifest.journal_layout is None and event.event_type != "baseline.probe_recorded":
            raise JournalError("Phase 1 journal contains an unsupported later event")
        if event.event_type in {"artifact.accepted", "passport.accepted"}:
            try:
                validate_accepted_event_manifests(root, (event,))
            except ManifestError as error:
                raise JournalError(str(error)) from error
        try:
            from arw.reducer import ReducerError, reduce_events

            candidate_reduced_state = reduce_events(
                manifest.workflow_definition_id or LEGACY_WORKFLOW_ID,
                (*events, event),
            )
            if event.event_type in {"artifact.accepted", "passport.accepted"}:
                if reduced_state is None:
                    raise ManifestError("accepted manifest has no prior runtime state")
                validate_event_manifest_semantics(root, event, reduced_state)
        except (ManifestError, ReducerError, WorkflowDefinitionError) as error:
            raise JournalError(f"runtime event {event_number} is invalid: {error}") from error
        return event

    def accept_event(event: CanonicalEvent, segment_events: list[CanonicalEvent]) -> None:
        nonlocal candidate_reduced_state, reduced_state, revision, previous_hash
        revision = event.resulting_revision
        previous_hash = event.event_sha256
        event_ids.add(event.event_id)
        command_ids.add(event.command_id)
        events.append(event)
        segment_events.append(event)
        reduced_state = candidate_reduced_state
        candidate_reduced_state = None

    for segment_index, segment_path in enumerate(segment_paths, start=1):
        try:
            segment_bytes = segment_path.read_bytes()
        except OSError as error:
            raise JournalError(f"segment {segment_path.name} is unreadable: {error}") from error
        segment_events: list[CanonicalEvent] = []
        accepted_byte_end = 0
        offset = 0
        if not segment_bytes:
            if not events:
                raise JournalError("journal has no trustworthy prefix: first segment is empty")
            segments.append(
                SegmentScan(
                    index=segment_index,
                    name=segment_path.name,
                    relative_path=segment_path.relative_to(root).as_posix(),
                    byte_count=0,
                    sha256=sha256_hex(segment_bytes),
                    accepted_byte_end=0,
                    events=(),
                    fault_offset=0,
                    fault_class="empty-segment",
                )
            )
            recovery_health = "blocked"
            recovery_message = "empty segment cannot establish a recovery boundary"
            break

        while offset < len(segment_bytes):
            newline = segment_bytes.find(b"\n", offset)
            has_newline = newline >= 0
            line_end = newline + 1 if has_newline else len(segment_bytes)
            line = segment_bytes[offset:line_end]
            is_terminal_record = line_end == len(segment_bytes)
            event_number = len(events) + 1
            try:
                payload = strict_json_loads(line)
            except UnicodeError as error:
                fault_class = "truncated-utf8" if not has_newline else "malformed-record"
                fault_message = str(error)
            except ValueError as error:
                fault_class = "incomplete-record" if not has_newline else "malformed-record"
                fault_message = str(error)
            else:
                try:
                    event = validate_event(payload, line, event_number)
                    if pending_damaged is not None:
                        if offset != 0 or event.event_type != "recovery.completed":
                            raise RecoveryError(
                                "segment after damaged tail must begin with recovery.completed"
                            )
                        validate_recovery_boundary(root, event, pending_damaged)
                        pending_damaged = None
                    elif event.event_type == "recovery.completed":
                        raise RecoveryError(
                            "recovery.completed is legal only as the first event after a damaged tail"
                        )
                except (JournalError, RecoveryError) as error:
                    if not events:
                        raise JournalError(
                            f"journal has no trustworthy prefix: {error}"
                        ) from error
                    segments.append(
                        SegmentScan(
                            index=segment_index,
                            name=segment_path.name,
                            relative_path=segment_path.relative_to(root).as_posix(),
                            byte_count=len(segment_bytes),
                            sha256=sha256_hex(segment_bytes),
                            accepted_byte_end=accepted_byte_end,
                            events=tuple(segment_events),
                            fault_offset=offset,
                            fault_class=(
                                "recovery-binding"
                                if isinstance(error, RecoveryError)
                                else "event-integrity"
                            ),
                            raw_tail=segment_bytes[offset:],
                        )
                    )
                    recovery_health = "blocked"
                    recovery_message = str(error)
                    break
                accept_event(event, segment_events)
                offset = line_end
                accepted_byte_end = offset
                continue

            if not events:
                raise JournalError(
                    f"journal has no trustworthy prefix: malformed first event: {fault_message}"
                )
            if pending_damaged is not None:
                segments.append(
                    SegmentScan(
                        index=segment_index,
                        name=segment_path.name,
                        relative_path=segment_path.relative_to(root).as_posix(),
                        byte_count=len(segment_bytes),
                        sha256=sha256_hex(segment_bytes),
                        accepted_byte_end=accepted_byte_end,
                        events=tuple(segment_events),
                        fault_offset=offset,
                        fault_class="recovery-binding",
                        raw_tail=segment_bytes[offset:],
                    )
                )
                recovery_health = "blocked"
                recovery_message = "recovery boundary first record is malformed"
                break
            recoverable = is_terminal_record and manifest.journal_layout == "segmented-v1"
            scan = SegmentScan(
                index=segment_index,
                name=segment_path.name,
                relative_path=segment_path.relative_to(root).as_posix(),
                byte_count=len(segment_bytes),
                sha256=sha256_hex(segment_bytes),
                accepted_byte_end=accepted_byte_end,
                events=tuple(segment_events),
                fault_offset=offset,
                fault_class=fault_class,
                raw_tail=segment_bytes[offset:],
            )
            segments.append(scan)
            if not recoverable:
                recovery_health = "blocked"
                recovery_message = "malformed record is not the final segment suffix"
            elif segment_index < len(segment_paths):
                pending_damaged = scan
            else:
                recovery_health = "recoverable_tail"
                recovery_message = fault_message
            break
        else:
            segments.append(
                SegmentScan(
                    index=segment_index,
                    name=segment_path.name,
                    relative_path=segment_path.relative_to(root).as_posix(),
                    byte_count=len(segment_bytes),
                    sha256=sha256_hex(segment_bytes),
                    accepted_byte_end=accepted_byte_end,
                    events=tuple(segment_events),
                )
            )

        if recovery_health == "blocked":
            break
        if pending_damaged is not None and segment_index == len(segment_paths):
            recovery_health = "recoverable_tail"
            recovery_message = "damaged terminal suffix requires explicit recovery"

    if pending_damaged is not None and recovery_health == "healthy":
        recovery_health = "blocked"
        recovery_message = "damaged segment is not followed by a valid recovery boundary"

    return ReplayState(
        run_id=manifest.run_id,
        revision=revision,
        last_event_sha256=previous_hash,
        event_count=len(events),
        event_ids=frozenset(event_ids),
        command_ids=frozenset(command_ids),
        workflow_definition_id=manifest.workflow_definition_id or LEGACY_WORKFLOW_ID,
        events=tuple(events),
        segments=tuple(segments),
        journal_layout=manifest.journal_layout,
        recovery_health=recovery_health,
        recovery_message=recovery_message,
        validated=True,
    )


def replay_run(run_root: Path, *, lock_timeout: float = 0.2) -> ReplayState:
    """Validate and replay solely from immutable manifest and canonical JSONL."""

    root = _existing_root(run_root)
    try:
        with _read_lock(root, lock_timeout):
            # Read-side lock acquisition is also part of the qualification
            # boundary; a lock fault must not be observable only on mutation.
            inject("phase7.lock-acquire")
            return _replay_unlocked(root)
    except portalocker.exceptions.LockException as error:
        raise JournalError("canonical writer lock is held") from error


@contextmanager
def locked_replay(
    run_root: Path, *, lock_timeout: float = 0.2
) -> Iterator[tuple[Path, ReplayState]]:
    """Yield one accepted state while holding the sole canonical writer lock."""

    root = require_existing_run_root(run_root)
    try:
        with _lock(root, lock_timeout):
            # This guarded seam runs only after the OS lock is acquired.  It
            # lets the parent matrix prove lock acquisition/owner-death
            # behavior without exposing a request-controlled bypass.
            inject("phase7.lock-acquire")
            inject("phase7.lock-owner-death", kill=True)
            yield root, _replay_unlocked(root)
    except portalocker.exceptions.LockException as error:
        raise JournalError("canonical writer lock is held") from error


def build_runtime_event(
    state: ReplayState,
    *,
    event_type: str,
    event_id: str,
    command_id: str,
    occurred_at: str,
    actor_id: str,
    actor_role: str,
    payload: object,
) -> CanonicalEvent:
    """Construct one canonical event using only writer-owned chain fields."""

    payload_value = (
        payload.model_dump(mode="json")
        if hasattr(payload, "model_dump")
        else payload
    )
    return _event_from_unsigned(
        {
            "schema_version": "1.0.0",
            "event_type": event_type,
            "event_id": event_id,
            "command_id": command_id,
            "run_id": state.run_id,
            "sequence": state.event_count + 1,
            "occurred_at": occurred_at,
            "expected_revision": state.revision,
            "resulting_revision": state.revision + 1,
            "actor_id": actor_id,
            "actor_role": actor_role,
            "prev_event_sha256": state.last_event_sha256,
            "payload": payload_value,
        }
    )


def append_runtime_event_unlocked(
    root: Path,
    state: ReplayState,
    event: CanonicalEvent,
) -> tuple[CanonicalEvent, ReplayState]:
    """Append one prevalidated event; callers must hold ``locked_replay``."""

    if not state.segments:
        raise JournalError("accepted replay has no active segment")
    if state.journal_layout != "segmented-v1":
        raise JournalError("Phase 2 runtime events require a segmented journal")
    if state.recovery_health != "healthy":
        raise JournalError("runtime append requires a healthy journal")
    if (
        event.run_id != state.run_id
        or event.sequence != state.event_count + 1
        or event.expected_revision != state.revision
        or event.resulting_revision != state.revision + 1
        or event.prev_event_sha256 != state.last_event_sha256
    ):
        raise JournalError("runtime event does not extend the accepted tip")
    segment_path = root / state.segments[-1].relative_path
    # The candidate event has already been validated and all chain fields are
    # parent-derived.  A write-before-commit fault therefore leaves no bytes
    # behind and cannot manufacture a retry attempt in the child.
    inject("phase7.canonical-write-before-commit")
    inject("phase7.hard-termination")
    inject("phase7.io-failure")
    inject("phase7.disk-exhaustion")
    before_size = segment_path.stat().st_size
    event_bytes = canonical_json_bytes(_event_wire_mapping(event))
    if segment_path.stat().st_size != before_size:
        raise JournalError("journal changed during locked replay")
    with segment_path.open("ab") as handle:
        torn = active_fault("phase7.torn-final-write")
        if (
            os.environ.get(FAILPOINT_ENV) == PARTIAL_RUNTIME_APPEND_SIGKILL
            or (torn is not None and torn.action == "torn-write")
        ):
            handle.write(event_bytes[: max(1, len(event_bytes) // 2)])
            handle.flush()
            os.fsync(handle.fileno())
            os.kill(os.getpid(), signal.SIGKILL)
        handle.write(event_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    # The event is durable before this seam fires.  A parent replay can prove
    # whether the command receipt was lost without accepting a duplicate.
    inject("phase7.journal-fsync")
    return event, _replay_unlocked(root)


def publish_recovery_event_unlocked(
    root: Path,
    state: ReplayState,
    event: CanonicalEvent,
) -> tuple[CanonicalEvent, ReplayState]:
    """Publish one recovery-first next segment; caller holds the writer lock."""

    if state.journal_layout != "segmented-v1" or not state.segments:
        raise JournalError("recovery requires a segmented journal")
    if state.recovery_health != "recoverable_tail":
        raise JournalError("recovery publication requires a recoverable terminal tail")
    if (
        event.event_type != "recovery.completed"
        or event.run_id != state.run_id
        or event.sequence != state.event_count + 1
        or event.expected_revision != state.revision
        or event.resulting_revision != state.revision + 1
        or event.prev_event_sha256 != state.last_event_sha256
    ):
        raise JournalError("recovery event does not extend the trustworthy prefix")
    publish_recovery_segment(
        root,
        segment_index=state.segments[-1].index + 1,
        event=event,
    )
    replayed = _replay_unlocked(root)
    if replayed.recovery_health != "healthy":
        raise JournalError("published recovery segment did not restore healthy replay")
    return event, replayed


def append_probe(
    run_root: Path,
    request: AppendProbeRequest,
    *,
    lock_timeout: float = 0.2,
) -> ReplayState:
    """Replay under lock and append exactly one fsynced baseline event."""

    failpoint = _requested_failpoint()
    root = require_existing_run_root(run_root)
    try:
        with _lock(root, lock_timeout):
            state = _replay_unlocked(root)
            if state.recovery_health != "healthy":
                raise JournalError("baseline append requires a healthy journal")
            if state.journal_layout is not None:
                raise JournalError("baseline append only supports legacy journals")
            journal_path = root / state.segments[-1].relative_path
            before_size = journal_path.stat().st_size
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
            event_bytes = canonical_json_bytes(_event_wire_mapping(event))
            if journal_path.stat().st_size != before_size:
                raise JournalError("journal changed during locked replay")
            with journal_path.open("ab") as handle:
                handle.write(event_bytes)
                handle.flush()
                os.fsync(handle.fileno())
            if failpoint == POST_FSYNC_SIGKILL:
                os.kill(os.getpid(), signal.SIGKILL)
            return _replay_unlocked(root)
    except portalocker.exceptions.LockException as error:
        raise JournalError("canonical writer lock is held") from error
