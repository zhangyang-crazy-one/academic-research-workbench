"""Parent-only Phase 4 lifecycle integration tests."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

from arw.kernel.core.canonical import sha256_hex
from arw.execution import (
    DispatchSpec,
    DeterministicFakeAdapter,
    ExecutionPolicySnapshot,
    HostResult,
    ProcessFailure,
)
from arw.journal import initialize_run, replay_run
from arw.manifests import load_assignment_manifest
from arw.models import InitRunRequest, LifecycleTransitionRequest, RuntimeCommandRequest
from arw.orchestration import AssignmentSpec, OrchestrationService
from arw.orchestration_models import AttemptDescriptor, WorkerProposal, canonical_orchestration_model_bytes
from arw.workflows import PHASE4_WORKFLOW


RUN_ID = "run-00000000-0000-4000-8000-000000000404"


class _ProposalWritingAdapter:
    async def dispatch(self, spec: DispatchSpec) -> HostResult:
        assignment = load_assignment_manifest(spec.assignment_path.parent.parent, spec.assignment_id)
        host_id = f"host.{assignment.worker_identity_id.removeprefix('worker.')}"
        proposal = WorkerProposal(
            schema_version="arw.worker-proposal.v1",
            protocol_version="1.0.0",
            run_id=assignment.run_id,
            assignment_id=assignment.assignment_id,
            attempt_id=spec.attempt_id,
            role_id=assignment.role_id,
            worker_identity_id=assignment.worker_identity_id,
            host_agent_id=host_id,
            execution_mode=assignment.execution_mode,
            execution_provenance=assignment.execution_provenance,
            independence_eligible=assignment.independence_eligible,
            assignment_sha256=assignment.canonical_sha256(),
            context_manifest_sha256=assignment.context_manifest_sha256,
            policy_sha256=assignment.policy_sha256,
            base_revision=assignment.base_revision,
            input_sha256=assignment.input_sha256,
            proposal_nonce=(
                f"nonce.{assignment.assignment_id}.001.retry-2"
                if ".retry-" in spec.attempt_id
                else f"nonce.{assignment.assignment_id}.001"
            ),
            status="completed",
            result_provenance_mode="executed",
            requested_next_action="accept",
            artifacts=(
                {
                    "relative_path": "report.json",
                    "sha256": "e" * 64,
                    "media_type": "application/json",
                    "schema_id": "arw.review-report.v1",
                    "byte_count": 1,
                },
            ),
            evidence_sha256=("f" * 64,),
            summary="adapter proposal",
            unresolved=(),
        )
        proposal_path = spec.attempt_root / "result" / "proposal.json"
        proposal_path.parent.mkdir(parents=True, exist_ok=True)
        proposal_path.write_bytes(canonical_orchestration_model_bytes(proposal))
        return HostResult(
            attempt_id=spec.attempt_id,
            host_agent_id=host_id,
            proposal_path=proposal_path,
        )

    async def request_cancel(self, spec: DispatchSpec) -> None:
        return None

    async def force_terminate(self, spec: DispatchSpec) -> None:
        return None


class _RetryingProposalAdapter(_ProposalWritingAdapter):
    def __init__(self) -> None:
        self.first = True

    async def dispatch(self, spec: DispatchSpec) -> HostResult:
        if self.first:
            self.first = False
            raise ProcessFailure("one repairable process failure")
        return await super().dispatch(spec)


class _MalformedThenValidAdapter(_ProposalWritingAdapter):
    def __init__(self, *, always_malformed: bool = False) -> None:
        self.always_malformed = always_malformed
        self.dispatch_specs: list[DispatchSpec] = []

    async def dispatch(self, spec: DispatchSpec) -> HostResult:
        self.dispatch_specs.append(spec)
        assert any(
            event.event_type == "attempt.prepared"
            and event.payload.attempt.attempt_id == spec.attempt_id
            for event in replay_run(spec.assignment_path.parent.parent).events
        )
        if self.always_malformed or spec.attempt_number == 1:
            proposal_path = spec.attempt_root / "result" / "proposal.json"
            proposal_path.parent.mkdir(parents=True, exist_ok=True)
            proposal_path.write_bytes(b"{}\n")
            return HostResult(
                attempt_id=spec.attempt_id,
                host_agent_id=f"host.{spec.assignment_id}",
                proposal_path=proposal_path,
            )
        return await super().dispatch(spec)


class _TimeoutThenValidAdapter(_ProposalWritingAdapter):
    def __init__(self) -> None:
        self.first_release = asyncio.Event()
        self.dispatch_specs: list[DispatchSpec] = []
        self.lifecycle: list[tuple[str, str]] = []

    async def dispatch(self, spec: DispatchSpec) -> HostResult:
        self.dispatch_specs.append(spec)
        self.lifecycle.append(("dispatch", spec.attempt_id))
        assert any(
            event.event_type == "attempt.prepared"
            and event.payload.attempt.attempt_id == spec.attempt_id
            for event in replay_run(spec.assignment_path.parent.parent).events
        )
        if spec.attempt_number == 1:
            await self.first_release.wait()
            return HostResult(
                attempt_id=spec.attempt_id,
                host_agent_id=f"host.{spec.assignment_id}",
                proposal_path=spec.attempt_root / "result" / "proposal.json",
            )
        return await super().dispatch(spec)

    async def request_cancel(self, spec: DispatchSpec) -> None:
        self.lifecycle.append(("request_cancel", spec.attempt_id))
        assert any(
            event.event_type == "attempt.lifecycle"
            and event.payload.attempt_id == spec.attempt_id
            and event.payload.status == "cancel_requested"
            for event in replay_run(spec.assignment_path.parent.parent).events
        )
        self.first_release.set()

    async def force_terminate(self, spec: DispatchSpec) -> None:
        self.lifecycle.append(("force_terminate", spec.attempt_id))


def _run(tmp_path: Path) -> tuple[Path, LifecycleTransitionRequest]:
    root = tmp_path / "run"
    source = root / "input" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("phase four input\n", encoding="utf-8")
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
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
                "event_id": "evt-00000000-0000-4000-8000-000000000404",
                "command_id": "cmd-00000000-0000-4000-8000-000000000404",
                "actor_id": "parent.runtime",
            }
        ),
    )
    request = LifecycleTransitionRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "event_id": "evt-00000000-0000-4000-8000-000000000405",
            "command_id": "cmd-00000000-0000-4000-8000-000000000405",
            "expected_revision": 1,
            "occurred_at": "2026-07-15T01:01:00Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "transition_id": "prepare",
            "from_stage": "initialized",
        }
    )
    return root, request


def test_p04_04_t01_parent_freezes_assignment_before_dispatch(tmp_path: Path) -> None:
    root, request = _run(tmp_path)
    adapter = DeterministicFakeAdapter({})
    prepared = OrchestrationService(root, adapter=adapter).prepare(
        request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.architect-001",
                stage_id="preparing",
                task_id="task.freeze-001",
                role_id="research_architect",
                worker_identity_id="worker.architect-001",
                acceptance_key=(0, 0),
            ),
        ),
    )

    assert prepared.state.stage == "prepared"
    assert prepared.state.execution_mode == "assignment_injected_subagent"
    assert prepared.state.role_catalog_sha256 == prepared.role_catalog_sha256
    assert len(prepared.state.assignments) == 1
    assignment = prepared.assignments[0]
    assert assignment.canonical_sha256() == prepared.state.assignments[0].assignment_sha256
    assert (root / "assignments" / f"{assignment.assignment_id}.json").is_file()
    assert adapter.dispatches_for(assignment.assignment_id) == ()

    replayed = replay_run(root)
    assert all(event.actor_role == "parent_control_plane" for event in replayed.events[1:])


def test_p04_04_t02_worker_cannot_append_and_parent_admits_exact_proposal(
    tmp_path: Path,
) -> None:
    root, request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(
        request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.architect-002",
                stage_id="preparing",
                task_id="task.proposal-001",
                role_id="research_architect",
                worker_identity_id="worker.architect-002",
                acceptance_key=(0, 0),
            ),
        ),
    )
    assignment = prepared.assignments[0]
    attempt = AttemptDescriptor(
        schema_version="arw.attempt-descriptor.v1",
        assignment_id=assignment.assignment_id,
        attempt_id="attempt.assignment.architect-002.001",
        attempt_number=1,
        proposal_nonce="nonce.assignment.architect-002.001",
        status="prepared",
        retry_reason=None,
        retry_eligible=False,
        continuation_count=0,
        host_agent_id=None,
        cancellation_deadline_at=None,
    )
    prepared_attempt = service.prepare_attempt(
        RuntimeCommandRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "event_id": "evt-00000000-0000-4000-8000-000000000406",
                "command_id": "cmd-00000000-0000-4000-8000-000000000406",
                "expected_revision": prepared.state.accepted_revision,
                "occurred_at": "2026-07-15T01:02:00Z",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
            }
        ),
        assignment=assignment,
        attempt=attempt,
    )
    assert prepared_attempt.accepted
    observed_attempt = attempt.model_copy(
        update={"status": "completed", "host_agent_id": "host.architect-002"}
    )
    proposal = WorkerProposal(
        schema_version="arw.worker-proposal.v1",
        protocol_version="1.0.0",
        run_id=RUN_ID,
        assignment_id=assignment.assignment_id,
        attempt_id=observed_attempt.attempt_id,
        role_id=assignment.role_id,
        worker_identity_id=assignment.worker_identity_id,
        host_agent_id=observed_attempt.host_agent_id,
        execution_mode=assignment.execution_mode,
        execution_provenance=assignment.execution_provenance,
        independence_eligible=assignment.independence_eligible,
        assignment_sha256=assignment.canonical_sha256(),
        context_manifest_sha256=assignment.context_manifest_sha256,
        policy_sha256=assignment.policy_sha256,
        base_revision=assignment.base_revision,
        input_sha256=assignment.input_sha256,
        proposal_nonce=observed_attempt.proposal_nonce,
        status="completed",
        result_provenance_mode="executed",
        requested_next_action="accept",
        artifacts=(
            {
                "relative_path": "report.json",
                "sha256": "c" * 64,
                "media_type": "application/json",
                "schema_id": "arw.review-report.v1",
                "byte_count": 1,
            },
        ),
        evidence_sha256=("d" * 64,),
        summary="bounded proposal",
        unresolved=(),
    )
    proposal_path = root / "attempts" / observed_attempt.attempt_id / "result" / "proposal.json"
    proposal_path.write_bytes(canonical_orchestration_model_bytes(proposal))
    admitted = service.admit_proposal(
        RuntimeCommandRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "event_id": "evt-00000000-0000-4000-8000-000000000407",
                "command_id": "cmd-00000000-0000-4000-8000-000000000407",
                "expected_revision": prepared_attempt.state.accepted_revision,
                "occurred_at": "2026-07-15T01:03:00Z",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
            }
        ),
        assignment=assignment,
        attempt=observed_attempt,
    )
    assert admitted.accepted
    assert admitted.event is not None and admitted.event.event_type == "proposal.accepted"
    assert admitted.state.accepted_proposals[0].proposal_sha256 == sha256_hex(
        proposal_path.read_bytes()
    )

    worker_request = RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "event_id": "evt-00000000-0000-4000-8000-000000000408",
            "command_id": "cmd-00000000-0000-4000-8000-000000000408",
            "expected_revision": admitted.state.accepted_revision,
            "occurred_at": "2026-07-15T01:04:00Z",
            "actor_id": "worker.architect-002",
            "actor_role": "worker",
        }
    )
    rejected_worker = service.runtime.append_phase4_event(
        worker_request,
        event_type="proposal.accepted",
        payload=admitted.event.payload,
    )
    assert not rejected_worker.accepted
    assert rejected_worker.rejection is not None
    assert rejected_worker.rejection.code == "unauthorized-actor"
    assert rejected_worker.state.accepted_revision == admitted.state.accepted_revision


def test_p04_04_t02_dispatch_uses_parent_admission_and_frozen_order(tmp_path: Path) -> None:
    root, request = _run(tmp_path)
    adapter = _ProposalWritingAdapter()
    service = OrchestrationService(root, adapter=adapter)
    prepared = service.prepare(
        request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.dispatch-001",
                stage_id="preparing",
                task_id="task.dispatch-001",
                role_id="research_architect",
                worker_identity_id="worker.dispatch-001",
                acceptance_key=(0, 1),
            ),
        ),
    )

    report = asyncio.run(
        service.dispatch(
            RuntimeCommandRequest.model_validate(
                {
                    "schema_version": "1.0.0",
                    "run_id": RUN_ID,
                    "event_id": "evt-00000000-0000-4000-8000-000000000409",
                    "command_id": "cmd-00000000-0000-4000-8000-000000000409",
                    "expected_revision": prepared.state.accepted_revision,
                    "occurred_at": "2026-07-15T01:05:00Z",
                    "actor_id": "parent.runtime",
                    "actor_role": "parent_control_plane",
                }
            ),
            prepared,
        )
    )
    assert report.outcomes[0].assignment_id == "assignment.dispatch-001"
    assert report.state.accepted_proposals[0].assignment_id == "assignment.dispatch-001"
    assert report.state.active_attempts == []
    assert all(event.actor_role == "parent_control_plane" for event in replay_run(root).events[1:])


def test_p04_04_t02_retry_materializes_before_adapter_and_does_not_reject_first_attempt(
    tmp_path: Path,
) -> None:
    root, request = _run(tmp_path)
    service = OrchestrationService(root, adapter=_RetryingProposalAdapter())
    prepared = service.prepare(
        request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.retry-001",
                stage_id="preparing",
                task_id="task.retry-001",
                role_id="research_architect",
                worker_identity_id="worker.retry-001",
                acceptance_key=(0, 0),
            ),
        ),
    )
    report = asyncio.run(
        service.dispatch(
            RuntimeCommandRequest.model_validate(
                {
                    "schema_version": "1.0.0",
                    "run_id": RUN_ID,
                    "event_id": "evt-00000000-0000-4000-8000-000000000413",
                    "command_id": "cmd-00000000-0000-4000-8000-000000000413",
                    "expected_revision": prepared.state.accepted_revision,
                    "occurred_at": "2026-07-15T01:06:00Z",
                    "actor_id": "parent.runtime",
                    "actor_role": "parent_control_plane",
                }
            ),
            prepared,
        )
    )
    assert report.state.accepted_proposals[0].assignment_id == "assignment.retry-001"
    assert report.state.rejected_proposals == ()
    retry_root = root / "attempts" / "attempt.assignment.retry-001.001.retry-2"
    assert (retry_root / "assignment.json").is_file()
    assert (retry_root / "attempt.json").is_file()
    assert [item.status for item in report.state.attempts[-6:]] == [
        "prepared",
        "active",
        "failed",
        "prepared",
        "active",
        "completed",
    ]


def test_p04_04_t02_repairable_envelope_retries_only_after_canonical_prepare(
    tmp_path: Path,
) -> None:
    root, request = _run(tmp_path)
    adapter = _MalformedThenValidAdapter()
    service = OrchestrationService(root, adapter=adapter)
    prepared = service.prepare(
        request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.envelope-001",
                stage_id="preparing",
                task_id="task.envelope-001",
                role_id="research_architect",
                worker_identity_id="worker.envelope-001",
                acceptance_key=(0, 0),
            ),
        ),
    )

    report = asyncio.run(
        service.dispatch(
            RuntimeCommandRequest.model_validate(
                {
                    "schema_version": "1.0.0",
                    "run_id": RUN_ID,
                    "event_id": "evt-00000000-0000-4000-8000-000000000414",
                    "command_id": "cmd-00000000-0000-4000-8000-000000000414",
                    "expected_revision": prepared.state.accepted_revision,
                    "occurred_at": "2026-07-15T01:07:00Z",
                    "actor_id": "parent.runtime",
                    "actor_role": "parent_control_plane",
                }
            ),
            prepared,
        )
    )

    assert [spec.attempt_number for spec in adapter.dispatch_specs] == [1, 2]
    assert report.state.rejected_proposals == ()
    assert len(report.state.accepted_proposals) == 1
    relevant = [
        event
        for event in replay_run(root).events
        if event.event_type
        in {"attempt.prepared", "attempt.lifecycle", "proposal.accepted", "proposal.rejected"}
    ]
    assert [event.event_type for event in relevant] == [
        "attempt.prepared",
        "attempt.lifecycle",
        "attempt.lifecycle",
        "attempt.prepared",
        "attempt.lifecycle",
        "proposal.accepted",
    ]
    assert relevant[2].payload.retry_reason == "repairable_envelope"
    assert relevant[2].payload.retry_eligible is True


def test_p04_04_t02_two_malformed_envelopes_block_without_third_attempt(
    tmp_path: Path,
) -> None:
    root, request = _run(tmp_path)
    adapter = _MalformedThenValidAdapter(always_malformed=True)
    service = OrchestrationService(root, adapter=adapter)
    prepared = service.prepare(
        request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.envelope-002",
                stage_id="preparing",
                task_id="task.envelope-002",
                role_id="research_architect",
                worker_identity_id="worker.envelope-002",
                acceptance_key=(0, 0),
            ),
        ),
    )

    report = asyncio.run(
        service.dispatch(
            RuntimeCommandRequest.model_validate(
                {
                    "schema_version": "1.0.0",
                    "run_id": RUN_ID,
                    "event_id": "evt-00000000-0000-4000-8000-000000000415",
                    "command_id": "cmd-00000000-0000-4000-8000-000000000415",
                    "expected_revision": prepared.state.accepted_revision,
                    "occurred_at": "2026-07-15T01:08:00Z",
                    "actor_id": "parent.runtime",
                    "actor_role": "parent_control_plane",
                }
            ),
            prepared,
        )
    )

    assert [spec.attempt_number for spec in adapter.dispatch_specs] == [1, 2]
    assert len(report.outcomes[0].attempts) == 2
    assert report.outcomes[0].retry_eligible is False
    assert len(report.state.rejected_proposals) == 1
    assert any(
        blocker.code.startswith("attempt-blocked.") for blocker in report.state.blockers
    )


def test_p04_04_t02_timeout_request_is_canonical_before_cancel_and_retries_once(
    tmp_path: Path,
) -> None:
    root, request = _run(tmp_path)
    adapter = _TimeoutThenValidAdapter()
    policy = ExecutionPolicySnapshot(
        max_concurrency=1,
        attempt_timeout_s=0.02,
        cancel_grace_s=0.05,
        max_attempts_per_assignment=2,
    )
    service = OrchestrationService(root, adapter=adapter, policy=policy)
    prepared = service.prepare(
        request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.timeout-001",
                stage_id="preparing",
                task_id="task.timeout-001",
                role_id="research_architect",
                worker_identity_id="worker.timeout-001",
                acceptance_key=(0, 0),
            ),
        ),
    )

    report = asyncio.run(
        service.dispatch(
            RuntimeCommandRequest.model_validate(
                {
                    "schema_version": "1.0.0",
                    "run_id": RUN_ID,
                    "event_id": "evt-00000000-0000-4000-8000-000000000416",
                    "command_id": "cmd-00000000-0000-4000-8000-000000000416",
                    "expected_revision": prepared.state.accepted_revision,
                    "occurred_at": "2026-07-15T01:09:00Z",
                    "actor_id": "parent.runtime",
                    "actor_role": "parent_control_plane",
                }
            ),
            prepared,
        )
    )

    assert [spec.attempt_number for spec in adapter.dispatch_specs] == [1, 2]
    assert adapter.lifecycle[:3] == [
        ("dispatch", adapter.dispatch_specs[0].attempt_id),
        ("request_cancel", adapter.dispatch_specs[0].attempt_id),
        ("dispatch", adapter.dispatch_specs[1].attempt_id),
    ]
    assert len(report.state.accepted_proposals) == 1
    first_history = [
        item
        for item in report.state.attempts
        if item.attempt_id == adapter.dispatch_specs[0].attempt_id
    ]
    assert [item.status for item in first_history] == [
        "prepared",
        "active",
        "cancel_requested",
        "cancelled",
    ]
    assert first_history[-1].retry_reason == "timeout"
    assert first_history[-1].retry_eligible is True
