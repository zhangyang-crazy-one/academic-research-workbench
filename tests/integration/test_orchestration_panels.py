"""Parent-integrated formal panel and dissent preservation tests."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path

import pytest

from arw.canonical import sha256_hex
from arw.execution import DeterministicFakeAdapter
from arw.models import RuntimeCommandRequest
from arw.orchestration import OrchestrationError, OrchestrationService
from arw.orchestration_models import (
    HostIdentityReceipt,
    ReviewFinding,
    ReviewFindingMatrix,
    ReviewReport,
    ReviewSynthesis,
)

from .test_orchestration_lifecycle import (
    AssignmentSpec,
    _ProposalWritingAdapter,
    _run,
)


SUBJECT = "a" * 64
RUBRIC = "b" * 64
EVIDENCE = "c" * 64
ROLES = (
    "methodology_reviewer",
    "domain_reviewer",
    "perspective_reviewer",
    "devils_advocate_reviewer",
)


def _request(revision: int, number: int) -> RuntimeCommandRequest:
    return RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": "run-00000000-0000-4000-8000-000000000404",
            "event_id": f"evt-00000000-0000-4000-8000-{number:012x}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012x}",
            "expected_revision": revision,
            "occurred_at": f"2026-07-15T01:20:{number % 60:02d}Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
        }
    )


def _identities(receipts: dict[str, str]) -> dict[str, dict[str, object]]:
    return {
        role: {
            "worker_identity_id": f"worker.{role}",
            "host_agent_id": f"host.{role}",
            "isolated": True,
            "role_ids": [role],
            "identity_receipt_sha256": receipts[role],
        }
        for role in ROLES
    }


def _panel(service: OrchestrationService):
    receipts: dict[str, str] = {}
    for index, role in enumerate((*ROLES, "editorial_synthesizer"), start=490):
        state = service.runtime.read_state()
        receipt = HostIdentityReceipt(
            schema_version="arw.host-identity-receipt.v1",
            receipt_id=f"receipt.{role}",
            role_id=role,
            worker_identity_id=(
                "worker.editorial-synthesizer"
                if role == "editorial_synthesizer"
                else f"worker.{role}"
            ),
            host_agent_id=(
                "host.editorial-synthesizer"
                if role == "editorial_synthesizer"
                else f"host.{role}"
            ),
            transport="isolated_codex_exec",
            codex_version="0.144.3",
            assignment_mapping_proven=True,
            isolation_proven=True,
            peer_isolation_proven=True,
            credential_isolation_proven=True,
            observed_at="2026-07-15T01:19:00Z",
            evidence_sha256=(state.ledger_head_sha256,),
        )
        outcome = service.record_host_identity(
            _request(state.accepted_revision, index), receipt
        )
        assert outcome.accepted
        receipts[role] = receipt.receipt_sha256
    state = service.runtime.read_state()
    return service.prepare_formal_panel(
        _request(state.accepted_revision, 499),
        panel_id="panel.phase4-001",
        subject_sha256=SUBJECT,
        rubric_sha256=RUBRIC,
        reviewer_identities=_identities(receipts),
        synthesizer_identity={
            "worker_identity_id": "worker.editorial-synthesizer",
            "host_agent_id": "host.editorial-synthesizer",
            "isolated": True,
            "role_ids": ["editorial_synthesizer"],
            "identity_receipt_sha256": receipts["editorial_synthesizer"],
        },
    )


def _report(panel, role: str, ordinal: int, *, critical: bool = False) -> ReviewReport:
    seat = next(item for item in panel.reviewer_assignments if item.role_id == role)
    source_hash = hashlib.sha256(f"report-source:{role}".encode()).hexdigest()
    finding_hash = hashlib.sha256(f"finding:{role}".encode()).hexdigest()
    finding = ReviewFinding(
        finding_id="finding.methodology-001",
        source_report_sha256=(source_hash,),
        evidence_sha256=(EVIDENCE,),
        severity="critical" if critical else "moderate",
        confidence=0.9,
        classification="DA-critical" if critical else "majority",
        resolution="unresolved" if critical else "resolved",
        rationale=f"{role} finding {finding_hash}",
    )
    return ReviewReport(
        report_id=f"report.{role}",
        panel_manifest_sha256=panel.manifest_sha256,
        assignment_id=seat.assignment_id,
        attempt_id=seat.attempt_id,
        identity_receipt_sha256=seat.identity_receipt_sha256,
        role_id=role,
        worker_identity_id=f"worker.{role}",
        host_agent_id=f"host.{role}",
        subject_sha256=SUBJECT,
        rubric_sha256=RUBRIC,
        findings=(finding,),
    )


def _matrix(panel, reports: tuple[ReviewReport, ...]) -> ReviewFindingMatrix:
    findings = tuple(
        report.findings[0].model_copy(
            update={"source_report_sha256": (report.report_sha256,)}
        )
        for report in reports
    )
    synthesis = ReviewSynthesis(
        synthesis_id="synthesis.panel.phase4-001",
        panel_manifest_sha256=panel.manifest_sha256,
        identity_receipt_sha256=panel.synthesizer_assignment.identity_receipt_sha256,
        worker_identity_id=panel.synthesizer_assignment.worker_identity_id,
        host_agent_id=panel.synthesizer_assignment.host_agent_id,
        source_report_sha256=tuple(report.report_sha256 for report in reports),
        findings=findings,
        limitations=("devil's-advocate dissent retained",),
    )
    return ReviewFindingMatrix(
        schema_version="arw.review-finding-matrix.v1",
        panel_id=panel.panel_id,
        panel_manifest_sha256=panel.manifest_sha256,
        subject_sha256=SUBJECT,
        rubric_sha256=RUBRIC,
        reports=reports,
        synthesis=synthesis,
        gate_verdict="BLOCKED" if any(item.resolution == "unresolved" for item in findings) else "PASS",
    )


def test_p04_05_t01_missing_required_report_blocks_synthesis(tmp_path: Path) -> None:
    root, prepare_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.panel-001",
                stage_id="preparing",
                task_id="task.panel-001",
                role_id="research_architect",
                worker_identity_id="worker.architect-panel",
                acceptance_key=(0, 0),
            ),
        ),
    )
    panel = _panel(service)
    reports = tuple(_report(panel, role, index) for index, role in enumerate(ROLES))
    revision = service.runtime.read_state().accepted_revision
    for index, report in enumerate(reports[:3], start=502):
        outcome = service.admit_review_report(
            _request(revision, index), panel=panel, report=report
        )
        assert outcome.accepted
        revision = outcome.state.accepted_revision

    with pytest.raises(OrchestrationError, match="accepted source reports"):
        service.admit_review_synthesis(
            _request(revision, 505), panel=panel, finding_matrix=_matrix(panel, reports)
        )


def test_p04_05_t01_da_critical_dissent_is_retained_and_blocks_synthesis(
    tmp_path: Path,
) -> None:
    root, prepare_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.panel-002",
                stage_id="preparing",
                task_id="task.panel-002",
                role_id="research_architect",
                worker_identity_id="worker.architect-panel-002",
                acceptance_key=(0, 0),
            ),
        ),
    )
    panel = _panel(service)
    reports = tuple(
        _report(panel, role, index, critical=role == "devils_advocate_reviewer")
        for index, role in enumerate(ROLES)
    )
    revision = service.runtime.read_state().accepted_revision
    for index, report in enumerate(reports, start=507):
        outcome = service.admit_review_report(
            _request(revision, index), panel=panel, report=report
        )
        assert outcome.accepted
        revision = outcome.state.accepted_revision
    outcome = service.admit_review_synthesis(
        _request(revision, 512), panel=panel, finding_matrix=_matrix(panel, reports)
    )
    assert outcome.accepted
    assert outcome.state.panel_syntheses[0].gate_verdict == "BLOCKED"
    assert outcome.state.panel_syntheses[0].reports[-1].findings[0].rationale.startswith(
        "devils_advocate_reviewer finding"
    )
    assert "formal-review-blocked" in {item.code for item in outcome.state.blockers}


def test_p04_05_t01_panel_manifest_and_seats_survive_cold_replay(
    tmp_path: Path,
) -> None:
    root, prepare_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.panel-replay",
                stage_id="preparing",
                task_id="task.panel-replay",
                role_id="research_architect",
                worker_identity_id="worker.panel-replay",
                acceptance_key=(0, 0),
            ),
        ),
    )
    panel = _panel(service)

    cold = OrchestrationService(
        root, adapter=DeterministicFakeAdapter({})
    ).runtime.read_state()
    manifest = cold.panel_manifests[0]
    assert manifest.manifest_sha256 == panel.manifest_sha256
    assert {seat.role_id for seat in manifest.reviewer_seats} == set(ROLES)
    assert all(seat.identity_receipt_sha256 for seat in manifest.reviewer_seats)
    assert manifest.synthesizer_seat is not None
    events = __import__("arw.journal", fromlist=["replay_run"]).replay_run(root).events
    panel_index = next(
        index for index, event in enumerate(events) if event.event_type == "panel.prepared"
    )
    assert not any(
        event.event_type in {"review.report_accepted", "review.synthesis_accepted"}
        for event in events[:panel_index]
    )


def test_p04_05_t01_report_hash_and_cross_panel_binding_are_derived(
    tmp_path: Path,
) -> None:
    root, prepare_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.panel-hash",
                stage_id="preparing",
                task_id="task.panel-hash",
                role_id="research_architect",
                worker_identity_id="worker.panel-hash",
                acceptance_key=(0, 0),
            ),
        ),
    )
    panel = _panel(service)
    report = _report(panel, ROLES[0], 0)
    changed_finding = report.findings[0].model_copy(
        update={"rationale": "tampered after the report hash was derived"}
    )
    stale_hash = report.model_copy(update={"findings": (changed_finding,)})

    with pytest.raises(ValueError, match="derived from canonical report body"):
        service.admit_review_report(
            _request(service.runtime.read_state().accepted_revision, 540),
            panel=panel,
            report=stale_hash,
        )

    cross_panel = report.model_copy(update={"panel_manifest_sha256": "f" * 64})
    with pytest.raises(OrchestrationError, match="frozen snapshot"):
        service.admit_review_report(
            _request(service.runtime.read_state().accepted_revision, 541),
            panel=panel,
            report=cross_panel,
        )
    assert service.runtime.read_state().accepted_revision > prepared.state.accepted_revision


def test_p04_05_t01_synthesis_cannot_drop_minority_or_da_finding(
    tmp_path: Path,
) -> None:
    root, prepare_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=DeterministicFakeAdapter({}))
    prepared = service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.panel-dissent",
                stage_id="preparing",
                task_id="task.panel-dissent",
                role_id="research_architect",
                worker_identity_id="worker.panel-dissent",
                acceptance_key=(0, 0),
            ),
        ),
    )
    panel = _panel(service)
    reports = tuple(
        _report(panel, role, index, critical=role == "devils_advocate_reviewer")
        for index, role in enumerate(ROLES)
    )
    revision = service.runtime.read_state().accepted_revision
    for index, report in enumerate(reports, start=542):
        accepted = service.admit_review_report(
            _request(revision, index), panel=panel, report=report
        )
        revision = accepted.state.accepted_revision
    matrix = _matrix(panel, reports)
    omitted = matrix.model_copy(
        update={
            "synthesis": matrix.synthesis.model_copy(
                update={"findings": matrix.synthesis.findings[:-1]}
            )
        }
    )

    with pytest.raises(ValueError, match="omitted or altered"):
        service.admit_review_synthesis(
            _request(revision, 550), panel=panel, finding_matrix=omitted
        )


def test_p04_05_t01_ready_panel_prevents_pass_until_exact_synthesis(
    tmp_path: Path,
) -> None:
    root, prepare_request = _run(tmp_path)
    service = OrchestrationService(root, adapter=_ProposalWritingAdapter())
    prepared = service.prepare(
        prepare_request,
        assignments=(
            AssignmentSpec(
                assignment_id="assignment.panel-finality",
                stage_id="preparing",
                task_id="task.panel-finality",
                role_id="research_architect",
                worker_identity_id="worker.panel-finality",
                acceptance_key=(0, 0),
            ),
        ),
    )
    panel = _panel(service)
    dispatched = asyncio.run(
        service.dispatch(
            _request(service.runtime.read_state().accepted_revision, 551), prepared
        )
    )
    assert len(dispatched.state.accepted_proposals) == 1
    assert dispatched.state.status == "RUNNING"

    reports = tuple(
        _report(panel, role, index) for index, role in enumerate(ROLES)
    )
    revision = dispatched.state.accepted_revision
    for index, report in enumerate(reports, start=552):
        accepted = service.admit_review_report(
            _request(revision, index), panel=panel, report=report
        )
        revision = accepted.state.accepted_revision
    synthesized = service.admit_review_synthesis(
        _request(revision, 557), panel=panel, finding_matrix=_matrix(panel, reports)
    )
    assert synthesized.accepted
    assert synthesized.state.status == "PASS"
