"""Resumable research administration using retained requests and the run journal."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import portalocker

from arw.kernel.core.canonical import (
    canonical_json_bytes,
    sha256_hex,
    strict_json_loads,
)
from arw.kernel.core.privacy import reject_secret_shapes
from arw.kernel.ledger.journal import (
    JOURNAL_NAME,
    JournalError,
    initialization_is_pending,
    initialize_run,
    locked_replay,
    replay_run,
    validate_initialization_transaction,
)
from arw.kernel.ledger.manifests import validate_accepted_event_manifests
from arw.kernel.ledger.narrative import binding_for_start, guard_run
from arw.kernel.ledger.projects import initialize_project, project_identity
from arw.kernel.ledger.reducer import reduce_events
from arw.kernel.ledger.research_records import publish_once
from arw.kernel.ledger.source_locations import read_retained_bytes
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.policy.core_integrity import installed_core_preflight
from arw.kernel.state.models import (
    InitRunRequest,
    RunManifest,
)
from arw.kernel.state.research_memory import ProjectIdentity
from arw.kernel.state.research_startup import ResearchStartPlan
from arw.kernel.state.status import build_status_report

PLAN = ".arw/research/start.json"
REQUEST = ".arw/research/init-request.json"


class ResearchStartupError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def project_root(value: Path, *, create=False) -> Path:
    root = Path(value).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise ResearchStartupError(
            "unsafe_project_root", "project path contains a symlink"
        )
    if create:
        root.mkdir(parents=True, exist_ok=True)
    if not root.is_dir():
        raise ResearchStartupError("project_missing", "project directory is missing")
    return root


def _input(plan: ResearchStartPlan) -> bytes:
    return canonical_json_bytes(
        {
            "schema_version": "arw.research-intent.v1",
            "project_id": plan.project_id,
            "project_identity_sha256": plan.project_identity_sha256,
            "ars_project_ref": plan.ars_project_ref,
            "direction": plan.direction,
            "phase": plan.phase,
            "run_id": plan.request.run_id,
        }
    )


def load_plan(
    root: Path,
    *,
    expected_project_id=None,
    expected_run_id=None,
    allow_pending_identity=False,
) -> ResearchStartPlan:
    plan = ResearchStartPlan.model_validate(
        strict_json_loads(read_retained_bytes(root, PLAN, max_bytes=65536))
    )
    pending = (
        not (root / ".arw/project.json").exists()
        and not (root / ".arw/project.json").is_symlink()
    )
    if pending and allow_pending_identity:
        identity = ProjectIdentity(
            schema_version="arw.project.v1", project_id=plan.project_id
        )
        identity_raw = canonical_json_bytes(identity.model_dump(mode="json"))
    else:
        identity = project_identity(root)
        identity_raw = read_retained_bytes(root, ".arw/project.json", max_bytes=4096)
    if (
        identity.project_id != plan.project_id
        or sha256_hex(identity_raw) != plan.project_identity_sha256
        or expected_project_id is not None
        and identity.project_id != expected_project_id
        or expected_run_id is not None
        and plan.request.run_id != expected_run_id
    ):
        raise ResearchStartupError(
            "research_identity_conflict",
            "project or run identity differs from the retained startup",
        )
    if sha256_hex(_input(plan)) != plan.request.immutable_input.sha256:
        raise ResearchStartupError(
            "research_input_conflict", "retained intent differs from the frozen input"
        )
    return plan


def _new_plan(root, identity, direction, phase, task_kind, ars_project_ref=None):
    run_id = f"run-{uuid.uuid4()}"
    relative = f".arw/research/runs/{run_id}"
    identity_sha = sha256_hex(
        read_retained_bytes(root, ".arw/project.json", max_bytes=4096)
        if (root / ".arw/project.json").exists()
        else canonical_json_bytes(identity.model_dump(mode="json"))
    )
    body = canonical_json_bytes(
        {
            "schema_version": "arw.research-intent.v1",
            "project_id": identity.project_id,
            "project_identity_sha256": identity_sha,
            "ars_project_ref": ars_project_ref or identity.project_id,
            "direction": direction,
            "phase": phase,
            "run_id": run_id,
        }
    )
    binding = binding_for_start(root, root / relative) if task_kind == "paper" else None
    request = InitRunRequest(
        schema_version="1.0.0",
        run_id=run_id,
        occurred_at=datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        immutable_input={
            "path": "input/research-intent.json",
            "sha256": sha256_hex(body),
        },
        workflow_family="academic-pipeline",
        workflow_mode="inline-role-prompts",
        workflow_definition_id=CORE_WORKFLOW.definition_id,
        workflow_definition_sha256=CORE_WORKFLOW.sha256,
        journal_layout="segmented-v1",
        capabilities=["canonical-journal"],
        task_kind=task_kind,
        narrative_binding=binding,
        event_id=f"evt-{uuid.uuid4()}",
        command_id=f"cmd-{uuid.uuid4()}",
        actor_id="parent.research-startup",
    )
    return ResearchStartPlan(
        project_id=identity.project_id,
        project_identity_sha256=identity_sha,
        ars_project_ref=ars_project_ref or identity.project_id,
        direction=direction,
        phase=phase,
        run_relative=relative,
        request=request,
    )


def start(
    root: Path,
    *,
    direction=None,
    phase="scoping",
    task_kind="other",
    expected_project_id=None,
    expected_run_id=None,
    resume=False,
    plan_only=False,
    ars_project_ref=None,
    boundary=lambda _: None,
):
    installed_core_preflight()  # A damaged stage cannot downgrade to editable mode.
    if direction is not None:
        if (
            not isinstance(direction, str)
            or not direction.strip()
            or len(direction) > 2048
        ):
            raise ResearchStartupError(
                "research_direction_invalid", "direction must contain 1–2048 characters"
            )
        reject_secret_shapes(canonical_json_bytes({"direction": direction}))
    if task_kind == "paper" and phase != "writing":
        raise ResearchStartupError(
            "research_phase_invalid",
            "paper startup requires writing and an existing narrative selection",
        )
    if phase not in {
        "scoping",
        "literature",
        "experiment",
        "writing",
    } or task_kind not in {"other", "paper"}:
        raise ResearchStartupError(
            "research_phase_invalid", "unsupported research phase or task kind"
        )
    root = project_root(root, create=not resume)
    directory = root / ".arw/research"
    if any(p.is_symlink() for p in (root / ".arw", directory, directory / ".lock")):
        raise ResearchStartupError(
            "research_state_unsafe", "unsafe research state path"
        )
    if resume and not (root / PLAN).is_file():
        raise ResearchStartupError(
            "research_start_missing", "resume requires the retained startup request"
        )
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        with portalocker.Lock(
            directory / ".lock", mode="a+b", timeout=1, check_interval=0.01
        ):
            if (root / PLAN).exists() or (root / PLAN).is_symlink():
                plan = load_plan(
                    root,
                    expected_project_id=expected_project_id,
                    expected_run_id=expected_run_id,
                    allow_pending_identity=True,
                )
                if not resume and (
                    plan.direction,
                    plan.phase,
                    plan.request.task_kind,
                ) != (direction, phase, task_kind):
                    raise ResearchStartupError(
                        "research_intent_conflict",
                        "startup already binds a different research intent",
                    )
            else:
                if direction is None:
                    raise ResearchStartupError(
                        "research_direction_required", "start requires a direction"
                    )
                identity = (
                    project_identity(root)
                    if (root / ".arw/project.json").exists()
                    else ProjectIdentity(
                        schema_version="arw.project.v1",
                        project_id=expected_project_id or f"project-{uuid.uuid4()}",
                    )
                )
                if (
                    expected_project_id is not None
                    and identity.project_id != expected_project_id
                ):
                    raise ResearchStartupError(
                        "research_identity_conflict", "project identity differs"
                    )
                plan = _new_plan(
                    root, identity, direction, phase, task_kind, ars_project_ref
                )
                if (
                    expected_run_id is not None
                    and plan.request.run_id != expected_run_id
                ):
                    raise ResearchStartupError(
                        "research_run_conflict",
                        "a new startup cannot resume an unrelated run",
                    )
                publish_once(
                    root, PLAN, canonical_json_bytes(plan.model_dump(mode="json"))
                )
                boundary("plan_durable")
            if ars_project_ref is not None and ars_project_ref != plan.ars_project_ref:
                raise ResearchStartupError(
                    "research_ars_identity_conflict",
                    "ARS project reference differs from the frozen startup",
                )
            initialize_project(root, plan.project_id)
            load_plan(root, expected_project_id=plan.project_id)
            boundary("identity_durable")
            publish_once(
                root,
                REQUEST,
                canonical_json_bytes(
                    plan.request.model_dump(mode="json", exclude_none=True)
                ),
            )
            boundary("request_durable")
            if not plan_only:
                run = root / plan.run_relative
                publish_once(
                    root,
                    plan.run_relative + "/input/research-intent.json",
                    _input(plan),
                )
                boundary("input_durable")
                if not _journal_path(run, plan).exists():
                    if (run / "run-manifest.json").exists():
                        _require_pending_initialization(run, plan)
                    initialize_run(
                        run, plan.request, lock_timeout=1, resume_initialization=True
                    )
                else:
                    # Seal a surviving transaction before later parent writes;
                    # replay remains exclusively authoritative for accepted data.
                    try:
                        with locked_replay(run, lock_timeout=1):
                            pass
                    except JournalError as error:
                        raise ResearchStartupError(
                            "research_history_damaged",
                            "canonical history or initialization transaction is damaged",
                        ) from error
                boundary("run_durable")
                _validate_run(root, plan)
    except portalocker.exceptions.LockException as error:
        raise ResearchStartupError(
            "research_writer_busy", "research startup writer lock is held"
        ) from error
    return status(
        root, expected_project_id=plan.project_id, expected_run_id=plan.request.run_id
    )


def _expected_manifest(plan):
    expected = {
        k: v
        for k, v in plan.request.model_dump(mode="json", exclude_none=True).items()
        if k not in {"event_id", "command_id", "actor_id", "occurred_at"}
    }
    expected["created_at"] = plan.request.occurred_at
    return expected


def _journal_path(run, plan):
    return (
        run / "journal/segments/00000001.jsonl"
        if plan.request.journal_layout == "segmented-v1"
        else run / JOURNAL_NAME
    )


def _require_pending_initialization(run, plan):
    try:
        pending = initialization_is_pending(run, plan.request)
    except (JournalError, OSError) as error:
        raise ResearchStartupError(
            "research_history_damaged", "initialization transaction is damaged"
        ) from error
    if not pending:
        raise ResearchStartupError(
            "research_history_damaged",
            "canonical history is missing; explicit recovery is required",
        )


def _validate_run(root, plan):
    run = root / plan.run_relative
    raw = read_retained_bytes(run, "run-manifest.json", max_bytes=65536)
    manifest = RunManifest.model_validate(strict_json_loads(raw))
    expected = _expected_manifest(plan)
    if manifest.model_dump(mode="json", exclude_none=True) != expected:
        raise ResearchStartupError(
            "research_manifest_conflict",
            "run manifest differs from the retained startup",
        )
    if read_retained_bytes(
        run, "input/research-intent.json", max_bytes=65536
    ) != _input(plan):
        raise ResearchStartupError(
            "research_input_conflict", "run intent bytes changed"
        )
    replay = replay_run(run)
    first = replay.events[0]
    if (first.event_id, first.command_id, first.actor_id) != (
        plan.request.event_id,
        plan.request.command_id,
        plan.request.actor_id,
    ):
        raise ResearchStartupError(
            "research_initial_event_conflict",
            "initial event differs from the retained request",
        )
    if replay.recovery_health != "healthy":
        raise ResearchStartupError(
            "research_history_damaged", "canonical history needs explicit recovery"
        )
    validate_accepted_event_manifests(run, replay.events)
    try:
        validate_initialization_transaction(run, replay)
    except (JournalError, OSError) as error:
        raise ResearchStartupError(
            "research_history_damaged", "initialization transaction is damaged"
        ) from error
    return run, raw, replay


def status(root: Path, *, expected_project_id=None, expected_run_id=None):
    integrity, _ = installed_core_preflight()
    root = project_root(root)
    plan = load_plan(
        root,
        expected_project_id=expected_project_id,
        expected_run_id=expected_run_id,
        allow_pending_identity=True,
    )
    run = root / plan.run_relative
    committed = ["startup_plan"]
    identity_present = (root / ".arw/project.json").exists()
    if identity_present:
        committed.append("project_identity")
    if (root / REQUEST).exists():
        if read_retained_bytes(root, REQUEST, max_bytes=65536) != canonical_json_bytes(
            plan.request.model_dump(mode="json", exclude_none=True)
        ):
            raise ResearchStartupError(
                "research_request_conflict", "retained initialization request changed"
            )
        committed.append("initialization_request")
    initialized = (run / "run-manifest.json").exists() and _journal_path(
        run, plan
    ).exists()
    if (
        _journal_path(run, plan).exists() and not (run / "run-manifest.json").exists()
    ) or (initialized and not identity_present):
        raise ResearchStartupError(
            "research_history_damaged",
            "initialized history is missing its identity or manifest",
        )
    if (run / "run-manifest.json").exists() and not initialized:
        _require_pending_initialization(run, plan)
        manifest = RunManifest.model_validate(
            strict_json_loads(
                read_retained_bytes(run, "run-manifest.json", max_bytes=65536)
            )
        )
        if manifest.model_dump(mode="json", exclude_none=True) != _expected_manifest(
            plan
        ):
            raise ResearchStartupError(
                "research_manifest_conflict",
                "partial initialization differs from the retained request",
            )
    run_report = None
    accepted = 0
    gates = []
    if initialized:
        with guard_run(
            run,
            expected_sha256=plan.request.narrative_binding.initial_sha256
            if plan.request.narrative_binding
            else None,
        ):
            run, raw, replay = _validate_run(root, plan)
            projected = build_status_report(
                reduce_events(
                    replay.workflow_definition_id,
                    replay.events,
                    recovery_health=replay.recovery_health,
                )
            )
            run_report = {
                "run_id": replay.run_id,
                "manifest_sha256": sha256_hex(raw),
                "lifecycle": projected.status,
                "workflow_stage": projected.current_stage,
                "revision": replay.revision,
                "event_count": replay.event_count,
                "head_sha256": replay.last_event_sha256,
                "recovery_health": replay.recovery_health,
            }
            accepted = sum(e.event_type == "artifact.accepted" for e in replay.events)
            gates = [
                {"gate_id": g.gate_id, "verdict": g.verdict} for g in projected.gates
            ]
        committed.append("canonical_run")
    input_available = (run / "input/research-intent.json").exists()
    if input_available:
        if read_retained_bytes(
            run, "input/research-intent.json", max_bytes=65536
        ) != _input(plan):
            raise ResearchStartupError(
                "research_input_conflict", "run intent bytes changed"
            )
        committed.append("immutable_input")
    return {
        "schema_version": "arw.research-status.v1",
        "status": "ready_for_local_research" if initialized else "startup_incomplete",
        "core": {
            "integrity": integrity,
            "reason_codes": []
            if integrity == "PASS"
            else ["editable_checkout_unverified"],
        },
        "project": {
            "project_id": plan.project_id,
            "identity_sha256": plan.project_identity_sha256,
            "ars_project_ref": plan.ars_project_ref,
            "identity_state": "retained"
            if identity_present
            else "pending_initialization",
        },
        "intent": {
            "direction": plan.direction,
            "initial_phase": plan.phase,
            "task_kind": plan.request.task_kind,
            "scope": "declared_intent_not_completed_research",
        },
        "run": run_report,
        "planned_run_id": plan.request.run_id,
        "run_relative": plan.run_relative,
        "committed_steps": committed,
        "materials": {
            "intent_bytes": "available" if input_available else "missing",
            "accepted_record_count": accepted,
            "proof_scope": "record_integrity_not_scientific_support",
        },
        "operations": [
            {
                "operation": "local_research_administration",
                "status": "checked" if initialized else "pending",
            },
            {"operation": "retrieval", "status": "not_evaluated"},
            {"operation": "experiment_execution", "status": "not_evaluated"},
        ],
        "executor": {
            "status": "not_evaluated",
            "reason_code": "selected_executor_not_checked",
        },
        "scientific_evidence": {"status": "not_evaluated", "gates": gates},
        "next_steps": ["Review the retained initialization request and resume"]
        if not initialized
        else [
            "Author narrows the research question; retain versioned sources and decisions",
            "Accept materials through the existing artifact interface",
            "Select a narrative only when starting paper work",
        ],
    }


def retained_steps(root: Path) -> list[str]:
    """Bounded diagnostic for partial failure; presence is not admission."""
    root = Path(root).absolute()
    if any(p.is_symlink() for p in (root, *root.parents)):
        return []
    return [
        relative
        for relative in (".arw/project.json", PLAN, REQUEST)
        if (Path(root) / relative).is_file()
        and not (Path(root) / relative).is_symlink()
    ]
