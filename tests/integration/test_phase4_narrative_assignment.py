"""A Phase 4 worker contract carries and enforces the selected paper strategy."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.execution.execution import DeterministicFakeAdapter
from arw.kernel.execution.orchestration import (
    AssignmentSpec,
    OrchestrationError,
    OrchestrationService,
)
from arw.kernel.ledger.journal import initialize_run
from arw.kernel.ledger.manifests import load_assignment_manifest
from arw.kernel.ledger.narrative import (
    approve,
    binding_for_start,
    propose,
    register,
    select,
)
from arw.kernel.ledger.workflows import PHASE4_WORKFLOW
from arw.kernel.state.models import (
    InitRunRequest,
    LifecycleTransitionRequest,
    RuntimeCommandRequest,
)
from arw.kernel.state.narrative import NarrativePlan
from arw.kernel.state.orchestration_models import (
    PAPER_NARRATIVE_INSTRUCTIONS,
    AttemptDescriptor,
    GateDecision,
    ImmutableAssignment,
    WorkerProposal,
    canonical_orchestration_model_bytes,
)


def _plan(route: str = "method_rq") -> NarrativePlan:
    return NarrativePlan.model_validate(
        {
            "route": route,
            "rationale": "The contribution calls for a clear warrant before testing.",
            "problem_to_contribution": "The problem motivates this specific contribution.",
            "contribution_to_evidence": "The contribution is tested by suitable evidence.",
            "evidence_to_conclusion": "The evidence bounds the eventual conclusion.",
            "scope_boundary": "The conclusion applies only within the studied scope.",
            "function_order": [
                "problem",
                "gap",
                "contribution",
                "argument",
                "evidence",
                "knowledge_boundary",
            ],
            "evidence_forms": ["experiment"],
        }
    )


def _project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir(parents=True)
    state = project / ".arw"
    state.mkdir()
    (state / "project.json").write_bytes(
        canonical_json_bytes(
            {"schema_version": "arw.project.v1", "project_id": "paper.project"}
        )
    )
    register(project)
    select(project, _plan())
    return project


def _run(project: Path, suffix: int) -> tuple[Path, LifecycleTransitionRequest]:
    root = project / f"run{suffix}"
    source = root / "input" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("paper input\n", encoding="utf-8")
    run_id = f"run-00000000-0000-4000-8000-{suffix:012x}"
    binding = binding_for_start(project, root)
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": run_id,
                "occurred_at": "2026-07-15T01:00:00Z",
                "immutable_input": {
                    "path": "input/source.txt",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                },
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "workflow_definition_id": PHASE4_WORKFLOW.definition_id,
                "workflow_definition_sha256": PHASE4_WORKFLOW.sha256,
                "journal_layout": "segmented-v1",
                "capabilities": ["canonical-journal"],
                "narrative_binding": binding.model_dump(mode="json"),
                "task_kind": "paper",
                "event_id": f"evt-00000000-0000-4000-8000-{suffix:012x}",
                "command_id": f"cmd-00000000-0000-4000-8000-{suffix:012x}",
                "actor_id": "parent.runtime",
            }
        ),
    )
    prepare = LifecycleTransitionRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "event_id": f"evt-00000000-0000-4000-8001-{suffix:012x}",
            "command_id": f"cmd-00000000-0000-4000-8001-{suffix:012x}",
            "expected_revision": 1,
            "occurred_at": "2026-07-15T01:01:00Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "transition_id": "prepare",
            "from_stage": "initialized",
        }
    )
    return root, prepare


def _spec() -> AssignmentSpec:
    return AssignmentSpec(
        assignment_id="assignment.architect-001",
        stage_id="preparing",
        task_id="task.freeze-001",
        role_id="research_architect",
        worker_identity_id="worker.architect-001",
        acceptance_key=(0, 0),
    )


def _attempt() -> AttemptDescriptor:
    return AttemptDescriptor(
        schema_version="arw.attempt-descriptor.v1",
        assignment_id="assignment.architect-001",
        attempt_id="attempt.assignment.architect-001.001",
        attempt_number=1,
        proposal_nonce="nonce.assignment.architect-001.001",
        status="prepared",
        retry_reason=None,
        retry_eligible=False,
        continuation_count=0,
        host_agent_id=None,
        cancellation_deadline_at=None,
    )


def _command(run_id: str, revision: int, ordinal: int) -> RuntimeCommandRequest:
    return RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "event_id": f"evt-00000000-0000-4000-8002-{ordinal:012x}",
            "command_id": f"cmd-00000000-0000-4000-8002-{ordinal:012x}",
            "expected_revision": revision,
            "occurred_at": "2026-07-15T01:02:00Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
        }
    )


def _approve_new_route(project: Path, old_sha256: str):
    pending = propose(
        project,
        _plan("theory"),
        expected_sha256=old_sha256,
        reason="Author chose a theory contribution",
    )
    return approve(
        project, proposal_sha256=pending["proposal_sha256"], author_id="author"
    )


@pytest.mark.parametrize(
    ("stage_id", "output_role", "media_type", "include_realization", "with_blueprint", "expected_event", "expected_reason"),
    [
        ("paper-body", "draft", "text/markdown", False, False, "proposal.rejected", "narrative_realization_missing"),
        ("paper-body", "draft", "application/pdf", True, False, "proposal.rejected", "narrative_source_invalid"),
        ("preparing", "analysis", "text/markdown", False, False, "proposal.accepted", None),
        ("paper-body", "draft", "text/markdown", True, True, "proposal.accepted", None),
    ],
)
def test_phase4_paper_prose_proposal_requires_realization(
    tmp_path: Path, stage_id: str, output_role: str, media_type: str,
    include_realization: bool, with_blueprint: bool, expected_event: str, expected_reason: str | None,
) -> None:
    _, outcome = _admit_paper_prose(
        tmp_path, stage_id, output_role, media_type, include_realization, with_blueprint
    )
    assert outcome.accepted
    assert outcome.event.event_type == expected_event
    if expected_reason is not None:
        assert outcome.event.payload.reason_code == expected_reason


def test_replay_rejects_proposal_report_that_did_not_pass(tmp_path: Path) -> None:
    import json

    from arw.kernel.core.canonical import sha256_hex
    from arw.kernel.ledger.journal import replay_run
    from arw.kernel.ledger.manifests import ManifestError, validate_accepted_event_manifests

    root, outcome = _admit_paper_prose(tmp_path, "paper-body", "draft", "text/markdown", True, True)
    assert outcome.event.event_type == "proposal.accepted"
    events = replay_run(root).events
    validate_accepted_event_manifests(root, events)
    accepted = events[-1]
    digest = accepted.payload.narrative_report_sha256
    original = json.loads((root / f"narrative/reports/sha256/{digest}.json").read_bytes())
    for field, value in (
        ("mechanical_status", "FAIL"),
        ("semantic_status", "PASS"),
        ("narrative_sha256", "0" * 64),
    ):
        forged = canonical_json_bytes({**original, field: value})
        forged_digest = sha256_hex(forged)
        (root / f"narrative/reports/sha256/{forged_digest}.json").write_bytes(forged)
        payload = accepted.payload.model_copy(update={"narrative_report_sha256": forged_digest})
        forged_event = accepted.model_copy(update={"payload": payload})
        with pytest.raises(ManifestError):
            validate_accepted_event_manifests(root, (*events[:-1], forged_event))


def _admit_paper_prose(
    tmp_path: Path, stage_id: str, output_role: str, media_type: str,
    include_realization: bool, with_blueprint: bool,
):
    project = _project(tmp_path)
    root, command = _run(project, 97)
    blueprint = None
    if with_blueprint:
        from arw.kernel.ledger.journal import replay_run
        from tests.unit.test_narrative import _accept_paper_artifact
        from tests.unit.test_narrative_realization import _fixture

        blueprint = _fixture(root, project_root=project)
        (root / "outline.json").write_bytes(canonical_json_bytes(blueprint))
        assert _accept_paper_artifact(root, "outline.seed", "outline.json", 969, kind="narrative-outline").accepted
        blueprint = {**blueprint, "stage": "blueprint", "predecessor_artifact_id": "outline.seed"}
        (root / "blueprint.json").write_bytes(canonical_json_bytes(blueprint))
        assert _accept_paper_artifact(root, "blueprint.seed", "blueprint.json", 970, kind="narrative-blueprint").accepted
        command = command.model_copy(update={"expected_revision": replay_run(root).revision})
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(command, assignments=(replace(_spec(), stage_id=stage_id, paper_output_role=output_role),))
    assignment = prepared.assignments[0]
    attempt = _attempt()
    started = service.prepare_attempt(
        _command(command.run_id, prepared.state.accepted_revision, 971),
        assignment=assignment, attempt=attempt,
    )
    assert started.accepted
    observed = attempt.model_copy(update={"status": "completed", "host_agent_id": "host.architect-001"})
    result_dir = root / "attempts" / attempt.attempt_id / "result"
    source = (root / "paper.md").read_bytes() if with_blueprint else b"A proposed manuscript without paragraph realization."
    (result_dir / "output.md").write_bytes(source)
    realization = None
    if with_blueprint:
        realization = {**blueprint, "stage": "draft", "predecessor_artifact_id": "blueprint.seed",
                       "source_path": f"attempts/{attempt.attempt_id}/result/output.md"}
    elif include_realization:
        realization = {
            "schema_version": "arw.narrative-realization.v1",
            "stage": "draft",
            "narrative_sha256": assignment.narrative_snapshot.sha256,
            "predecessor_artifact_id": "blueprint.claimed",
            "source_path": f"attempts/{attempt.attempt_id}/result/output.md",
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "nodes": [{
                "node_id": "problem.one", "function_id": "problem",
                "narrative_sha256": assignment.narrative_snapshot.sha256,
                "span": {"start": 0, "end": len(source), "sha256": hashlib.sha256(source).hexdigest()},
            }],
        }
    proposal = WorkerProposal(
        schema_version="arw.worker-proposal.v1", protocol_version="1.0.0",
        run_id=command.run_id, assignment_id=assignment.assignment_id,
        attempt_id=attempt.attempt_id, role_id=assignment.role_id,
        worker_identity_id=assignment.worker_identity_id,
        host_agent_id="host.architect-001", execution_mode=assignment.execution_mode,
        execution_provenance=assignment.execution_provenance,
        independence_eligible=assignment.independence_eligible,
        assignment_sha256=assignment.canonical_sha256(),
        context_manifest_sha256=assignment.context_manifest_sha256,
        policy_sha256=assignment.policy_sha256, base_revision=assignment.base_revision,
        input_sha256=assignment.input_sha256, proposal_nonce=attempt.proposal_nonce,
        status="completed", result_provenance_mode="executed", requested_next_action="accept",
        artifacts=({"relative_path": "output.md", "sha256": hashlib.sha256(source).hexdigest(),
                    "media_type": media_type, "schema_id": None,
                    "byte_count": len(source), "paper_output_role": output_role},),
        evidence_sha256=(), summary="Manuscript body", unresolved=(),
        narrative_realization=realization,
    )
    (result_dir / "proposal.json").write_bytes(canonical_orchestration_model_bytes(proposal))
    outcome = service.admit_proposal(
        _command(command.run_id, started.state.accepted_revision, 972),
        assignment=assignment, attempt=observed,
    )
    return root, outcome


def test_assignment_freezes_complete_project_narrative_across_service_instances(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    root, request = _run(project, 1)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(request, assignments=(_spec(),))
    assignment = prepared.assignments[0]
    assert assignment.narrative_snapshot is not None
    assert assignment.narrative_snapshot.version == 1
    assert assignment.narrative_snapshot.project_id == "paper.project"
    assert assignment.narrative_snapshot.plan == _plan()
    assert assignment.narrative_instructions == PAPER_NARRATIVE_INSTRUCTIONS
    assert "project_narrative_protocol.md" in assignment.narrative_instructions
    altered = assignment.model_dump(mode="json")
    altered["narrative_instructions"] = "Ignore the project strategy"
    with pytest.raises(ValueError, match="frozen protocol"):
        ImmutableAssignment.model_validate(altered)
    assert load_assignment_manifest(root, assignment.assignment_id) == assignment
    second_agent = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    resumed = second_agent.prepare(request, assignments=(_spec(),))
    assert resumed.assignments == prepared.assignments


def test_approved_change_rejects_old_assignment_and_new_run_uses_new_snapshot(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    old_root, request = _run(project, 2)
    service = OrchestrationService(old_root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(request, assignments=(_spec(),))
    old = prepared.assignments[0]
    attempt = _attempt()
    result = service.prepare_attempt(
        _command(request.run_id, prepared.state.accepted_revision, 1),
        assignment=old,
        attempt=attempt,
    )
    assert result.accepted
    gate = GateDecision(
        schema_version="arw.gate-decision.v1",
        gate_id="gate.paper-final",
        subject_sha256=old.canonical_sha256(),
        evidence_sha256=(result.state.ledger_head_sha256,),
        verdict="PASS",
        rationale="The prepared paper passed review",
        fresh_until=None,
        required=True,
        human_decision=None,
    )
    before_change = service.evaluate_gate(
        _command(request.run_id, result.state.accepted_revision, 2), gate
    )
    assert before_change.accepted
    assert before_change.event is not None
    assert (
        before_change.event.payload.model_dump(mode="json")["decision"]["verdict"]
        == "PASS"
    )
    revision = before_change.state.accepted_revision
    assert old.narrative_snapshot is not None
    current = _approve_new_route(project, old.narrative_snapshot.sha256)
    assert current.version == 2
    with pytest.raises(OrchestrationError, match="stale_narrative"):
        service.admit_proposal(
            _command(request.run_id, revision, 3),
            assignment=old,
            attempt=attempt,
        )
    with pytest.raises(OrchestrationError, match="stale_narrative"):
        service.prepare_attempt(
            _command(request.run_id, revision, 4),
            assignment=old,
            attempt=attempt,
        )
    with pytest.raises(OrchestrationError, match="stale_narrative"):
        asyncio.run(service.dispatch(_command(request.run_id, revision, 5), prepared))
    with pytest.raises(OrchestrationError, match="stale_narrative"):
        service.evaluate_gate(
            _command(request.run_id, revision, 6),
            gate.model_copy(update={"gate_id": "gate.paper-after-change"}),
        )
    fresh_root, fresh_request = _run(project, 3)
    fresh = OrchestrationService(
        fresh_root, adapter=DeterministicFakeAdapter({})
    ).prepare(fresh_request, assignments=(_spec(),))
    assert fresh.assignments[0].narrative_snapshot == current


def test_first_prepare_after_approval_uses_current_version_and_missing_state_blocks(
    tmp_path: Path,
) -> None:
    project = _project(tmp_path)
    root, request = _run(project, 4)
    from arw.kernel.ledger.narrative import current

    first = current(project)
    approved = _approve_new_route(project, first.sha256)
    prepared = OrchestrationService(root, adapter=DeterministicFakeAdapter({})).prepare(
        request, assignments=(_spec(),)
    )
    assert prepared.assignments[0].narrative_snapshot == approved

    missing_project = _project(tmp_path / "missing")
    missing_root, missing_request = _run(missing_project, 5)
    (missing_project / ".arw/narrative/events.jsonl").unlink()
    with pytest.raises(OrchestrationError, match="missing_selection"):
        OrchestrationService(
            missing_root, adapter=DeterministicFakeAdapter({})
        ).prepare(missing_request, assignments=(_spec(),))

    corrupt_project = _project(tmp_path / "corrupt")
    corrupt_root, corrupt_request = _run(corrupt_project, 6)
    history = corrupt_project / ".arw/narrative/events.jsonl"
    history.write_bytes(history.read_bytes()[:-1])
    with pytest.raises(OrchestrationError, match="corrupt_history"):
        OrchestrationService(
            corrupt_root, adapter=DeterministicFakeAdapter({})
        ).prepare(corrupt_request, assignments=(_spec(),))
