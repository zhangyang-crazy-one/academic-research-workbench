from __future__ import annotations

from datetime import UTC, datetime

import pytest


RUN_ID = "run-00000000-0000-4000-8000-000000000001"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64


def _phase4_assignment(*, assignment_id: str, task_ordinal: int):
    from arw.orchestration_models import ImmutableAssignment

    return ImmutableAssignment.model_validate(
        {
            "schema_version": "arw.assignment.v1",
            "protocol_version": "1.0.0",
            "assignment_id": assignment_id,
            "supersedes_assignment_id": None,
            "run_id": RUN_ID,
            "stage_id": "proposal-stage",
            "task_id": f"task-{task_ordinal:03d}",
            "role_id": "research_architect",
            "worker_identity_id": f"worker.architect-{task_ordinal:03d}",
            "execution_mode": "native_formal",
            "execution_provenance": "assignment_injected_subagent",
            "independence_eligible": False,
            "base_revision": 1,
            "input_sha256": [HASH_A],
            "capability_ids": ["files.read"],
            "allowed_read_root_ids": ["research-root"],
            "scratch_path_template": "attempts/{attempt_id}/scratch",
            "result_path_template": "attempts/{attempt_id}/result",
            "output_policy": {
                "schema_id": "arw.worker-proposal.v1",
                "schema_sha256": HASH_B,
                "max_bytes": 4096,
                "max_artifacts": 1,
            },
            "policy_sha256": HASH_C,
            "context_manifest_sha256": HASH_D,
            "blind_review": {
                "required": False,
                "subject_sha256": None,
                "rubric_sha256": None,
                "forbidden_peer_role_ids": [],
            },
            "deadline_at": "2026-07-15T12:00:00Z",
            "completion_contract": {
                "requires_completed_proposal": True,
                "required_artifact_kinds": ["proposal"],
                "requires_human_gate": False,
            },
            "acceptance_key": {
                "topological_layer": 0,
                "task_ordinal": task_ordinal,
                "assignment_id": assignment_id,
            },
        }
    )


def _phase4_attempt(assignment, *, attempt_id: str, attempt_number: int = 1, status: str = "active"):
    from arw.orchestration_models import AttemptDescriptor

    return AttemptDescriptor.model_validate(
        {
            "schema_version": "arw.attempt-descriptor.v1",
            "assignment_id": assignment.assignment_id,
            "attempt_id": attempt_id,
            "attempt_number": attempt_number,
            "proposal_nonce": f"nonce-{attempt_id}",
            "status": status,
            "retry_reason": None,
            "retry_eligible": False,
            "continuation_count": 0,
            "host_agent_id": "host-agent-001",
            "cancellation_deadline_at": None,
        }
    )


def _phase4_proposal(assignment, attempt):
    from arw.orchestration_models import ProposedArtifact, WorkerProposal

    return WorkerProposal.model_validate(
        {
            "schema_version": "arw.worker-proposal.v1",
            "protocol_version": "1.0.0",
            "run_id": RUN_ID,
            "assignment_id": assignment.assignment_id,
            "attempt_id": attempt.attempt_id,
            "role_id": assignment.role_id,
            "worker_identity_id": assignment.worker_identity_id,
            "host_agent_id": attempt.host_agent_id,
            "execution_mode": assignment.execution_mode,
            "execution_provenance": assignment.execution_provenance,
            "independence_eligible": assignment.independence_eligible,
            "assignment_sha256": assignment.canonical_sha256(),
            "context_manifest_sha256": assignment.context_manifest_sha256,
            "policy_sha256": assignment.policy_sha256,
            "base_revision": assignment.base_revision,
            "input_sha256": assignment.input_sha256,
            "proposal_nonce": attempt.proposal_nonce,
            "status": "completed",
            "result_provenance_mode": "executed",
            "requested_next_action": "accept",
            "artifacts": [
                {
                    "relative_path": "proposal.json",
                    "sha256": HASH_E,
                    "media_type": "application/json",
                    "schema_id": "arw.worker-proposal.v1",
                    "byte_count": 128,
                }
            ],
            "evidence_sha256": [HASH_E],
            "summary": "A deterministic Phase 4 proposal.",
            "unresolved": [],
        }
    )


def _event(event_type: str, payload: object, *, revision: int, role: str = "parent_control_plane"):
    from arw.models import CanonicalEvent

    return CanonicalEvent.model_validate(
        {
            "schema_version": "1.0.0",
            "event_type": event_type,
            "event_id": f"evt-00000000-0000-4000-8000-{revision:012x}",
            "command_id": f"cmd-00000000-0000-4000-8000-{revision:012x}",
            "run_id": "run-00000000-0000-4000-8000-000000000001",
            "sequence": revision,
            "occurred_at": f"2026-07-13T00:00:{revision:02d}Z",
            "expected_revision": revision - 1,
            "resulting_revision": revision,
            "actor_id": "parent.runtime" if role == "parent_control_plane" else "worker.agent",
            "actor_role": role,
            "prev_event_sha256": "0" * 64,
            "payload": payload,
            "event_sha256": f"{revision:064x}",
        }
    )


def test_reducer_applies_legal_lifecycle_decisions_attempts_and_passport() -> None:
    from arw.reducer import reduce_events

    events = [
        _event("run.initialized", {"manifest_sha256": "a" * 64}, revision=1),
        _event(
            "lifecycle.transitioned",
            {"transition_id": "start", "from_stage": "initialized", "to_stage": "intake"},
            revision=2,
        ),
        _event(
            "human_decision.requested",
            {
                "decision_id": "decision.review-route",
                "blocker_code": "human-choice-required",
                "starting_revision": 2,
                "allowed_choices": ["continue", "abort"],
                "rationale_required": True,
                "source_event_ids": [],
                "unlock_transitions": ["begin_work"],
            },
            revision=3,
        ),
        _event(
            "attempt.started",
            {
                "attempt_id": "attempt.writer-001",
                "base_revision": 3,
                "consumed_sha256": [f"{3:064x}"],
            },
            revision=4,
        ),
        _event(
            "passport.accepted",
            {
                "passport_sha256": "c" * 64,
                "parent_passport_sha256": None,
                "supersedes_passport_sha256": None,
                "checkpoint_kind": "explicit",
                "based_on_revision": 4,
                "stage": "intake",
                "fresh_until": "2026-07-14T00:00:00Z",
            },
            revision=5,
        ),
    ]
    state = reduce_events(
        "core-research.v1",
        events,
        now=datetime(2026, 7, 13, 12, tzinfo=UTC),
    )
    assert state.stage == "intake"
    assert state.accepted_revision == 5
    assert state.current_passport_sha256 == "c" * 64
    assert [item.decision_id for item in state.pending_human_decisions] == ["decision.review-route"]
    assert [item.attempt_id for item in state.active_attempts] == ["attempt.writer-001"]


def test_reducer_rejects_unauthorized_or_illegal_transition() -> None:
    from arw.reducer import ReducerError, reduce_events

    initialized = _event("run.initialized", {"manifest_sha256": "a" * 64}, revision=1)
    unauthorized = _event(
        "lifecycle.transitioned",
        {"transition_id": "start", "from_stage": "initialized", "to_stage": "intake"},
        revision=2,
        role="worker",
    )
    with pytest.raises(ReducerError, match="authorized"):
        reduce_events("core-research.v1", [initialized, unauthorized])

    illegal = _event(
        "lifecycle.transitioned",
        {"transition_id": "complete", "from_stage": "initialized", "to_stage": "completed"},
        revision=2,
    )
    with pytest.raises(ReducerError, match="legal"):
        reduce_events("core-research.v1", [initialized, illegal])


def test_reducer_requires_explicit_actor_role_for_phase2_initialization() -> None:
    from arw.reducer import ReducerError, reduce_events

    initialized = _event(
        "run.initialized", {"manifest_sha256": "a" * 64}, revision=1
    ).model_copy(update={"actor_role": None})

    with pytest.raises(ReducerError, match="explicit actor role"):
        reduce_events("core-research.v1", [initialized])

    legacy = reduce_events("academic-pipeline.legacy-v1", [initialized])
    assert legacy.accepted_revision == 1


def test_reducer_keeps_shared_blocker_until_every_decision_is_resolved() -> None:
    from arw.reducer import reduce_events

    events = [_event("run.initialized", {"manifest_sha256": "a" * 64}, revision=1)]
    for revision, decision_id in ((2, "decision.first"), (3, "decision.second")):
        events.append(
            _event(
                "human_decision.requested",
                {
                    "decision_id": decision_id,
                    "blocker_code": "human-choice-required",
                    "starting_revision": revision - 1,
                    "allowed_choices": ["continue"],
                    "rationale_required": False,
                    "source_event_ids": [],
                    "unlock_transitions": ["start"],
                },
                revision=revision,
            )
        )
    events.append(
        _event(
            "human_decision.resolved",
            {"decision_id": "decision.first", "choice": "continue", "rationale": None},
            revision=4,
        )
    )

    state = reduce_events("core-research.v1", events)
    assert [item.decision_id for item in state.pending_human_decisions] == [
        "decision.second"
    ]
    assert [item.code for item in state.blockers] == ["human-choice-required"]
    assert state.legal_next_transitions == []


@pytest.mark.parametrize("identity", ["decision", "attempt", "artifact"])
def test_reducer_rejects_reused_stable_runtime_identity(identity: str) -> None:
    from arw.reducer import ReducerError, reduce_events

    events = [_event("run.initialized", {"manifest_sha256": "a" * 64}, revision=1)]
    if identity == "decision":
        events.extend(
            [
                _event(
                    "human_decision.requested",
                    {
                        "decision_id": "decision.once",
                        "blocker_code": "human-choice-required",
                        "starting_revision": 1,
                        "allowed_choices": ["continue"],
                        "rationale_required": False,
                        "source_event_ids": [],
                        "unlock_transitions": ["start"],
                    },
                    revision=2,
                ),
                _event(
                    "human_decision.resolved",
                    {"decision_id": "decision.once", "choice": "continue", "rationale": None},
                    revision=3,
                ),
                _event(
                    "human_decision.requested",
                    {
                        "decision_id": "decision.once",
                        "blocker_code": "human-choice-required",
                        "starting_revision": 3,
                        "allowed_choices": ["continue"],
                        "rationale_required": False,
                        "source_event_ids": [],
                        "unlock_transitions": ["start"],
                    },
                    revision=4,
                ),
            ]
        )
    elif identity == "attempt":
        events.extend(
            [
                _event(
                    "attempt.started",
                    {"attempt_id": "attempt.once", "base_revision": 1, "consumed_sha256": []},
                    revision=2,
                ),
                _event(
                    "attempt.closed",
                    {"attempt_id": "attempt.once", "outcome": "completed", "proposal_sha256": None},
                    revision=3,
                ),
                _event(
                    "attempt.started",
                    {"attempt_id": "attempt.once", "base_revision": 3, "consumed_sha256": []},
                    revision=4,
                ),
            ]
        )
    else:
        events.extend(
            [
                _event(
                    "artifact.accepted",
                    {
                        "artifact_id": "artifact.once",
                        "manifest_sha256": "b" * 64,
                        "artifact_sha256": "c" * 64,
                        "attempt_id": None,
                    },
                    revision=2,
                ),
                _event(
                    "artifact.accepted",
                    {
                        "artifact_id": "artifact.once",
                        "manifest_sha256": "d" * 64,
                        "artifact_sha256": "e" * 64,
                        "attempt_id": None,
                    },
                    revision=3,
                ),
            ]
        )

    with pytest.raises(ReducerError, match="already used"):
        reduce_events("core-research.v1", events)


def test_freshness_is_dynamic_and_does_not_change_events() -> None:
    from arw.reducer import reduce_events

    events = [
        _event("run.initialized", {"manifest_sha256": "a" * 64}, revision=1),
        _event(
            "passport.accepted",
            {
                "passport_sha256": "c" * 64,
                "parent_passport_sha256": None,
                "supersedes_passport_sha256": None,
                "checkpoint_kind": "explicit",
                "based_on_revision": 1,
                "stage": "initialized",
                "fresh_until": "2026-07-13T01:00:00Z",
            },
            revision=2,
        ),
    ]
    before = [event.model_dump(mode="json") for event in events]
    state = reduce_events(
        "core-research.v1",
        events,
        now=datetime(2026, 7, 13, 2, tzinfo=UTC),
    )
    assert "evidence-expired" in [blocker.code for blocker in state.blockers]
    assert [event.model_dump(mode="json") for event in events] == before


@pytest.mark.parametrize(
    ("based_on_revision", "supersedes", "message"),
    [
        (0, None, "stage/revision"),
        (1, "d" * 64, "supersession"),
    ],
)
def test_reducer_rejects_non_exact_or_branching_passport(
    based_on_revision: int, supersedes: str | None, message: str
) -> None:
    from arw.reducer import ReducerError, reduce_events

    events = [
        _event("run.initialized", {"manifest_sha256": "a" * 64}, revision=1),
        _event(
            "passport.accepted",
            {
                "passport_sha256": "c" * 64,
                "parent_passport_sha256": None,
                "supersedes_passport_sha256": supersedes,
                "checkpoint_kind": "explicit",
                "based_on_revision": based_on_revision,
                "stage": "initialized",
                "fresh_until": None,
            },
            revision=2,
        ),
    ]

    with pytest.raises(ReducerError, match=message):
        reduce_events("core-research.v1", events)


def test_phase4_replay_reduces_parent_events_and_status_without_evidence_files() -> None:
    from arw.canonical import sha256_hex
    from arw.models import (
        AssignmentPreparedPayload,
        CanonicalEvent,
        ExecutionModeSelectedPayload,
        ProposalAcceptedPayload,
    )
    from arw.reducer import reduce_events
    from arw.status import build_status_report

    assignment = _phase4_assignment(assignment_id="assignment.phase4-001", task_ordinal=0)
    attempt = _phase4_attempt(assignment, attempt_id="attempt.phase4-001")
    proposal = _phase4_proposal(assignment, attempt)
    proposal_sha256 = sha256_hex(
        __import__("arw.orchestration_models", fromlist=["canonical_orchestration_model_bytes"])
        .canonical_orchestration_model_bytes(proposal)
    )
    events = [
        _event("run.initialized", {"manifest_sha256": HASH_A}, revision=1),
        _event(
            "execution.mode_selected",
            ExecutionModeSelectedPayload(
                execution_mode="native_formal",
                execution_provenance="assignment_injected_subagent",
                role_catalog_sha256=HASH_B,
                policy_sha256=HASH_C,
                dag_sha256=HASH_D,
            ),
            revision=2,
        ),
        _event(
            "assignment.prepared",
            AssignmentPreparedPayload(
                assignment=assignment,
                assignment_sha256=assignment.canonical_sha256(),
            ),
            revision=3,
        ),
        _event(
            "attempt.prepared",
            {
                "assignment_id": assignment.assignment_id,
                "assignment_sha256": assignment.canonical_sha256(),
                "attempt": attempt,
            },
            revision=4,
        ),
        _event(
            "proposal.accepted",
            ProposalAcceptedPayload(
                assignment_id=assignment.assignment_id,
                assignment_sha256=assignment.canonical_sha256(),
                attempt_id=attempt.attempt_id,
                proposal=proposal,
                proposal_sha256=proposal_sha256,
                acceptance_key=assignment.acceptance_key.value,
            ),
            revision=5,
        ),
    ]
    first = reduce_events("core-research.v1", events)
    second = reduce_events("core-research.v1", tuple(events))

    assert first == second
    assert first.execution_mode == "native_formal"
    assert first.role_catalog_sha256 == HASH_B
    assert [item.assignment_id for item in first.assignments] == [assignment.assignment_id]
    assert first.accepted_proposal_sha256 == (proposal_sha256,)
    assert first.deterministic_commit_cursor == assignment.acceptance_key.value
    report = build_status_report(first)
    assert report.status == "PASS"
    assert report.accepted_proposal_sha256 == (proposal_sha256,)


def test_phase4_reducer_buffers_frozen_order_and_blocks_stale_or_unresolved_results() -> None:
    from arw.canonical import sha256_hex
    from arw.models import (
        AssignmentPreparedPayload,
        AttemptLifecyclePayload,
        GateEvaluatedPayload,
        ProposalAcceptedPayload,
    )
    from arw.orchestration_models import GateDecision, canonical_orchestration_model_bytes
    from arw.reducer import reduce_events

    first_assignment = _phase4_assignment(assignment_id="assignment.phase4-002", task_ordinal=0)
    second_assignment = _phase4_assignment(assignment_id="assignment.phase4-003", task_ordinal=1)
    first_attempt = _phase4_attempt(first_assignment, attempt_id="attempt.phase4-002")
    second_attempt = _phase4_attempt(second_assignment, attempt_id="attempt.phase4-003")
    first_proposal = _phase4_proposal(first_assignment, first_attempt)
    second_proposal = _phase4_proposal(second_assignment, second_attempt)

    def proposal_event(assignment, attempt, proposal, revision: int):
        return _event(
            "proposal.accepted",
            ProposalAcceptedPayload(
                assignment_id=assignment.assignment_id,
                assignment_sha256=assignment.canonical_sha256(),
                attempt_id=attempt.attempt_id,
                proposal=proposal,
                proposal_sha256=sha256_hex(canonical_orchestration_model_bytes(proposal)),
                acceptance_key=assignment.acceptance_key.value,
            ),
            revision=revision,
        )

    events = [
        _event("run.initialized", {"manifest_sha256": HASH_A}, revision=1),
        _event(
            "assignment.prepared",
            AssignmentPreparedPayload(
                assignment=first_assignment,
                assignment_sha256=first_assignment.canonical_sha256(),
            ),
            revision=2,
        ),
        _event(
            "assignment.prepared",
            AssignmentPreparedPayload(
                assignment=second_assignment,
                assignment_sha256=second_assignment.canonical_sha256(),
            ),
            revision=3,
        ),
        _event(
            "attempt.prepared",
            {
                "assignment_id": first_assignment.assignment_id,
                "assignment_sha256": first_assignment.canonical_sha256(),
                "attempt": first_attempt,
            },
            revision=4,
        ),
        _event(
            "attempt.prepared",
            {
                "assignment_id": second_assignment.assignment_id,
                "assignment_sha256": second_assignment.canonical_sha256(),
                "attempt": second_attempt,
            },
            revision=5,
        ),
        proposal_event(second_assignment, second_attempt, second_proposal, 6),
        proposal_event(first_assignment, first_attempt, first_proposal, 7),
        _event(
            "attempt.lifecycle",
            AttemptLifecyclePayload(
                assignment_id=first_assignment.assignment_id,
                assignment_sha256=first_assignment.canonical_sha256(),
                attempt_id=first_attempt.attempt_id,
                attempt_number=1,
                status="rejected_stale",
                proposal_sha256=sha256_hex(canonical_orchestration_model_bytes(first_proposal)),
                reason_code="late-result",
            ),
            revision=8,
        ),
        _event(
            "gate.evaluated",
            GateEvaluatedPayload(
                decision=(gate := GateDecision.model_validate(
                    {
                        "schema_version": "arw.gate-decision.v1",
                        "gate_id": "gate.phase4-001",
                        "subject_sha256": HASH_A,
                        "evidence_sha256": [HASH_B],
                        "verdict": "BLOCKED",
                        "rationale": "A required report is missing.",
                        "fresh_until": None,
                        "required": True,
                        "human_decision": None,
                    }
                )),
                decision_sha256=sha256_hex(canonical_orchestration_model_bytes(gate)),
            ),
            revision=9,
        ),
    ]
    state = reduce_events("core-research.v1", events)
    assert state.accepted_proposal_sha256 == (
        sha256_hex(canonical_orchestration_model_bytes(first_proposal)),
        sha256_hex(canonical_orchestration_model_bytes(second_proposal)),
    )
    assert "gate.phase4-001" in [item.code for item in state.blockers]
    assert state.status == "BLOCKED"
