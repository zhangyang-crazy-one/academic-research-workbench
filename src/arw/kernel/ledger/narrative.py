"""Project paper-strategy journal and read guard shared by every provider."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import portalocker

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.state.models import NarrativeRunBinding, RunManifest
from arw.kernel.state.narrative import NarrativePlan, NarrativeSnapshot
from arw.kernel.state.research_memory import ProjectIdentity

ZERO = "0" * 64
RELATIVE = Path(".arw/narrative/events.jsonl")
LOCK = Path(".arw/narrative/.lock")
MAX_HISTORY = 1_048_576


class NarrativeError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _root(value: Path) -> Path:
    path = Path(value).absolute()
    if not path.is_dir() or any(part.is_symlink() for part in (path, *path.parents)):
        raise NarrativeError(
            "invalid_project_root", "project root must be a real directory"
        )
    return path.resolve(strict=True)


def _identity(root: Path) -> ProjectIdentity:
    try:
        return ProjectIdentity.model_validate(
            strict_json_loads(
                read_retained_bytes(root, ".arw/project.json", max_bytes=4096)
            )
        )
    except (ValueError, OSError, RuntimeError) as error:
        raise NarrativeError(
            "project_identity_invalid", "project identity is invalid"
        ) from error


def _history_path(root: Path) -> Path:
    return root / RELATIVE


@contextmanager
def _locked(root: Path, *, write: bool) -> Iterator[Path]:
    root = _root(root)
    directory = root / ".arw/narrative"
    if (
        (root / ".arw").is_symlink()
        or directory.is_symlink()
        or (root / LOCK).is_symlink()
    ):
        raise NarrativeError("unsafe_state", "narrative state path contains a symlink")
    if write:
        directory.mkdir(parents=True, exist_ok=True)
    if not directory.is_dir() or directory.is_symlink():
        raise NarrativeError(
            "not_applicable", "project has no paper narrative registration"
        )
    lock = root / LOCK
    try:
        with portalocker.Lock(
            lock,
            mode="a+b",
            flags=(portalocker.LOCK_EX if write else portalocker.LOCK_SH)
            | portalocker.LOCK_NB,
            timeout=2,
        ):
            yield root
    except portalocker.exceptions.LockException as error:
        raise NarrativeError(
            "narrative_busy", "narrative writer lock is held"
        ) from error


def _read(root: Path) -> tuple[list[dict], NarrativeSnapshot | None, dict | None]:
    path = _history_path(root)
    if path.is_symlink() or not path.is_file():
        raise NarrativeError(
            "missing_selection", "paper project has no narrative history"
        )
    if path.stat().st_size > MAX_HISTORY:
        raise NarrativeError("corrupt_history", "narrative history exceeds budget")
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n"):
        raise NarrativeError("corrupt_history", "narrative history is incomplete")
    events: list[dict] = []
    snapshot = None
    pending = None
    previous = ZERO
    project_id = _identity(root).project_id
    try:
        for line in raw.splitlines(keepends=True):
            event = strict_json_loads(line)
            if not isinstance(event, dict) or canonical_json_bytes(event) != line:
                raise ValueError("event bytes are noncanonical")
            expected = sha256_hex(
                canonical_json_bytes(
                    {k: v for k, v in event.items() if k != "event_sha256"}
                )
            )
            if (
                set(event)
                != {
                    "schema_version",
                    "sequence",
                    "kind",
                    "project_id",
                    "version",
                    "previous_sha256",
                    "payload",
                    "event_sha256",
                }
                or event["schema_version"] != "arw.narrative-event.v1"
                or event["event_sha256"] != expected
                or event["previous_sha256"] != previous
                or event["project_id"] != project_id
                or type(event["sequence"]) is not int
                or event["sequence"] != len(events) + 1
            ):
                raise ValueError("event chain or identity is invalid")
            kind, version, payload = event["kind"], event["version"], event["payload"]
            if type(version) is not int or not isinstance(payload, dict):
                raise ValueError("invalid event fields")
            if (
                kind == "registered"
                and not events
                and version == 0
                and payload == {"scope": "paper"}
            ):
                pass
            elif (
                kind == "selected"
                and len(events) == 1
                and snapshot is None
                and version == 1
                and set(payload) == {"plan"}
            ):
                plan = NarrativePlan.model_validate(payload["plan"])
                snapshot = NarrativeSnapshot(
                    project_id=project_id,
                    version=1,
                    sha256=event["event_sha256"],
                    plan=plan,
                )
            elif (
                kind == "proposed"
                and snapshot is not None
                and pending is None
                and version == snapshot.version
                and set(payload) == {"plan", "expected_sha256", "reason"}
                and payload["expected_sha256"] == snapshot.sha256
                and isinstance(payload["reason"], str)
                and payload["reason"].strip()
            ):
                NarrativePlan.model_validate(payload["plan"])
                pending = event
            elif (
                kind == "approved"
                and snapshot is not None
                and pending is not None
                and version == snapshot.version + 1
                and set(payload) == {"proposal_sha256", "author_id"}
                and payload["proposal_sha256"] == pending["event_sha256"]
                and isinstance(payload["author_id"], str)
                and payload["author_id"].strip()
            ):
                snapshot = NarrativeSnapshot(
                    project_id=project_id,
                    version=version,
                    sha256=event["event_sha256"],
                    plan=NarrativePlan.model_validate(pending["payload"]["plan"]),
                )
                pending = None
            else:
                raise ValueError("invalid narrative transition")
            events.append(event)
            previous = event["event_sha256"]
    except (ValueError, KeyError, TypeError, OSError) as error:
        raise NarrativeError(
            "corrupt_history", "narrative history is invalid"
        ) from error
    return events, snapshot, pending


def _append(
    root: Path, events: list[dict], kind: str, version: int, payload: dict
) -> dict:
    unsigned = {
        "schema_version": "arw.narrative-event.v1",
        "sequence": len(events) + 1,
        "kind": kind,
        "project_id": _identity(root).project_id,
        "version": version,
        "previous_sha256": events[-1]["event_sha256"] if events else ZERO,
        "payload": payload,
    }
    event = {**unsigned, "event_sha256": sha256_hex(canonical_json_bytes(unsigned))}
    path = _history_path(root)
    encoded = canonical_json_bytes(event)
    if (
        sum(len(canonical_json_bytes(existing)) for existing in events) + len(encoded)
        > MAX_HISTORY
    ):
        raise NarrativeError(
            "history_full", "narrative history has reached its byte budget"
        )
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        if not events and os.fstat(fd).st_size:
            raise NarrativeError("concurrent_selection", "narrative already exists")
        remaining = memoryview(encoded)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise NarrativeError(
                    "write_failed", "narrative event write was incomplete"
                )
            remaining = remaining[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    return event


def register(project_root: Path) -> dict:
    root = _root(project_root)
    _identity(root)
    with _locked(root, write=True):
        if _history_path(root).exists():
            events, snapshot, pending = _read(root)
            return _status(snapshot, pending, events)
        _append(root, [], "registered", 0, {"scope": "paper"})
        return _status(None, None, [{}])


def select(project_root: Path, plan: NarrativePlan) -> NarrativeSnapshot:
    with _locked(project_root, write=True) as root:
        events, snapshot, _ = _read(root)
        if snapshot is not None:
            raise NarrativeError(
                "already_selected", "initial narrative is already selected"
            )
        event = _append(
            root, events, "selected", 1, {"plan": plan.model_dump(mode="json")}
        )
        return NarrativeSnapshot(
            project_id=_identity(root).project_id,
            version=1,
            sha256=event["event_sha256"],
            plan=plan,
        )


def propose(
    project_root: Path, plan: NarrativePlan, *, expected_sha256: str, reason: str
) -> dict:
    if not reason.strip() or len(reason.encode("utf-8")) > 2048:
        raise NarrativeError("change_reason_missing", "narrative change needs a reason")
    with _locked(project_root, write=True) as root:
        events, snapshot, pending = _read(root)
        if snapshot is None:
            raise NarrativeError(
                "missing_selection", "select an initial narrative first"
            )
        if snapshot.sha256 != expected_sha256:
            raise NarrativeError(
                "stale_narrative", "expected narrative version is stale"
            )
        if pending is not None:
            raise NarrativeError("pending_change", "resolve the pending proposal first")
        event = _append(
            root,
            events,
            "proposed",
            snapshot.version,
            {
                "plan": plan.model_dump(mode="json"),
                "expected_sha256": expected_sha256,
                "reason": reason,
            },
        )
        return {
            "status": "pending_change",
            "proposal_sha256": event["event_sha256"],
            "current": snapshot.model_dump(mode="json"),
        }


def approve(
    project_root: Path, *, proposal_sha256: str, author_id: str
) -> NarrativeSnapshot:
    if not author_id.strip() or len(author_id.encode("utf-8")) > 128:
        raise NarrativeError(
            "author_confirmation_missing", "author confirmation identity is required"
        )
    with _locked(project_root, write=True) as root:
        events, snapshot, pending = _read(root)
        if (
            snapshot is None
            or pending is None
            or pending["event_sha256"] != proposal_sha256
        ):
            raise NarrativeError(
                "stale_proposal", "approval must name the current pending proposal"
            )
        event = _append(
            root,
            events,
            "approved",
            snapshot.version + 1,
            {"proposal_sha256": proposal_sha256, "author_id": author_id},
        )
        return NarrativeSnapshot(
            project_id=snapshot.project_id,
            version=snapshot.version + 1,
            sha256=event["event_sha256"],
            plan=NarrativePlan.model_validate(pending["payload"]["plan"]),
        )


def _status(
    snapshot: NarrativeSnapshot | None, pending: dict | None, events: list[dict]
) -> dict:
    return {
        "status": "missing_selection"
        if snapshot is None
        else "pending_change"
        if pending
        else "selected",
        "current": snapshot.model_dump(mode="json") if snapshot else None,
        "pending_proposal_sha256": pending["event_sha256"] if pending else None,
        "event_count": len(events),
    }


def status(project_root: Path) -> dict:
    root = _root(project_root)
    if not _history_path(root).exists() and not (root / LOCK).exists():
        return {
            "status": "not_applicable",
            "current": None,
            "pending_proposal_sha256": None,
            "event_count": 0,
        }
    with _locked(root, write=False):
        events, snapshot, pending = _read(root)
        return _status(snapshot, pending, events)


def current(project_root: Path) -> NarrativeSnapshot:
    with _locked(project_root, write=False) as root:
        _, snapshot, _ = _read(root)
        if snapshot is None:
            raise NarrativeError(
                "missing_selection",
                "paper narrative must be selected before planning or writing",
            )
        return snapshot


def binding_for_start(project_root: Path, run_root: Path) -> NarrativeRunBinding:
    root = _root(project_root)
    run = Path(run_root).absolute()
    if not run.is_relative_to(root):
        raise NarrativeError(
            "project_run_mismatch", "paper run must be within its project root"
        )
    snapshot = current(root)
    return NarrativeRunBinding(
        project_relative_path=os.path.relpath(root, run),
        project_id=snapshot.project_id,
        initial_version=snapshot.version,
        initial_sha256=snapshot.sha256,
    )


def _binding_root(run_root: Path, binding: NarrativeRunBinding) -> Path:
    run = Path(run_root).resolve(strict=True)
    if Path(binding.project_relative_path).is_absolute():
        raise NarrativeError(
            "invalid_run_binding", "narrative project locator must be relative"
        )
    project = _root(run / binding.project_relative_path)
    if (
        os.path.relpath(project, run) != binding.project_relative_path
        or not run.is_relative_to(project)
        or _identity(project).project_id != binding.project_id
    ):
        raise NarrativeError(
            "project_run_mismatch", "run narrative project identity differs"
        )
    return project


@contextmanager
def guard_start(run_root: Path, binding: NarrativeRunBinding) -> Iterator[None]:
    root = _binding_root(run_root, binding)
    with _locked(root, write=False):
        _, snapshot, _ = _read(root)
        if (
            snapshot is None
            or snapshot.project_id != binding.project_id
            or snapshot.sha256 != binding.initial_sha256
            or snapshot.version != binding.initial_version
        ):
            raise NarrativeError(
                "stale_narrative",
                "paper run must start from the current selected narrative",
            )
        yield


@contextmanager
def guard_run(
    run_root: Path, *, expected_sha256: str | None = None
) -> Iterator[NarrativeSnapshot | None]:
    """Hold the project read lock through a paper operation so approval cannot race it."""
    try:
        manifest = RunManifest.model_validate(
            strict_json_loads(
                read_retained_bytes(
                    Path(run_root), "run-manifest.json", max_bytes=65536
                )
            )
        )
    except (ValueError, OSError, RuntimeError) as error:
        raise NarrativeError(
            "invalid_run_binding", "run manifest is missing or unsafe"
        ) from error
    if manifest.task_kind != "paper":
        yield None
        return
    if manifest.narrative_binding is None:
        raise NarrativeError(
            "invalid_run_binding", "paper run has no narrative binding"
        )
    root = _binding_root(run_root, manifest.narrative_binding)
    with _locked(root, write=False):
        events, snapshot, _ = _read(root)
        if snapshot is None:
            raise NarrativeError(
                "missing_selection", "paper project has no selected narrative"
            )
        if not any(
            e["event_sha256"] == manifest.narrative_binding.initial_sha256
            and e["version"] == manifest.narrative_binding.initial_version
            for e in events
        ):
            raise NarrativeError(
                "invalid_run_binding",
                "run startup narrative is absent from project history",
            )
        if expected_sha256 is not None and expected_sha256 != snapshot.sha256:
            raise NarrativeError(
                "stale_narrative", "agent or plan carries an obsolete narrative version"
            )
        yield snapshot
