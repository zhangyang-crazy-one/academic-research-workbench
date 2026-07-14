"""Formal blind-panel policy and dissent-preserving synthesis tests."""

from __future__ import annotations

from arw.review import (
    FORMAL_REVIEW_ROLES,
    FindingObservation,
    FormalPanelPolicy,
    ReviewerIdentity,
    ReviewerReport,
)


SUBJECT = "a" * 64
RUBRIC = "b" * 64


def _identities() -> dict[str, ReviewerIdentity]:
    return {
        role: ReviewerIdentity(
            worker_identity_id=f"worker.{role}",
            host_agent_id=f"host.{role}",
        )
        for role in FORMAL_REVIEW_ROLES
    }


def test_p04_03_t02_panel_requires_four_distinct_isolated_roles() -> None:
    policy = FormalPanelPolicy()
    panel = policy.prepare_panel(
        panel_id="panel.review-001",
        subject_sha256=SUBJECT,
        rubric_sha256=RUBRIC,
        reviewer_identities=_identities(),
        synthesizer_identity=ReviewerIdentity(
            worker_identity_id="worker.editorial",
            host_agent_id="host.editorial",
        ),
    )

    assert panel.status == "ready"
    assert tuple(assignment.role_id for assignment in panel.reviewer_assignments) == tuple(
        sorted(FORMAL_REVIEW_ROLES)
    )
    assert len(panel.reviewer_assignments) == 4
    assert panel.synthesizer_assignment is not None
    assert panel.synthesizer_assignment.role_id == "editorial_synthesizer"
    assert panel.synthesizer_assignment.assignment_id not in {
        assignment.assignment_id for assignment in panel.reviewer_assignments
    }
    assert len({assignment.worker_identity_id for assignment in panel.reviewer_assignments}) == 4
    assert len({assignment.host_agent_id for assignment in panel.reviewer_assignments}) == 4

    for assignment in panel.reviewer_assignments:
        visible = assignment.blind_envelope.visible_payload
        assert visible["subject_sha256"] == SUBJECT
        assert visible["rubric_sha256"] == RUBRIC
        assert visible["role_id"] == assignment.role_id
        assert "peer_identity_ids" not in visible
        assert "peer_report_sha256" not in visible
        assert "attempt_id" not in visible
        assert "synthesis" not in visible

    duplicate = dict(_identities())
    duplicate["domain_reviewer"] = duplicate["methodology_reviewer"]
    blocked = policy.prepare_panel(
        panel_id="panel.review-duplicate",
        subject_sha256=SUBJECT,
        rubric_sha256=RUBRIC,
        reviewer_identities=duplicate,
        synthesizer_identity=ReviewerIdentity("worker.editorial-2", "host.editorial-2"),
    )
    assert blocked.status == "blocked"
    assert any("distinct" in reason or "identity" in reason for reason in blocked.blockers)


def test_p04_03_t02_unresolved_critical_dissent_blocks_synthesis() -> None:
    policy = FormalPanelPolicy()
    panel = policy.prepare_panel(
        panel_id="panel.review-002",
        subject_sha256=SUBJECT,
        rubric_sha256=RUBRIC,
        reviewer_identities=_identities(),
        synthesizer_identity=ReviewerIdentity("worker.editorial-3", "host.editorial-3"),
    )
    reports = []
    for assignment in panel.reviewer_assignments:
        reports.append(
            ReviewerReport(
                report_id=f"report.{assignment.role_id}",
                role_id=assignment.role_id,
                worker_identity_id=assignment.worker_identity_id,
                host_agent_id=assignment.host_agent_id,
                subject_sha256=SUBJECT,
                rubric_sha256=RUBRIC,
                findings=(
                    FindingObservation(
                        finding_id="finding.consensus",
                        stance="support",
                        evidence_sha256=("c" * 64,),
                        severity="moderate",
                        confidence=0.8,
                        rationale="The reported method is adequately specified.",
                    ),
                    FindingObservation(
                        finding_id="finding.critical",
                        stance=(
                            "challenge"
                            if assignment.role_id == "devils_advocate_reviewer"
                            else "support"
                        ),
                        evidence_sha256=("d" * 64,),
                        severity="critical",
                        confidence=0.95 if assignment.role_id == "devils_advocate_reviewer" else 0.6,
                        rationale=(
                            "The devil's advocate found an unresolved validity threat."
                            if assignment.role_id == "devils_advocate_reviewer"
                            else "No critical threat was found in this review."
                        ),
                        resolved=False,
                    ),
                ),
            )
        )

    result = policy.synthesize(panel, tuple(reports))

    assert result.status == "blocked"
    assert result.synthesis is not None
    assert result.synthesis.gate_verdict == "BLOCKED"
    matrix = {cell.finding_id: cell for cell in result.synthesis.finding_matrix}
    assert matrix["finding.consensus"].classification == "consensus"
    assert matrix["finding.critical"].classification == "DA-critical"
    assert matrix["finding.critical"].resolution == "unresolved"
    assert matrix["finding.critical"].evidence_sha256 == ("d" * 64,)
    assert any(
        "devil's advocate" in observation.rationale
        for observation in matrix["finding.critical"].observations
    )
    assert any("critical" in blocker for blocker in result.blockers)
