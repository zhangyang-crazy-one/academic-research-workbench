"""Fresh gate and scoped append-only human decision integration tests."""

from __future__ import annotations

import asyncio
from pathlib import Path

from arw.kernel.execution.execution import DeterministicFakeAdapter
from arw.kernel.state.models import LifecycleTransitionRequest, RuntimeCommandRequest
from arw.kernel.execution.orchestration import AssignmentSpec, OrchestrationService
from arw.kernel.state.orchestration_models import GateDecision, HumanAuthority, HumanDecisionRecord

from .test_orchestration_lifecycle import _run
from .test_orchestration_lifecycle import _ProposalWritingAdapter


def _request(revision: int, number: int, occurred_at: str = "2026-07-15T01:30:00Z") -> RuntimeCommandRequest:
    return RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": "run-00000000-0000-4000-8000-000000000404",
            "event_id": f"evt-00000000-0000-4000-8000-{number:012x}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012x}",
            "expected_revision": revision,
            "occurred_at": occurred_at,
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
        }
    )


def _prepared(tmp_path: Path) -> tuple[OrchestrationService, object]:
    root, init_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(
        init_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.gate-001",
                stage_id="preparing",
                task_id="task.gate-001",
                role_id="research_architect",
                worker_identity_id="worker.gate-001",
                acceptance_key=(0, 0),
            ),
        ),
    )
    return service, prepared


def _gate(evidence: str, *, verdict: str = "PASS", fresh_until: str | None = "2026-07-15T02:00:00Z") -> GateDecision:
    return GateDecision(
        schema_version="arw.gate-decision.v1",
        gate_id="gate.final-001",
        subject_sha256="a" * 64,
        evidence_sha256=(evidence,),
        verdict=verdict,
        rationale="parent evaluated the scoped gate",
        fresh_until=fresh_until,
        required=True,
        human_decision=None,
    )


def test_p04_05_t02_stale_evidence_cannot_finalize_run(tmp_path: Path) -> None:
    service, prepared = _prepared(tmp_path)
    stale = _gate(prepared.state.ledger_head_sha256, fresh_until="2026-07-15T01:00:00Z")
    outcome = service.evaluate_gate(_request(prepared.state.accepted_revision, 520), stale)
    assert outcome.accepted
    assert outcome.state.gates[-1].verdict == "BLOCKED"
    transition = service.runtime.execute_transition(
        LifecycleTransitionRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": prepared.state.run_id,
                "event_id": "evt-00000000-0000-4000-8000-000000000521",
                "command_id": "cmd-00000000-0000-4000-8000-000000000521",
                "expected_revision": outcome.state.accepted_revision,
                "occurred_at": "2026-07-15T01:31:00Z",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
                "transition_id": "complete",
                "from_stage": outcome.state.stage,
            }
        )
    )
    assert not transition.accepted
    assert transition.rejection is not None


def test_p04_05_t02_human_correction_does_not_rewrite_history(tmp_path: Path) -> None:
    service, prepared = _prepared(tmp_path)
    gate_outcome = service.evaluate_gate(
        _request(prepared.state.accepted_revision, 522),
        _gate(prepared.state.ledger_head_sha256, verdict="BLOCKED"),
    )
    assert gate_outcome.accepted
    gate = gate_outcome.state.gates[-1]
    authority = HumanAuthority(
        schema_version="arw.human-authority.v1",
        authority_id="authority.review-001",
        authenticated_actor_id="operator.user",
        accountable_role="review_authority",
        validated_by_actor_id="parent.runtime",
        allowed_decision_kinds=("waiver", "correction"),
        allowed_gate_ids=(gate.gate_id,),
        allowed_scopes=(gate.gate_id,),
        authenticated_at="2026-07-15T01:20:00Z",
        expires_at="2026-07-15T02:00:00Z",
        evidence_sha256=(gate_outcome.state.ledger_head_sha256,),
    )
    authority_outcome = service.record_human_authority(
        _request(gate_outcome.state.accepted_revision, 523), authority
    )
    assert authority_outcome.accepted
    waiver = HumanDecisionRecord(
        schema_version="arw.human-decision.v1",
        decision_id="decision.waiver-001",
        decision_kind="waiver",
        gate_id=gate.gate_id,
        subject_sha256=gate.subject_sha256,
        evidence_sha256=gate.evidence_sha256,
        applicable_transition="dispatch",
        accountable_actor_id="operator.user",
        accountable_role="review_authority",
        scope="gate.final-001",
        rationale="Release only the named BLOCKED gate for the scoped transition.",
        prior_verdict_sha256=gate.decision_sha256,
        authority_sha256=authority.authority_sha256,
        supersedes_decision_id=None,
        blocker_action="release",
        blocker_code=gate.gate_id,
    )
    waiver_outcome = service.record_human_decision(
        _request(authority_outcome.state.accepted_revision, 524), waiver
    )
    assert waiver_outcome.accepted
    assert gate.gate_id not in {item.code for item in waiver_outcome.state.blockers}
    correction = HumanDecisionRecord(
        schema_version="arw.human-decision.v1",
        decision_id="decision.correction-001",
        decision_kind="correction",
        gate_id=gate.gate_id,
        subject_sha256=gate.subject_sha256,
        evidence_sha256=gate.evidence_sha256,
        applicable_transition="dispatch",
        accountable_actor_id="operator.user",
        accountable_role="review_authority",
        scope="gate.final-001",
        rationale="Correct the scoped approval rationale; retain the prior record.",
        prior_verdict_sha256=gate.decision_sha256,
        authority_sha256=authority.authority_sha256,
        supersedes_decision_id=waiver.decision_id,
        blocker_action="restore",
        blocker_code=gate.gate_id,
    )
    corrected = service.record_human_decision(
        _request(waiver_outcome.state.accepted_revision, 525), correction
    )
    assert corrected.accepted
    assert [item.decision_id for item in corrected.state.human_decision_history] == [
        waiver.decision_id,
        correction.decision_id,
    ]
    assert gate.gate_id in {
        item.code for item in corrected.state.blockers
    }
    assert [item.action for item in corrected.state.blocker_release_history] == [
        "release",
        "restore",
    ]


def test_p04_05_t02_gate_hash_remains_known_after_later_events(tmp_path: Path) -> None:
    service, prepared = _prepared(tmp_path)
    first = service.evaluate_gate(
        _request(prepared.state.accepted_revision, 526),
        _gate(prepared.state.ledger_head_sha256),
    )
    assert first.accepted
    first_gate = first.state.gates[-1]
    second_decision = _gate(first_gate.decision_sha256).model_copy(
        update={"gate_id": "gate.final-002"}
    )
    second = service.evaluate_gate(
        _request(first.state.accepted_revision, 527), second_decision
    )

    assert second.accepted
    assert second.state.gates[-1].verdict == "PASS"
    assert first_gate.decision_sha256 in second.state.accepted_evidence_sha256


def test_p04_05_t02_blocked_gate_cannot_launder_unknown_evidence(
    tmp_path: Path,
) -> None:
    service, prepared = _prepared(tmp_path)
    unknown = "f" * 64
    first = service.evaluate_gate(
        _request(prepared.state.accepted_revision, 528),
        _gate(unknown, verdict="BLOCKED").model_copy(
            update={"gate_id": "gate.unknown-001"}
        ),
    )
    assert first.accepted
    second = service.evaluate_gate(
        _request(first.state.accepted_revision, 529),
        _gate(unknown, verdict="BLOCKED").model_copy(
            update={"gate_id": "gate.unknown-002"}
        ),
    )

    assert second.accepted
    assert "evidence is not accepted" in second.state.gates[-1].decision.rationale
    assert unknown not in second.state.accepted_evidence_sha256


def test_p04_05_t02_human_actor_and_prior_hash_must_match_authority(
    tmp_path: Path,
) -> None:
    service, prepared = _prepared(tmp_path)
    gate_outcome = service.evaluate_gate(
        _request(prepared.state.accepted_revision, 530),
        _gate(prepared.state.ledger_head_sha256, verdict="BLOCKED"),
    )
    gate = gate_outcome.state.gates[-1]
    authority = HumanAuthority(
        schema_version="arw.human-authority.v1",
        authority_id="authority.review-002",
        authenticated_actor_id="reviewer.authorized",
        accountable_role="review_authority",
        validated_by_actor_id="parent.runtime",
        allowed_decision_kinds=("waiver",),
        allowed_gate_ids=(gate.gate_id,),
        allowed_scopes=(gate.gate_id,),
        authenticated_at="2026-07-15T01:20:00Z",
        expires_at="2026-07-15T02:00:00Z",
        evidence_sha256=(gate_outcome.state.ledger_head_sha256,),
    )
    accepted_authority = service.record_human_authority(
        _request(gate_outcome.state.accepted_revision, 531), authority
    )
    base = HumanDecisionRecord(
        schema_version="arw.human-decision.v1",
        decision_id="decision.waiver-002",
        decision_kind="waiver",
        gate_id=gate.gate_id,
        subject_sha256=gate.subject_sha256,
        evidence_sha256=gate.evidence_sha256,
        applicable_transition="dispatch",
        accountable_actor_id="reviewer.authorized",
        accountable_role="review_authority",
        scope=gate.gate_id,
        rationale="Scoped waiver backed by authenticated review authority.",
        prior_verdict_sha256=gate.decision_sha256,
        authority_sha256=authority.authority_sha256,
        supersedes_decision_id=None,
        blocker_action="release",
        blocker_code=gate.gate_id,
    )
    wrong_actor = base.model_copy(
        update={
            "decision_id": "decision.waiver-wrong-actor",
            "accountable_actor_id": "attacker.self-reported",
        }
    )
    actor_rejected = service.record_human_decision(
        _request(accepted_authority.state.accepted_revision, 532), wrong_actor
    )
    assert not actor_rejected.accepted
    assert actor_rejected.rejection is not None
    assert actor_rejected.rejection.code == "authority-scope-mismatch"

    wrong_hash = base.model_copy(
        update={
            "decision_id": "decision.waiver-wrong-hash",
            "prior_verdict_sha256": "e" * 64,
        }
    )
    hash_rejected = service.record_human_decision(
        _request(accepted_authority.state.accepted_revision, 533), wrong_hash
    )
    assert not hash_rejected.accepted
    assert hash_rejected.rejection is not None
    assert hash_rejected.rejection.code == "prior-verdict-mismatch"


def test_p04_05_t02_required_gate_prevents_premature_pass(tmp_path: Path) -> None:
    root, init_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=_ProposalWritingAdapter())
    prepared = service.prepare(
        init_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.required-gate",
                stage_id="preparing",
                task_id="task.required-gate",
                role_id="research_architect",
                worker_identity_id="worker.required-gate",
                acceptance_key=(0, 0),
                requires_human_gate=True,
            ),
        ),
    )
    dispatched = asyncio.run(
        service.dispatch(
            _request(prepared.state.accepted_revision, 534), prepared
        )
    )
    assert len(dispatched.state.accepted_proposals) == 1
    assert dispatched.state.status == "RUNNING"

    gate = service.evaluate_gate(
        _request(dispatched.state.accepted_revision, 535),
        _gate(dispatched.state.accepted_proposal_sha256[0]),
    )
    assert gate.accepted
    assert gate.state.status == "PASS"


def test_p04_05_t02_fail_gate_remains_fail_not_blocked(tmp_path: Path) -> None:
    service, prepared = _prepared(tmp_path)
    failed = service.evaluate_gate(
        _request(prepared.state.accepted_revision, 536),
        _gate(prepared.state.ledger_head_sha256, verdict="FAIL"),
    )

    assert failed.accepted
    assert failed.state.gates[-1].verdict == "FAIL"
    assert failed.state.status == "FAIL"
