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
MAX_TRAIL_CHOICES = 128
MAX_TRAIL_BYTES = 65_536
MAX_RUN_RELATIONS = 128
# Handoff/resume context keeps only the most recent abandoned routes.
MAX_SUMMARY_ABANDONED = 8


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
def _locked(
    root: Path, *, write: bool, create_lock: bool = True
) -> Iterator[Path]:
    """Hold the project narrative lock.

    Operational readers recreate a missing lock file, as before the trail
    export existed; a cloned project need not carry it. The trail export
    passes ``create_lock=False`` so a read-only projection never writes.
    """
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
    if not create_lock and not lock.is_file():
        raise NarrativeError("corrupt_history", "narrative lock is missing")
    try:
        with portalocker.Lock(
            lock,
            mode="a+b" if write or create_lock else "rb",
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
            elif (
                kind == "withdrawn"
                and snapshot is not None
                and pending is not None
                and version == snapshot.version
                and set(payload) == {"proposal_sha256", "author_id", "reason"}
                and payload["proposal_sha256"] == pending["event_sha256"]
                and isinstance(payload["author_id"], str)
                and payload["author_id"].strip()
                and len(payload["author_id"].encode("utf-8")) <= 128
                and isinstance(payload["reason"], str)
                and payload["reason"].strip()
                and len(payload["reason"].encode("utf-8")) <= 2048
            ):
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


def withdraw(
    project_root: Path, *, proposal_sha256: str, author_id: str, reason: str
) -> dict:
    """Record an author's withdrawal of one exact pending branch."""
    if not author_id.strip() or len(author_id.encode("utf-8")) > 128:
        raise NarrativeError(
            "author_confirmation_missing", "withdrawal requires an author identity"
        )
    if not reason.strip() or len(reason.encode("utf-8")) > 2048:
        raise NarrativeError("change_reason_missing", "withdrawal requires a reason")
    with _locked(project_root, write=True) as root:
        events, snapshot, pending = _read(root)
        if (
            snapshot is None
            or pending is None
            or pending["event_sha256"] != proposal_sha256
        ):
            raise NarrativeError(
                "stale_proposal", "withdrawal must name the current pending proposal"
            )
        event = _append(
            root,
            events,
            "withdrawn",
            snapshot.version,
            {
                "proposal_sha256": proposal_sha256,
                "author_id": author_id,
                "reason": reason,
            },
        )
        return {
            "status": "selected",
            "current": snapshot.model_dump(mode="json"),
            "withdrawal_sha256": event["event_sha256"],
        }


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


def _event_source(event: dict) -> dict:
    return {
        "sequence": event["sequence"],
        "kind": event["kind"],
        "event_sha256": event["event_sha256"],
    }


def _trail_view(
    events: list[dict], *, history_head_sha256: str, bounded: bool = True
) -> dict:
    choices: list[dict] = []
    active: dict | None = None
    pending: dict | None = None
    for event in events:
        kind = event["kind"]
        if kind in {"registered"}:
            continue
        if kind in {"selected", "proposed"}:
            plan = event["payload"]["plan"]
            choice = {
                "choice_id": event["event_sha256"],
                "version": event["version"] if kind == "selected" else None,
                "route": plan["route"],
                "disposition": "kept" if kind == "selected" else "unknown",
                "plan": plan,
                "plan_source": _event_source(event),
                "rationale": {
                    "text": plan["rationale"],
                    "source": _event_source(event),
                    "provenance": "recorded_plan_statement",
                },
                "change_reason": (
                    {
                        "text": event["payload"]["reason"],
                        "source": _event_source(event),
                        "provenance": "recorded_proposal_statement",
                    }
                    if kind == "proposed"
                    else None
                ),
                "successor": None,
                "supersession_reason": None,
                "author_confirmation": None,
            }
            choices.append(choice)
            if kind == "selected":
                active = choice
            else:
                pending = choice
            continue
        if kind == "withdrawn":
            assert pending is not None  # _read validated this transition
            pending["disposition"] = "abandoned"
            pending["withdrawal_reason"] = {
                "text": event["payload"]["reason"],
                "source": _event_source(event),
                "provenance": "recorded_withdrawal_statement",
            }
            pending["author_confirmation"] = {
                "author_id": event["payload"]["author_id"],
                "source": _event_source(event),
                "provenance": "operator_asserted_author_confirmation",
            }
            pending = None
            continue
        assert kind == "approved" and pending is not None and active is not None
        proposal = pending
        choices.remove(proposal)
        successor = {
            **proposal,
            "choice_id": event["event_sha256"],
            "version": event["version"],
            "disposition": "kept",
            "author_confirmation": {
                "author_id": event["payload"]["author_id"],
                "source": _event_source(event),
                "provenance": "operator_asserted_author_confirmation",
            },
        }
        active["disposition"] = "superseded"
        active["successor"] = {
            "choice_id": successor["choice_id"],
            "version": successor["version"],
            "source": _event_source(event),
        }
        active["supersession_reason"] = proposal["change_reason"]
        choices.append(successor)
        active = successor
        pending = None
    if bounded and len(choices) > MAX_TRAIL_CHOICES:
        raise NarrativeError(
            "trail_limit_exceeded", "narrative trail has too many choices"
        )
    result = {
        "schema_version": "arw.narrative-trail.v1",
        "status": (
            "missing_selection"
            if active is None
            else "pending_change"
            if pending
            else "selected"
        ),
        "project_id": events[0]["project_id"],
        "history_head_sha256": history_head_sha256,
        "view_head_sha256": events[-1]["event_sha256"],
        "view_sequence": events[-1]["sequence"],
        "choices": choices,
        "current_choice_ids": [active["choice_id"]] if active else [],
        "abandoned_choice_ids": [
            choice["choice_id"]
            for choice in choices
            if choice["disposition"] in {"superseded", "abandoned"}
        ],
        "unresolved_questions": (
            [{"kind": "pending_author_decision", "source": pending["plan_source"]}]
            if pending
            else []
        ),
    }
    if bounded and len(canonical_json_bytes(result)) > MAX_TRAIL_BYTES:
        raise NarrativeError(
            "trail_limit_exceeded", "narrative trail exceeds byte budget"
        )
    return result


def _run_relations(root: Path, run_root: Path, events: list[dict]) -> dict:
    """Include only explicit relations in one caller-named canonical paper run."""
    from arw.kernel.ledger.journal import replay_run

    run = Path(run_root).absolute()
    # ``root`` is symlink-free; a symlinked run component could point outside.
    if not run.is_relative_to(root) or run.resolve() != run:
        raise NarrativeError("project_run_mismatch", "run is outside the project")
    try:
        manifest = RunManifest.model_validate(
            strict_json_loads(
                read_retained_bytes(run, "run-manifest.json", max_bytes=65536)
            )
        )
    except (ValueError, OSError, RuntimeError) as error:
        raise NarrativeError(
            "invalid_run_binding", "run manifest is invalid"
        ) from error
    binding = manifest.narrative_binding
    if (
        manifest.task_kind != "paper"
        or binding is None
        or _binding_root(run, binding) != root
        or not any(
            event["event_sha256"] == binding.initial_sha256
            and event["version"] == binding.initial_version
            for event in events
        )
    ):
        raise NarrativeError(
            "invalid_run_binding", "run is not bound to this paper history"
        )
    try:
        state = replay_run(run)
    except (ValueError, OSError, RuntimeError) as error:
        raise NarrativeError(
            "corrupt_run_history", "run history cannot be replayed"
        ) from error
    if state.recovery_health != "healthy":
        raise NarrativeError("corrupt_run_history", "run history needs recovery")
    artifacts = []
    artifact_successors = []
    memory_successors = []
    for event in state.events:
        source = {
            "event_id": event.event_id,
            "event_sha256": event.event_sha256,
            "sequence": event.sequence,
        }
        payload = event.payload
        if event.event_type in {"artifact.accepted", "research_artifact_accepted"}:
            artifacts.append(
                {
                    "artifact_id": payload.artifact_id,
                    "artifact_sha256": payload.artifact_sha256,
                    "narrative_report_sha256": getattr(
                        payload, "narrative_report_sha256", None
                    ),
                    "source_event_sha256": getattr(payload, "source_event_sha256", []),
                    "source": source,
                }
            )
        elif event.event_type == "research_artifact_superseded":
            artifact_successors.append(
                {
                    "predecessor_artifact_id": payload.supersedes,
                    "successor_artifact_id": payload.artifact_id,
                    "source": source,
                }
            )
        elif event.event_type == "research_memory_superseded":
            memory_successors.append(
                {
                    "predecessor_memory_id": payload.memory_id,
                    "successor_memory_id": payload.successor_memory_id,
                    "source": source,
                }
            )
    if (
        len(artifacts) + len(artifact_successors) + len(memory_successors)
        > MAX_RUN_RELATIONS
    ):
        raise NarrativeError(
            "trail_limit_exceeded", "run has too many explicit relations"
        )
    return {
        "run_id": state.run_id,
        "initial_narrative_sha256": binding.initial_sha256,
        "relation_scope": "explicit_run_journal_only",
        "accepted_artifacts": artifacts,
        "artifact_successors": artifact_successors,
        "memory_successors": memory_successors,
    }


def trail(
    project_root: Path,
    *,
    at_sequence: int | None = None,
    expected_head_sha256: str | None = None,
    run_root: Path | None = None,
) -> dict:
    """Read-only deterministic projection of the validated project history."""
    return _trail(
        project_root,
        at_sequence=at_sequence,
        expected_head_sha256=expected_head_sha256,
        run_root=run_root,
        bounded=True,
    )


def _trail(
    project_root: Path,
    *,
    at_sequence: int | None,
    expected_head_sha256: str | None,
    run_root: Path | None,
    bounded: bool,
) -> dict:
    root = _root(project_root)
    if run_root is not None and at_sequence is not None:
        raise NarrativeError(
            "invalid_sequence",
            "historical project views cannot include current run records",
        )
    directory = root / ".arw/narrative"
    if not directory.exists() and not directory.is_symlink():
        if at_sequence is not None or expected_head_sha256 is not None or run_root is not None:
            raise NarrativeError(
                "missing_selection", "project has no narrative history"
            )
        return {
            "schema_version": "arw.narrative-trail.v1",
            "status": "not_applicable",
            "project_id": None,
            "history_head_sha256": None,
            "view_head_sha256": None,
            "view_sequence": 0,
            "choices": [],
            "current_choice_ids": [],
            "abandoned_choice_ids": [],
            "unresolved_questions": [],
        }
    # The export is strictly read-only; operational summaries may restore a
    # missing lock file like every other narrative reader.
    with _locked(root, write=False, create_lock=not bounded):
        events, _, _ = _read(root)
        head = events[-1]["event_sha256"]
        if expected_head_sha256 is not None and expected_head_sha256 != head:
            raise NarrativeError("stale_narrative", "narrative history head changed")
        if at_sequence is not None:
            if (
                type(at_sequence) is not int
                or at_sequence < 1
                or at_sequence > len(events)
            ):
                raise NarrativeError(
                    "invalid_sequence", "historical sequence is outside history"
                )
            events = events[:at_sequence]
        view = _trail_view(events, history_head_sha256=head, bounded=bounded)
        if run_root is not None:
            view["run_relations"] = _run_relations(root, run_root, events)
            if len(canonical_json_bytes(view)) > MAX_TRAIL_BYTES:
                raise NarrativeError(
                    "trail_limit_exceeded", "narrative trail exceeds byte budget"
                )
        return view


def trail_summary(
    project_root: Path, *, expected_head_sha256: str | None = None
) -> dict:
    """Bounded continuation context; never fails because history grew long.

    The full export keeps its explicit limits. Handoff and resume only carry
    the current route and the most recent abandoned routes, with the number
    omitted, so a long but valid history cannot block continuation.
    """
    view = _trail(
        project_root,
        at_sequence=None,
        expected_head_sha256=expected_head_sha256,
        run_root=None,
        bounded=False,
    )
    choices = {choice["choice_id"]: choice for choice in view["choices"]}

    def concise(choice_id: str) -> dict:
        choice = choices[choice_id]
        return {
            "choice_id": choice_id,
            "version": choice["version"],
            "route": choice["route"],
            "disposition": choice["disposition"],
            "plan_source": choice["plan_source"],
            "successor": choice["successor"],
            "change_reason": choice["change_reason"],
            "supersession_reason": choice["supersession_reason"],
            "withdrawal_reason": choice.get("withdrawal_reason"),
            "author_confirmation": choice["author_confirmation"],
        }

    abandoned = sorted(
        (concise(value) for value in view["abandoned_choice_ids"]),
        key=lambda row: row["plan_source"]["sequence"],
    )
    total = len(abandoned)
    kept = abandoned[-MAX_SUMMARY_ABANDONED:]

    def assemble(rows: list[dict]) -> dict:
        return {
            "schema_version": "arw.narrative-trail-summary.v1",
            "status": view["status"],
            "history_head_sha256": view["history_head_sha256"],
            "current_choices": [
                concise(value) for value in view["current_choice_ids"]
            ],
            "abandoned_routes": rows,
            "omitted_abandoned_route_count": total - len(rows),
            "unresolved_questions": view["unresolved_questions"],
            "interpretation": "Decision history is provenance, not a scientific finding or a recommendation.",
        }

    summary = assemble(kept)
    # Recorded reasons are individually bounded, so this only trims the
    # oldest retained rows in extreme cases; it never raises.
    while kept and len(canonical_json_bytes(summary)) > MAX_TRAIL_BYTES:
        kept = kept[1:]
        summary = assemble(kept)
    return summary


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


def bound_trail_summary(run_root: Path, snapshot: NarrativeSnapshot) -> dict:
    """Recheck a paper run's project binding before projecting continuation context."""
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
    if manifest.task_kind != "paper" or manifest.narrative_binding is None:
        raise NarrativeError(
            "invalid_run_binding", "paper run has no narrative binding"
        )
    root = _binding_root(run_root, manifest.narrative_binding)
    summary = trail_summary(root)
    if (
        not summary["current_choices"]
        or summary["current_choices"][0]["choice_id"] != snapshot.sha256
    ):
        raise NarrativeError(
            "stale_narrative", "trajectory differs from current narrative"
        )
    return summary


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
