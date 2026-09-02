"""Unit tests for the LedgerProjection mapper (PR4 Lane B task 3.1)."""

from __future__ import annotations

from arw_ext.local_store import (
    map_ledger_events,  # pyright: ignore[reportMissingImports]
)

from arw.kernel.core.canonical import canonical_event_bytes, sha256_hex
from arw.kernel.state.models import (
    ArtifactAcceptedPayload,
    CanonicalEvent,
    ExperimentProvenanceAcceptedPayload,
    GateEvaluatedPayload,
    LifecycleTransitionedPayload,
    ProposalAcceptedPayload,
    ReviewReportAcceptedPayload,
    RunInitializedPayload,
)
from arw.kernel.state.orchestration_models import (
    ReviewFindingMatrix,
    ReviewSynthesis,
)
from arw.kernel.state.orchestration_models import (
    ReviewReport as ORReport,
)

HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64

RUN_ID = "run-00000000-0000-4000-8000-0000000000a1"


def _event_id(seq: int) -> str:
    return f"evt-00000000-0000-4000-8000-{seq:012x}"


def _command_id(seq: int) -> str:
    return f"cmd-00000000-0000-4000-8000-{seq:012x}"


def _event(
    *,
    event_type: str,
    payload,
    seq: int = 1,
    run_id: str = RUN_ID,
    occurred_at: str = "2026-07-15T10:00:00Z",
    actor_id: str = "parent.runtime",
    actor_role: str = "parent_control_plane",
    prev_event_sha256: str = "0" * 64,
) -> CanonicalEvent:
    unsigned = {
        "schema_version": "1.0.0",
        "event_type": event_type,
        "event_id": _event_id(seq),
        "command_id": _command_id(seq),
        "run_id": run_id,
        "sequence": seq,
        "occurred_at": occurred_at,
        "expected_revision": seq - 1,
        "resulting_revision": seq,
        "actor_id": actor_id,
        "actor_role": actor_role,
        "prev_event_sha256": prev_event_sha256,
        "payload": payload.model_dump(mode="json"),
    }
    unsigned["event_sha256"] = sha256_hex(canonical_event_bytes(unsigned))
    return CanonicalEvent.model_validate(unsigned)


def _review_report(*, report_id: str, role_id: str, worker: str, host: str) -> ORReport:
    return ORReport.model_validate(
        {
            "report_id": report_id,
            "panel_manifest_sha256": HASH_A,
            "assignment_id": "asg.panel-x",
            "attempt_id": "atp.panel-x",
            "identity_receipt_sha256": HASH_B,
            "role_id": role_id,
            "worker_identity_id": worker,
            "host_agent_id": host,
            "subject_sha256": HASH_C,
            "rubric_sha256": HASH_D,
            "findings": [
                {
                    "finding_id": f"finding-{report_id}",
                    "summary": "review summary",
                    "severity": "info",
                    "evidence_sha256": [HASH_E],
                }
            ],
        }
    )


def _finding_matrix() -> ReviewFindingMatrix:
    reports = tuple(
        _review_report(
            report_id=f"report-{index}",
            role_id=role_id,
            worker=f"worker.{role_id}",
            host=f"host.{role_id}",
        )
        for index, role_id in enumerate(
            [
                "research_architect",
                "domain_researcher",
                "method_reviewer",
                "red_team_reviewer",
            ]
        )
    )
    synthesis = ReviewSynthesis.model_validate(
        {
            "synthesis_id": "synthesis-x",
            "panel_manifest_sha256": HASH_A,
            "identity_receipt_sha256": HASH_B,
            "worker_identity_id": "worker.editor",
            "host_agent_id": "host.editor",
            "source_report_sha256": [item.report_sha256 for item in reports],
            "findings": [],
            "limitations": [],
        }
    )
    return ReviewFindingMatrix.model_validate(
        {
            "schema_version": "arw.review-finding-matrix.v1",
            "panel_id": "panel-x",
            "panel_manifest_sha256": HASH_A,
            "subject_sha256": HASH_C,
            "rubric_sha256": HASH_D,
            "reports": list(reports),
            "synthesis": synthesis,
            "gate_verdict": "PASS",
        }
    )


def _proposal_for_test(*, evidence_sha256: tuple[str, ...]):
    from arw.kernel.state.orchestration_models import (
        WorkerProposal,
        canonical_orchestration_model_bytes,
    )

    proposal = WorkerProposal.model_validate(
        {
            "schema_version": "arw.worker-proposal.v1",
            "protocol_version": "1.0.0",
            "run_id": RUN_ID,
            "assignment_id": "asg.proposal-x",
            "attempt_id": "atp.proposal-x",
            "role_id": "research_architect",
            "worker_identity_id": "worker.proposal",
            "host_agent_id": "host.proposal",
            "execution_mode": "assignment_injected_subagent",
            "execution_provenance": "assignment_injected_subagent",
            "independence_eligible": False,
            "assignment_sha256": HASH_A,
            "context_manifest_sha256": HASH_A,
            "policy_sha256": HASH_A,
            "base_revision": 1,
            "input_sha256": [HASH_A],
            "proposal_nonce": "nonce.proposal",
            "status": "completed",
            "result_provenance_mode": "executed",
            "requested_next_action": "accept",
            "artifacts": [
                {
                    "relative_path": "result.json",
                    "sha256": HASH_B,
                    "media_type": "application/json",
                    "schema_id": "arw.worker-proposal.v1",
                    "byte_count": 128,
                }
            ],
            "evidence_sha256": list(evidence_sha256),
            "summary": "ok",
            "unresolved": [],
        }
    )
    proposal_sha256 = sha256_hex(canonical_orchestration_model_bytes(proposal))
    # Attach the canonical digest so callers can pass it as proposal_sha256.
    proposal._proposal_sha256 = proposal_sha256  # type: ignore[attr-defined]
    return proposal, proposal_sha256


def test_mapper_runs_initialized_yields_run_node_with_manifest_digest() -> None:
    payload = RunInitializedPayload(manifest_sha256=HASH_A)
    event = _event(event_type="run.initialized", payload=payload, seq=1)
    records, binding = map_ledger_events([event])
    assert len(records) == 1
    assert records[0]["entity_type"] == "Run"
    assert records[0]["source_digest"] == HASH_A
    assert binding["direct"]["Run"][HASH_A][0] == event.event_id


def test_mapper_artifact_accepted_uses_manifest_sha256_and_artifact_sha256() -> None:
    payload = ArtifactAcceptedPayload(
        artifact_id="artifact-x",
        manifest_sha256=HASH_A,
        artifact_sha256=HASH_B,
        attempt_id="attempt-x",
    )
    event = _event(event_type="artifact.accepted", payload=payload, seq=2)
    records, binding = map_ledger_events([event])
    assert records[0]["entity_type"] == "Artifact"
    assert records[0]["source_digest"] == HASH_A
    assert records[0]["_artifact_sha256"] == HASH_B
    assert binding["direct"]["Artifact"][HASH_A][0] == event.event_id


def test_mapper_proposal_accepted_uses_proposal_sha256() -> None:
    proposal, proposal_sha256 = _proposal_for_test(evidence_sha256=(HASH_C,))
    payload = ProposalAcceptedPayload.model_validate(
        {
            "assignment_id": "asg.proposal-x",
            "assignment_sha256": HASH_A,
            "attempt_id": "atp.proposal-x",
            "proposal": proposal,
            "proposal_sha256": proposal_sha256,
            "acceptance_key": (0, 0, "asg.proposal-x"),
        }
    )
    event = _event(event_type="proposal.accepted", payload=payload, seq=2)
    records, binding = map_ledger_events([event])
    claim_record = next(item for item in records if item["entity_type"] == "Claim")
    assert claim_record["source_digest"] == proposal_sha256
    assert claim_record["entity_id"] == f"claim-{proposal_sha256[:24]}"
    edges = claim_record.get("edges", [])
    assert any(item["edge_type"] == "supported_by" for item in edges)
    # The proposal_sha256 is bound directly
    assert binding["direct"]["Claim"][proposal_sha256][0] == event.event_id


def test_mapper_review_report_uses_report_sha256() -> None:
    from arw.kernel.state.orchestration_models import review_report_body_sha256

    report = ORReport.model_validate(
        {
            "report_id": "report-x",
            "panel_manifest_sha256": HASH_A,
            "assignment_id": "asg.review-x",
            "attempt_id": "atp.review-x",
            "identity_receipt_sha256": HASH_B,
            "role_id": "research_architect",
            "worker_identity_id": "worker.x",
            "host_agent_id": "host.x",
            "subject_sha256": HASH_C,
            "rubric_sha256": HASH_D,
            "findings": [
                {
                    "finding_id": "f-1",
                    "source_report_sha256": [sha256_hex(b"placeholder")],
                    "evidence_sha256": [HASH_E],
                    "severity": "low",
                    "confidence": 0.9,
                    "classification": "consensus",
                    "resolution": "resolved",
                    "rationale": "ok",
                }
            ],
        }
    )
    report_sha256 = review_report_body_sha256(report)
    review_event = _event(
        event_type="review.report_accepted",
        payload=ReviewReportAcceptedPayload.model_validate(
            {"report": report, "report_sha256": report_sha256}
        ),
        seq=2,
    )
    records, _ = map_ledger_events([review_event])
    review_records = [item for item in records if item["entity_type"] == "Review"]
    assert len(review_records) == 1
    assert review_records[0]["source_digest"] == report_sha256


def test_mapper_gate_evaluated_uses_decision_sha256() -> None:
    from arw.kernel.state.orchestration_models import (
        GateDecision,
        canonical_orchestration_model_bytes,
    )

    decision = GateDecision.model_validate(
        {
            "schema_version": "arw.gate-decision.v1",
            "gate_id": "gate-x",
            "subject_sha256": HASH_A,
            "evidence_sha256": [HASH_B],
            "verdict": "PASS",
            "rationale": "ok",
            "fresh_until": None,
            "required": True,
            "human_decision": None,
        }
    )
    expected_sha = sha256_hex(canonical_orchestration_model_bytes(decision))
    payload = GateEvaluatedPayload.model_validate(
        {
            "decision": decision,
            "decision_sha256": expected_sha,
        }
    )
    event = _event(event_type="gate.evaluated", payload=payload, seq=2)
    records, _ = map_ledger_events([event])
    assert records[0]["entity_type"] == "Gate"
    assert records[0]["source_digest"] == expected_sha
    assert records[0]["entity_id"] == "gate-gate-x"


def test_mapper_experiment_provenance_uses_provenance_sha256() -> None:
    payload = ExperimentProvenanceAcceptedPayload(
        provenance_id="prov-x",
        experiment_id="experiment-x",
        provenance_sha256=HASH_A,
    )
    event = _event(event_type="experiment.provenance.accepted", payload=payload, seq=2)
    records, _ = map_ledger_events([event])
    assert records[0]["entity_type"] == "Experiment"
    assert records[0]["source_digest"] == HASH_A


def test_mapper_lifecycle_transition_yields_stage_node_with_deterministic_id() -> None:
    payload = LifecycleTransitionedPayload(
        transition_id="t-1",
        from_stage="initialized",
        to_stage="executing",
    )
    event = _event(event_type="lifecycle.transitioned", payload=payload, seq=2)
    records, _ = map_ledger_events([event])
    assert records[0]["entity_type"] == "Stage"
    assert records[0]["entity_id"].startswith("stage-")
    # Determinism — the same from/to pair always maps to the same Stage ID
    records2, _ = map_ledger_events([event])
    assert records[0]["entity_id"] == records2[0]["entity_id"]


def test_mapper_emits_synthetic_source_node_when_payload_consumes_a_digest() -> None:
    """An event whose payload references a digest in consumed_sha256
    creates a synthetic Source node whose entity_id is stable."""

    proposal, proposal_sha256 = _proposal_for_test(evidence_sha256=(HASH_A,))
    proposal_event = _event(
        event_type="proposal.accepted",
        payload=ProposalAcceptedPayload.model_validate(
            {
                "assignment_id": "asg.proposal-x",
                "assignment_sha256": HASH_A,
                "attempt_id": "atp.proposal-x",
                "proposal": proposal,
                "proposal_sha256": proposal_sha256,
                "acceptance_key": (0, 0, "asg.proposal-x"),
            }
        ),
        seq=2,
    )
    records, binding = map_ledger_events([proposal_event])
    synthetic_sources = [
        record
        for record in records
        if record.get("_synthetic") and record["entity_type"] == "Source"
    ]
    assert len(synthetic_sources) == 1
    assert synthetic_sources[0]["source_digest"] == HASH_A
    assert HASH_A in binding["indirect"]
