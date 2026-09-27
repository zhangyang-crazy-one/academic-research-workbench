from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from arw.cli import main
from arw.composition import default_router
from arw.kernel.capabilities import CapabilityUnavailable
from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.execution import submission as submission_module
from arw.kernel.execution.execution import DeterministicFakeAdapter
from arw.kernel.execution.orchestration import OrchestrationService
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.execution.submission import SubmissionWorkflowService
from arw.kernel.ledger.journal import replay_run
from arw.kernel.policy.contracts import installed_route
from arw.kernel.state.models import (
    ArtifactAcceptanceRequest,
    LifecycleTransitionRequest,
    RuntimeCommandRequest,
)
from arw.kernel.state.orchestration_models import HumanAuthority, HumanDecisionRecord
from arw.kernel.state.submission import (
    DeclarationField,
    JournalRequirementsSnapshot,
    ReviewComment,
    ReviewLocator,
    ReviewResponse,
    ReviewRound,
    SubmissionArtifactReference,
    SubmissionCheck,
    SubmissionCheckReport,
    SubmissionPacket,
    SubmissionResultObservation,
    declaration_subject_sha256,
    response_subject_sha256,
    review_comment_identity,
)
from tests.integration.test_submission_runtime import (
    RUN,
    accept_file,
    request_for,
    seed_run,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SUBMISSION_EXTENSION = PROJECT_ROOT / "extensions/submission-workflow/src"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_file(root: Path, name: str, value: object) -> Path:
    path = root / name
    payload = value if isinstance(value, bytes) else canonical_json_bytes(value)
    path.write_bytes(payload)
    return path


def _reference_from_result(
    result: dict[str, object], *, artifact_id: str, raw: bytes
) -> SubmissionArtifactReference:
    event = result["event"]
    assert isinstance(event, dict)
    payload = event["payload"]
    assert isinstance(payload, dict)
    return SubmissionArtifactReference(
        artifact_id=artifact_id,
        manifest_sha256=payload["manifest_sha256"],
        content_sha256=_sha256(raw),
        accepting_event_id=event["event_id"],
    )


def _invoke_cli(capsys, argv: list[str]) -> tuple[int, dict[str, object]]:
    return_code = main(argv)
    captured = capsys.readouterr()
    assert captured.err == ""
    return return_code, json.loads(captured.out)


def _submission_record_cli(
    root: Path,
    capsys,
    *,
    kind: str,
    artifact_id: str,
    file_name: str,
    raw: bytes,
    number: int,
    request: ArtifactAcceptanceRequest | None = None,
) -> tuple[
    int,
    dict[str, object],
    ArtifactAcceptanceRequest,
    Path,
    Path,
]:
    input_path = _json_file(root, file_name, raw)
    accepted_request = request or request_for(
        root, artifact_id, file_name, raw, number, kind
    )
    request_path = _json_file(
        root,
        f"{artifact_id.replace('.', '-')}.request.json",
        accepted_request.model_dump(mode="json"),
    )
    command = "record"
    argv = [
        "submission",
        command,
        "--run-root",
        str(root),
        "--kind",
        kind,
        "--input",
        str(input_path),
        "--request",
        str(request_path),
    ]
    if kind == "submission-review-round":
        argv = [
            "submission",
            "review-import",
            "--run-root",
            str(root),
            "--input",
            str(input_path),
            "--request",
            str(request_path),
        ]
    elif kind == "submission-response":
        argv = [
            "submission",
            "response-record",
            "--run-root",
            str(root),
            "--input",
            str(input_path),
            "--request",
            str(request_path),
        ]
    result = _invoke_cli(capsys, argv)
    return (*result, accepted_request, request_path, input_path)


def _submission_qualify_confirmation_cli(
    root: Path,
    capsys,
    *,
    submission_id: str,
    subject_scope: str,
    subject_sha256: str,
    number: int,
    response_status: str | None = None,
) -> dict[str, object]:
    # The confirmation route consumes the existing parent request envelope;
    # its artifact fields are intentionally ignored by the gate service.
    raw = b"confirmation request witness"
    witness_path = root / f"confirmation-{number}.txt"
    witness_path.write_bytes(raw)
    request = request_for(
        root,
        f"artifact.confirmation.{number}",
        witness_path.name,
        raw,
        number,
        "confirmation-witness",
    )
    request_path = _json_file(
        root,
        f"confirmation-{number}.request.json",
        request.model_dump(mode="json"),
    )
    argv = [
        "submission",
        "qualify",
        "--run-root",
        str(root),
        "--request",
        str(request_path),
        "--scope",
        "confirmation",
        "--submission-id",
        submission_id,
        "--subject-scope",
        subject_scope,
        "--subject-sha256",
        subject_sha256,
    ]
    if response_status is not None:
        argv.extend(["--response-status", response_status])
    return _invoke_cli(capsys, argv)[1]


def _advance_to_review(root: Path, *, first_number: int) -> None:
    runtime = RuntimeCommandService(root)
    for offset, (transition_id, from_stage) in enumerate(
        (
            ("start", "initialized"),
            ("begin_work", "intake"),
            ("request_review", "work"),
        )
    ):
        state = replay_run(root)
        outcome = runtime.execute_transition(
            LifecycleTransitionRequest.model_validate(
                {
                    "schema_version": "1.0.0",
                    "run_id": RUN,
                    "occurred_at": "2026-09-21T12:00:00Z",
                    "event_id": f"evt-00000000-0000-4000-8000-{first_number + offset:012d}",
                    "command_id": f"cmd-00000000-0000-4000-8000-{first_number + offset:012d}",
                    "actor_id": "parent.runtime",
                    "actor_role": "parent_control_plane",
                    "expected_revision": state.revision,
                    "transition_id": transition_id,
                    "from_stage": from_stage,
                }
            )
        )
        assert outcome.accepted, outcome.rejection


def _record_scoped_approval(
    root: Path,
    *,
    gate_result: dict[str, object],
    subject_sha256: str,
    scope: str,
    decision_id: str,
    number: int,
) -> None:
    gate_result_body = gate_result["gate"]
    assert isinstance(gate_result_body, dict)
    event = gate_result_body["event"]
    assert isinstance(event, dict)
    decision_payload = event["payload"]
    assert isinstance(decision_payload, dict)
    gate_id = decision_payload["decision"]["gate_id"]
    state = RuntimeCommandService(root).read_state()
    gate = next(item for item in state.gates if item.gate_id == gate_id)
    authority = HumanAuthority(
        schema_version="arw.human-authority.v1",
        authority_id=f"authority.{decision_id}",
        authenticated_actor_id="author.user",
        accountable_role="operator",
        validated_by_actor_id="parent.runtime",
        allowed_decision_kinds=("approval",),
        allowed_gate_ids=(gate.gate_id,),
        allowed_scopes=(scope,),
        authenticated_at="2026-09-21T12:00:00Z",
        expires_at="2026-09-22T00:00:00Z",
        evidence_sha256=(gate.decision_sha256,),
    )
    authority_request = RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN,
            "occurred_at": "2026-09-21T12:10:00Z",
            "event_id": f"evt-00000000-0000-4000-8000-{number:012d}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012d}",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "expected_revision": state.accepted_revision,
        }
    )
    orchestration = OrchestrationService(
        root,
        adapter=DeterministicFakeAdapter({}),
    )
    accepted_authority = orchestration.record_human_authority(
        authority_request, authority
    )
    assert accepted_authority.accepted, accepted_authority.rejection
    decision = HumanDecisionRecord(
        schema_version="arw.human-decision.v1",
        decision_id=decision_id,
        decision_kind="approval",
        gate_id=gate.gate_id,
        subject_sha256=subject_sha256,
        evidence_sha256=(gate.decision_sha256, authority.authority_sha256),
        applicable_transition="complete",
        accountable_actor_id="author.user",
        accountable_role="operator",
        scope=scope,
        rationale="Fixture-labelled accountable author approval for the exact subject.",
        prior_verdict_sha256=gate.decision_sha256,
        authority_sha256=authority.authority_sha256,
        supersedes_decision_id=None,
    )
    decision_request = authority_request.model_copy(
        update={
            "event_id": f"evt-00000000-0000-4000-8000-{number + 1:012d}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number + 1:012d}",
            "expected_revision": accepted_authority.state.accepted_revision,
        }
    )
    accepted_decision = orchestration.record_human_decision(
        decision_request, decision
    )
    assert accepted_decision.accepted, accepted_decision.rejection


def _build_packet(
    *,
    policy_ref: SubmissionArtifactReference,
    manuscript_ref: SubmissionArtifactReference,
    title_ref: SubmissionArtifactReference,
    figure_ref: SubmissionArtifactReference,
    submission_id: str,
    round_number: int = 0,
    confirmed_funding: bool = False,
) -> SubmissionPacket:
    not_applicable = DeclarationField(
        status="not_applicable", rationale="not applicable in this fixture"
    )
    funding = (
        DeclarationField(
            status="confirmed",
            value="fixture funding statement",
            human_decision_id=f"decision.{submission_id}.funding",
        )
        if confirmed_funding
        else not_applicable
    )
    return SubmissionPacket(
        schema_version="arw.submission-packet.v1",
        project_id="project.demo",
        run_id=RUN,
        submission_id=submission_id,
        packet_version=1,
        journal_id="journal.demo",
        journal_name="Journal",
        article_type="research-article",
        round_number=round_number,
        manuscript_id=f"manuscript.{submission_id}",
        manuscript_version="v1",
        manuscript=manuscript_ref,
        components=(
            {
                "component_id": f"component.{submission_id}.manuscript",
                "role": "main_manuscript",
                "artifact": manuscript_ref,
                "media_type": "text/markdown",
                "byte_length": 5,
            },
            {
                "component_id": f"component.{submission_id}.title",
                "role": "title_page",
                "artifact": title_ref,
                "media_type": "text/markdown",
                "byte_length": 5,
            },
            {
                "component_id": f"component.{submission_id}.figure",
                "role": "figure",
                "artifact": figure_ref,
                "media_type": "image/png",
                "byte_length": 5,
            },
        ),
        policy_snapshot=policy_ref,
        authors=(
            {
                "person_id": f"person.{submission_id}",
                "display_name": "Fixture Author",
                "order": 0,
                "corresponding": True,
                "contributions": ("conceptualization",),
                "funding": funding,
                "conflicts": not_applicable,
                "ethics": not_applicable,
                "data": not_applicable,
                "ai_use": not_applicable,
            },
        ),
        created_at="2026-09-21T12:00:00Z",
        created_by="parent.runtime",
    )


def _admit_cli_packet(
    root: Path,
    capsys,
    *,
    submission_id: str,
    round_number: int = 0,
    confirmed_funding: bool = False,
    record_packet: bool = True,
    number: int,
) -> tuple[SubmissionPacket, SubmissionArtifactReference | None, dict[str, object]]:
    source_ref = accept_file(
        root,
        f"artifact.policy-source.{number}",
        f"policy-source-{number}.txt",
        b"journal policy source",
        number,
        "source",
    )
    policy = JournalRequirementsSnapshot(
        schema_version="arw.journal-requirements.v1",
        snapshot_id=f"snapshot.{submission_id}",
        journal_id="journal.demo",
        journal_name="Journal",
        article_type="research-article",
        official_source_urls=("https://journal.example/policy",),
        retained_source_artifacts=(source_ref,),
        captured_at="2026-09-21T12:00:00Z",
        verified_at="2026-09-21T12:00:00Z",
        requirements=(),
        verifier_id="parent.runtime",
    )
    policy_raw = canonical_json_bytes(policy.model_dump(mode="json"))
    policy_rc, policy_result, _, _, _ = _submission_record_cli(
        root,
        capsys,
        kind="journal-requirements",
        artifact_id=f"artifact.policy.{submission_id}",
        file_name=f"policy-{submission_id}.json",
        raw=policy_raw,
        number=number + 1,
    )
    assert policy_rc == 0
    policy_ref = _reference_from_result(
        policy_result,
        artifact_id=f"artifact.policy.{submission_id}",
        raw=policy_raw,
    )
    manuscript_ref = accept_file(
        root,
        f"artifact.manuscript.{submission_id}",
        f"manuscript-{submission_id}.md",
        b"draft",
        number + 2,
        "manuscript",
    )
    title_ref = accept_file(
        root,
        f"artifact.title.{submission_id}",
        f"title-{submission_id}.md",
        b"title",
        number + 3,
        "title-page",
    )
    figure_ref = accept_file(
        root,
        f"artifact.figure.{submission_id}",
        f"figure-{submission_id}.png",
        b"figure",
        number + 4,
        "figure",
    )
    packet = _build_packet(
        policy_ref=policy_ref,
        manuscript_ref=manuscript_ref,
        title_ref=title_ref,
        figure_ref=figure_ref,
        submission_id=submission_id,
        round_number=round_number,
        confirmed_funding=confirmed_funding,
    )
    if not record_packet:
        return packet, None, {
            "manuscript": manuscript_ref,
            "title": title_ref,
            "figure": figure_ref,
        }
    packet_raw = canonical_json_bytes(packet.model_dump(mode="json"))
    packet_rc, packet_result, _, _, _ = _submission_record_cli(
        root,
        capsys,
        kind="submission-packet",
        artifact_id=f"artifact.packet.{submission_id}",
        file_name=f"packet-{submission_id}.json",
        raw=packet_raw,
        number=number + 5,
    )
    if packet_rc != 0:
        packet_request = request_for(
            root,
            f"artifact.packet.{submission_id}",
            f"packet-{submission_id}.json",
            packet_raw,
            number + 5,
            "submission-packet",
        )
        direct = SubmissionWorkflowService(root).record(
            "submission-packet", packet_raw, packet_request
        )
        raise AssertionError((packet_result, direct))
    assert packet_result["accepted"] is True, packet_result
    packet_ref = _reference_from_result(
        packet_result,
        artifact_id=f"artifact.packet.{submission_id}",
        raw=packet_raw,
    )
    return packet, packet_ref, {
        "manuscript": manuscript_ref,
        "title": title_ref,
        "figure": figure_ref,
    }


def _make_report(
    root: Path,
    *,
    packet: SubmissionPacket,
    capsys,
    number: int,
    include_response_coverage: bool = False,
) -> SubmissionCheckReport:
    status = SubmissionWorkflowService(root).check(packet.submission_id)
    check_kinds = [
        "component_integrity",
        "journal_requirements",
        "author_declarations",
        "claim_citation_coverage",
        "scientific_review",
    ]
    if include_response_coverage:
        check_kinds.append("review_response_coverage")
    evidence = [
        accept_file(
            root,
            f"artifact.cli-evidence.{number + index}",
            f"cli-evidence-{number + index}.txt",
            b"fixture-labelled strict evidence",
            number + index,
            "audit",
        )
        for index in range(len(check_kinds))
    ]
    return SubmissionCheckReport(
        schema_version="arw.submission-check-report.v1",
        report_id=f"report.cli.{packet.submission_id}.{number}",
        submission_id=packet.submission_id,
        packet_manifest_sha256=status["packet_manifest_sha256"],
        input_fingerprint=status["readiness"]["input_fingerprint"],
        evaluated_at="2026-09-21T12:30:00Z",
        valid_until="2026-09-22T00:00:00Z",
        checks=tuple(
            SubmissionCheck(
                check_id=f"check.cli.{packet.submission_id}.{kind}",
                check_kind=kind,
                applicability="REQUIRED",
                status="PASS",
                source_identity="fixture.strict",
                source_version="v1",
                input_sha256=status["readiness"]["input_fingerprint"],
                output_sha256="a" * 64,
                coverage="fixture-labelled exact evidence",
                evidence=(evidence[index],),
                evaluated_at="2026-09-21T12:30:00Z",
                valid_until="2026-09-22T00:00:00Z",
            )
            for index, kind in enumerate(check_kinds)
        ),
        readiness="READY_FOR_HUMAN_SUBMIT",
    )


def test_a1_first_submission_cli_reaches_bound_human_boundary_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.syspath_prepend(str(SUBMISSION_EXTENSION))
    monkeypatch.setattr(submission_module, "_now", lambda: "2026-09-21T12:45:00Z")

    def fail_network(*_args, **_kwargs):
        raise AssertionError("submission acceptance must not perform network IO")

    monkeypatch.setattr(socket, "socket", fail_network)
    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)

    root = seed_run(tmp_path)
    _advance_to_review(root, first_number=2200)
    packet, _packet_ref, _artifacts = _admit_cli_packet(
        root,
        capsys,
        submission_id="submission.a1",
        confirmed_funding=True,
        record_packet=False,
        number=2205,
    )
    missing_title = SubmissionArtifactReference(
        artifact_id="artifact.missing-title",
        manifest_sha256="a" * 64,
        content_sha256="b" * 64,
        accepting_event_id="evt-00000000-0000-4000-8000-000000009999",
    )
    bad_packet = packet.model_copy(
        update={
            "components": tuple(
                item.model_copy(update={"artifact": missing_title})
                if item.role == "title_page"
                else item
                for item in packet.components
            )
        }
    )
    bad_raw = canonical_json_bytes(bad_packet.model_dump(mode="json"))
    before_rejection = replay_run(root).revision
    bad_rc, bad_result, _, _, _ = _submission_record_cli(
        root,
        capsys,
        kind="submission-packet",
        artifact_id="artifact.packet.a1.bad",
        file_name="packet-a1-bad.json",
        raw=bad_raw,
        number=2211,
    )
    assert bad_rc == 65
    assert bad_result.get("accepted") is False, bad_result
    assert bad_result["rejection"]["code"] == "submission-reference-unknown"
    assert replay_run(root).revision == before_rejection

    packet_raw = canonical_json_bytes(packet.model_dump(mode="json"))
    packet_rc, packet_result, _, _, _ = _submission_record_cli(
        root,
        capsys,
        kind="submission-packet",
        artifact_id="artifact.packet.a1",
        file_name="packet-a1.json",
        raw=packet_raw,
        number=2212,
    )
    assert packet_rc == 0 and packet_result["accepted"] is True

    blocked = SubmissionWorkflowService(root).check(packet.submission_id)
    assert blocked["readiness"]["readiness"] == "BLOCKED"
    assert "author_decision_missing" in blocked["readiness"]["reason_codes"]

    scope = f"submission:{packet.submission_id}:author:{packet.authors[0].person_id}:funding"
    subject = declaration_subject_sha256(
        packet.submission_id,
        packet.authors[0].person_id,
        "funding",
        packet.authors[0].funding,
    )
    confirmation = _submission_qualify_confirmation_cli(
        root,
        capsys,
        submission_id=packet.submission_id,
        subject_scope=scope,
        subject_sha256=subject,
        number=2212,
    )
    assert confirmation["gate"]["event"]["payload"]["decision"]["verdict"] == "PASS"
    _record_scoped_approval(
        root,
        gate_result=confirmation,
        subject_sha256=subject,
        scope=scope,
        decision_id="decision.submission.a1.funding",
        number=2213,
    )

    report = _make_report(root, packet=packet, capsys=capsys, number=2215)
    report_raw = canonical_json_bytes(report.model_dump(mode="json"))
    report_rc, report_result, _, _, _ = _submission_record_cli(
        root,
        capsys,
        kind="submission-check-report",
        artifact_id="artifact.report.a1",
        file_name="report-a1.json",
        raw=report_raw,
        number=2221,
    )
    assert report_rc == 0 and report_result["accepted"] is True

    qualified = _invoke_cli(
        capsys,
        [
            "submission",
            "qualify",
            "--run-root",
            str(root),
            "--input",
            str(root / "report-a1.json"),
            "--request",
            str(root / "artifact-report-a1.request.json"),
            "--scope",
            "readiness",
        ],
    )[1]
    assert qualified["gate"]["event"]["payload"]["decision"]["verdict"] == "PASS"
    aggregate_gate_id = qualified["gate"]["event"]["payload"]["decision"]["gate_id"]
    assert aggregate_gate_id.startswith("gate.submission.submission.a1.")
    report_fingerprint = report.input_fingerprint
    _record_scoped_approval(
        root,
        gate_result=qualified,
        subject_sha256=report_fingerprint,
        scope=f"submission:{packet.submission_id}:ready",
        decision_id="decision.submission.a1.ready",
        number=2222,
    )
    ready_request = LifecycleTransitionRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN,
            "occurred_at": "2026-09-21T12:40:00Z",
            "event_id": "evt-00000000-0000-4000-8000-000000002224",
            "command_id": "cmd-00000000-0000-4000-8000-000000002224",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "expected_revision": replay_run(root).revision,
            "transition_id": "complete",
            "from_stage": "review",
        }
    )
    ready_request_path = _json_file(
        root, "ready-a1.request.json", ready_request.model_dump(mode="json")
    )
    ready_rc, ready_result = _invoke_cli(
        capsys,
        [
            "submission",
            "ready",
            "--run-root",
            str(root),
            "--submission-id",
            packet.submission_id,
            "--request",
            str(ready_request_path),
        ],
    )
    assert ready_rc == 0 and ready_result["accepted"] is True

    status_rc, status = _invoke_cli(
        capsys,
        [
            "submission",
            "status",
            "--run-root",
            str(root),
            "--submission-id",
            packet.submission_id,
        ],
    )
    assert status_rc == 0
    assert status["readiness"]["readiness"] == "READY_FOR_HUMAN_SUBMIT"
    assert status["qualification"]["aggregate_gate"]["verdict"] == "PASS"
    assert status["qualification"]["final_human_approval"]["decision_id"] == "decision.submission.a1.ready"
    assert status["external_observation"] is None


def test_a2_cli_revision_round_retries_import_and_closes_every_leaf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.syspath_prepend(str(SUBMISSION_EXTENSION))
    root = seed_run(tmp_path)
    _advance_to_review(root, first_number=2300)
    packet, _packet_ref, _artifacts = _admit_cli_packet(
        root,
        capsys,
        submission_id="submission.a2",
        round_number=1,
        number=2305,
    )
    letter_ref = accept_file(
        root,
        "artifact.editor-letter.a2",
        "editor-letter-a2.txt",
        b"1. Clarify method. 2. Explain limitation.",
        2311,
        "review-letter",
    )
    locators = (
        ReviewLocator(locator_type="paragraph", value="methods.p1"),
        ReviewLocator(locator_type="paragraph", value="limitations.p1"),
    )
    comments = tuple(
        ReviewComment(
            comment_id=review_comment_identity(
                packet.submission_id, 1, letter_ref.manifest_sha256, locator
            ),
            submission_id=packet.submission_id,
            round_number=1,
            source_locator=locator,
            quote=quote,
            original_order=index,
        )
        for index, (locator, quote) in enumerate(
            zip(locators, ("Clarify method.", "Explain limitation."), strict=True)
        )
    )
    review_round = ReviewRound(
        schema_version="arw.submission-review-round.v1",
        round_id="round.a2",
        submission_id=packet.submission_id,
        round_number=1,
        source_letter=letter_ref,
        comments=comments,
        imported_at="2026-09-21T12:20:00Z",
        imported_by="parent.runtime",
    )
    round_raw = canonical_json_bytes(review_round.model_dump(mode="json"))
    first_rc, first_result, round_request, round_request_path, round_input_path = _submission_record_cli(
        root,
        capsys,
        kind="submission-review-round",
        artifact_id="artifact.round.a2",
        file_name="round-a2.json",
        raw=round_raw,
        number=2312,
    )
    if first_rc != 0:
        direct = SubmissionWorkflowService(root).record(
            "submission-review-round", round_raw, round_request
        )
        raise AssertionError((first_result, direct))
    assert first_result["accepted"] is True, first_result
    second_rc, second_result = _invoke_cli(
        capsys,
        [
            "submission",
            "review-import",
            "--run-root",
            str(root),
            "--input",
            str(round_input_path),
            "--request",
            str(round_request_path),
        ],
    )
    assert second_rc == 0 and second_result["accepted"] is True
    assert second_result["event"]["event_id"] == first_result["event"]["event_id"]
    assert replay_run(root).revision == first_result["state"]["accepted_revision"]

    revision_evidence = accept_file(
        root,
        "artifact.revision-evidence.a2",
        "revision-evidence-a2.txt",
        b"bound revision evidence",
        2313,
        "revision-evidence",
    )
    proposed = []
    for index, (comment, text, rationale, evidence, locations) in enumerate(
        (
            (
                comments[0],
                "We retain the registered method and clarify the limitation.",
                "The requested method change would invalidate the registered analysis.",
                (),
                (),
            ),
            (
                comments[1],
                "We added the requested limitation explanation.",
                None,
                (revision_evidence,),
                (
                    ReviewLocator(
                        locator_type="paragraph",
                        value="limitations.p2",
                        manuscript_sha256=packet.manuscript.content_sha256,
                    ),
                ),
            ),
        )
    ):
        response = ReviewResponse(
            schema_version="arw.submission-response.v1",
            response_id=f"response.a2.proposed.{index}",
            submission_id=packet.submission_id,
            round_number=1,
            comment_id=comment.comment_id,
            status="proposed",
            response_text=text,
            rationale=rationale,
            evidence=evidence,
            locations=locations,
        )
        raw = canonical_json_bytes(response.model_dump(mode="json"))
        rc, result, _, _, _ = _submission_record_cli(
            root,
            capsys,
            kind="submission-response",
            artifact_id=f"artifact.response.a2.proposed.{index}",
            file_name=f"response-a2-proposed-{index}.json",
            raw=raw,
            number=2314 + index,
        )
        assert rc == 0 and result["accepted"] is True
        proposed.append(response)

    final_statuses = ("not_adopted", "addressed")
    for index, (response, final_status) in enumerate(zip(proposed, final_statuses, strict=True)):
        scope = f"submission:{packet.submission_id}:response:{response.comment_id}"
        subject = response_subject_sha256(response)
        confirmation = _submission_qualify_confirmation_cli(
            root,
            capsys,
            submission_id=packet.submission_id,
            subject_scope=scope,
            subject_sha256=subject,
            response_status=final_status,
            number=2320 + index * 4,
        )
        assert confirmation["gate"]["event"]["payload"]["decision"]["verdict"] == "PASS"
        decision_id = f"decision.a2.response.{index}"
        _record_scoped_approval(
            root,
            gate_result=confirmation,
            subject_sha256=subject,
            scope=scope,
            decision_id=decision_id,
            number=2321 + index * 4,
        )
        final = response.model_copy(
            update={
                "response_id": f"response.a2.final.{index}",
                "status": final_status,
                "predecessor_response_id": response.response_id,
                "author_decision_id": decision_id,
            }
        )
        raw = canonical_json_bytes(final.model_dump(mode="json"))
        rc, result, final_request, _, _ = _submission_record_cli(
            root,
            capsys,
            kind="submission-response",
            artifact_id=f"artifact.response.a2.final.{index}",
            file_name=f"response-a2-final-{index}.json",
            raw=raw,
            number=2323 + index * 4,
        )
        if rc != 0:
            direct = SubmissionWorkflowService(root).record(
                "submission-response", raw, final_request
            )
            raise AssertionError((result, direct))
        assert result["accepted"] is True

    status = SubmissionWorkflowService(root).check(packet.submission_id)
    assert "review_responses_incomplete" not in status["readiness"]["reason_codes"]
    assert "review_comments_unresolved" not in status["readiness"]["reason_codes"]
    report = _make_report(
        root,
        packet=packet,
        capsys=capsys,
        number=2330,
        include_response_coverage=True,
    )
    report_raw = canonical_json_bytes(report.model_dump(mode="json"))
    report_rc, report_result, _, report_request_path, report_input_path = _submission_record_cli(
        root,
        capsys,
        kind="submission-check-report",
        artifact_id="artifact.report.a2",
        file_name="report-a2.json",
        raw=report_raw,
        number=2340,
    )
    assert report_rc == 0 and report_result["accepted"] is True
    qualified_rc, qualified = _invoke_cli(
        capsys,
        [
            "submission",
            "qualify",
            "--run-root",
            str(root),
            "--input",
            str(report_input_path),
            "--request",
            str(report_request_path),
            "--scope",
            "readiness",
        ],
    )
    assert qualified_rc == 0
    assert qualified["gate"]["event"]["payload"]["decision"]["verdict"] == "PASS"
    assert qualified["final_submit"] == "human_only"


@pytest.mark.parametrize(
    "fault_id",
    (
        "phase7.canonical-write-before-commit",
        "phase7.hard-termination",
        "phase7.journal-fsync",
    ),
)
def test_a4_artifact_boundaries_are_retryable_after_fault_injection(
    tmp_path: Path, fault_id: str
) -> None:
    root = seed_run(tmp_path)
    raw = b"fault-injected submission source"
    path = root / "fault-source.txt"
    path.write_bytes(raw)
    request = request_for(
        root,
        "artifact.fault-source",
        path.name,
        raw,
        2400,
        "source",
    )
    request_path = tmp_path / "fault-request.json"
    request_path.write_bytes(canonical_json_bytes(request.model_dump(mode="json")))
    child_environment = os.environ.copy()
    child_environment.update(
        {
            "ARW_TEST_MODE": "1",
            "ARW_TEST_FAULT_ID": fault_id,
        }
    )
    code = (
        "from pathlib import Path; "
        "from arw.kernel.execution.runtime import RuntimeCommandService; "
        "from arw.kernel.state.models import ArtifactAcceptanceRequest; "
        "import json; "
        f"root=Path({str(root)!r}); "
        f"request=ArtifactAcceptanceRequest.model_validate(json.loads(Path({str(request_path)!r}).read_text())); "
        "RuntimeCommandService(root).accept_artifact(request)"
    )
    crashed = subprocess.run(
        [sys.executable, "-c", code],
        env=child_environment,
        capture_output=True,
        check=False,
    )
    if fault_id == "phase7.hard-termination":
        assert crashed.returncode == -9
    else:
        assert crashed.returncode != 0
    assert not any(
        event.event_type == "artifact.accepted"
        for event in replay_run(root).events
    ) or fault_id == "phase7.journal-fsync"

    retry_environment = os.environ.copy()
    retry_environment.pop("ARW_TEST_MODE", None)
    retry_environment.pop("ARW_TEST_FAULT_ID", None)
    retry = subprocess.run(
        [sys.executable, "-c", code],
        env=retry_environment,
        capture_output=True,
        check=False,
    )
    assert retry.returncode == 0, retry.stderr.decode()
    replayed = replay_run(root)
    assert sum(event.command_id == request.command_id for event in replayed.events) == 1


def test_a4_reused_command_with_changed_payload_conflicts_without_new_event(
    tmp_path: Path,
) -> None:
    root = seed_run(tmp_path)
    source_ref = accept_file(
        root,
        "artifact.conflict-source",
        "conflict-source.txt",
        b"policy source",
        2450,
        "source",
    )
    policy = JournalRequirementsSnapshot(
        schema_version="arw.journal-requirements.v1",
        snapshot_id="snapshot.conflict",
        journal_id="journal.demo",
        journal_name="Journal",
        article_type="research-article",
        official_source_urls=("https://journal.example/policy",),
        retained_source_artifacts=(source_ref,),
        captured_at="2026-09-21T12:00:00Z",
        verified_at="2026-09-21T12:00:00Z",
        requirements=(),
        verifier_id="parent.runtime",
    )
    raw = canonical_json_bytes(policy.model_dump(mode="json"))
    path = root / "conflict-policy.json"
    path.write_bytes(raw)
    request = request_for(
        root,
        "artifact.conflict-policy",
        path.name,
        raw,
        2451,
        "journal-requirements",
    )
    service = SubmissionWorkflowService(root)
    first = service.record("journal-requirements", raw, request)
    assert first["accepted"] is True
    before_revision = replay_run(root).revision
    changed = policy.model_copy(update={"journal_name": "Changed Journal"})
    changed_raw = canonical_json_bytes(changed.model_dump(mode="json"))
    path.write_bytes(changed_raw)
    changed_request = request.model_copy(update={"content_sha256": _sha256(changed_raw)})
    conflict = service.record("journal-requirements", changed_raw, changed_request)
    assert conflict["accepted"] is False
    assert conflict["rejection"]["code"] == "duplicate-command-conflict"
    assert replay_run(root).revision == before_revision


def test_a4_concurrent_packet_successors_have_one_parent_owned_winner(
    tmp_path: Path, capsys
) -> None:
    root = seed_run(tmp_path)
    packet, packet_ref, _artifacts = _admit_cli_packet(
        root,
        capsys,
        submission_id="submission.concurrent",
        number=2480,
    )
    assert packet_ref is not None
    successors = (
        packet.model_copy(
            update={
                "packet_version": 2,
                "predecessor_manifest_sha256": packet_ref.manifest_sha256,
                "manuscript_version": "v2-a",
            }
        ),
        packet.model_copy(
            update={
                "packet_version": 2,
                "predecessor_manifest_sha256": packet_ref.manifest_sha256,
                "manuscript_version": "v2-b",
            }
        ),
    )
    requests = []
    for index, successor in enumerate(successors):
        raw = canonical_json_bytes(successor.model_dump(mode="json"))
        file_name = f"concurrent-packet-{index}.json"
        (root / file_name).write_bytes(raw)
        requests.append(
            request_for(
                root,
                f"artifact.concurrent.{index}",
                file_name,
                raw,
                2486 + index,
                "submission-packet",
            )
        )

    def accept(request: ArtifactAcceptanceRequest):
        return RuntimeCommandService(root).accept_artifact(request)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(accept, requests))
    assert sum(item.accepted for item in outcomes) == 1
    loser = next(item for item in outcomes if not item.accepted)
    assert loser.rejection.code in {"stale-revision", "submission-predecessor-stale"}
    current = SubmissionWorkflowService(root).check(packet.submission_id)
    assert current["packet"]["packet_version"] == 2


def test_a5_projection_and_advisory_mutations_do_not_change_canonical_status(
    tmp_path: Path, capsys
) -> None:
    root = seed_run(tmp_path)
    packet, _packet_ref, _artifacts = _admit_cli_packet(
        root,
        capsys,
        submission_id="submission.a5",
        number=2500,
    )
    before = SubmissionWorkflowService(root).check(packet.submission_id)
    (root / "submission-projection.sqlite").write_bytes(b"forged PASS")
    (root / "semantica-cache.sqlite").write_bytes(b"forged PASS")
    (root / "memory-approval.json").write_text(
        '{"approved":true,"actor":"memory"}', encoding="utf-8"
    )
    after = SubmissionWorkflowService(root).check(packet.submission_id)
    assert after == before
    assert after["readiness"]["readiness"] == "BLOCKED"
    assert not any(
        item["kind"] == "memory-approval" for item in after["accepted_artifacts"]
    )


def test_a5_forged_human_authority_cannot_become_a_submission_decision(
    tmp_path: Path, capsys
) -> None:
    root = seed_run(tmp_path)
    packet, _packet_ref, _artifacts = _admit_cli_packet(
        root,
        capsys,
        submission_id="submission.a5.authority",
        number=2550,
    )
    scope = (
        f"submission:{packet.submission_id}:author:{packet.authors[0].person_id}:funding"
    )
    subject = declaration_subject_sha256(
        packet.submission_id,
        packet.authors[0].person_id,
        "funding",
        packet.authors[0].funding,
    )
    qualification = _submission_qualify_confirmation_cli(
        root,
        capsys,
        submission_id=packet.submission_id,
        subject_scope=scope,
        subject_sha256=subject,
        number=2556,
    )
    gate_id = qualification["gate"]["event"]["payload"]["decision"]["gate_id"]
    state = RuntimeCommandService(root).read_state()
    gate = next(item for item in state.gates if item.gate_id == gate_id)
    forged = HumanDecisionRecord(
        schema_version="arw.human-decision.v1",
        decision_id="decision.a5.forged",
        decision_kind="approval",
        gate_id=gate.gate_id,
        subject_sha256=subject,
        evidence_sha256=(gate.decision_sha256,),
        applicable_transition="complete",
        accountable_actor_id="attacker",
        accountable_role="operator",
        scope=scope,
        rationale="forged authority claim",
        prior_verdict_sha256=gate.decision_sha256,
        authority_sha256="f" * 64,
        supersedes_decision_id=None,
    )
    request = RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN,
            "occurred_at": "2026-09-21T12:20:00Z",
            "event_id": "evt-00000000-0000-4000-8000-000000002557",
            "command_id": "cmd-00000000-0000-4000-8000-000000002557",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "expected_revision": state.accepted_revision,
        }
    )
    outcome = OrchestrationService(
        root,
        adapter=DeterministicFakeAdapter({}),
    ).record_human_decision(request, forged)
    assert outcome.accepted is False
    assert outcome.rejection.code == "authority-unknown"
    assert not any(
        item.decision_id == forged.decision_id
        for item in RuntimeCommandService(root).read_state().human_decision_history
    )


def test_a6_record_result_is_attributed_and_never_submits_or_calls_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.syspath_prepend(str(SUBMISSION_EXTENSION))

    def fail_network(*_args, **_kwargs):
        raise AssertionError("record-result must not perform external IO")

    monkeypatch.setattr(socket, "socket", fail_network)
    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(urllib.request, "urlopen", fail_network)

    root = seed_run(tmp_path)
    packet, packet_ref, _artifacts = _admit_cli_packet(
        root,
        capsys,
        submission_id="submission.a6",
        number=2600,
    )
    assert packet_ref is not None
    observation = SubmissionResultObservation(
        schema_version="arw.submission-result-observation.v1",
        observation_id="observation.a6.submitted",
        submission_id=packet.submission_id,
        packet_manifest_sha256=packet_ref.manifest_sha256,
        state="submitted",
        attribution="user_confirmation",
        recorded_at="2026-09-21T12:30:00Z",
        deviation_codes=("local_readiness_blocked",),
    )
    observation_raw = canonical_json_bytes(observation.model_dump(mode="json"))
    observation_path = _json_file(root, "observation-a6.json", observation_raw)
    observation_request = request_for(
        root,
        "artifact.observation.a6.submitted",
        observation_path.name,
        observation_raw,
        2606,
        "submission-result-observation",
    )
    request_path = _json_file(
        root, "observation-a6.request.json", observation_request.model_dump(mode="json")
    )
    record_rc, record_result = _invoke_cli(
        capsys,
        [
            "submission",
            "record-result",
            "--run-root",
            str(root),
            "--input",
            str(observation_path),
            "--request",
            str(request_path),
        ],
    )
    assert record_rc == 0 and record_result["accepted"] is True
    status_rc, status = _invoke_cli(
        capsys,
        [
            "submission",
            "status",
            "--run-root",
            str(root),
            "--submission-id",
            packet.submission_id,
        ],
    )
    assert status_rc == 0
    assert status["external_observation"]["state"] == "submitted"
    assert status["external_observation"]["attribution"] == "user_confirmation"
    assert status["external_observation"]["deviation_codes"] == [
        "local_readiness_blocked"
    ]
    assert status["readiness"]["readiness"] == "BLOCKED"

    draft = observation.model_copy(
        update={
            "observation_id": "observation.a6.draft",
            "state": "awaiting_human_submit",
            "recorded_at": "2026-09-21T12:40:00Z",
            "deviation_codes": (),
        }
    )
    draft_raw = canonical_json_bytes(draft.model_dump(mode="json"))
    draft_path = _json_file(root, "observation-a6-draft.json", draft_raw)
    draft_request = request_for(
        root,
        "artifact.observation.a6.draft",
        draft_path.name,
        draft_raw,
        2607,
        "submission-result-observation",
    )
    draft_request_path = _json_file(
        root, "observation-a6-draft.request.json", draft_request.model_dump(mode="json")
    )
    draft_rc, draft_result = _invoke_cli(
        capsys,
        [
            "submission",
            "record-result",
            "--run-root",
            str(root),
            "--input",
            str(draft_path),
            "--request",
            str(draft_request_path),
        ],
    )
    assert draft_rc == 0 and draft_result["accepted"] is True
    latest_rc, latest = _invoke_cli(
        capsys,
        [
            "submission",
            "status",
            "--run-root",
            str(root),
            "--submission-id",
            packet.submission_id,
        ],
    )
    assert latest_rc == 0
    assert latest["external_observation"]["state"] == "awaiting_human_submit"
    assert "submit" not in {
        item
        for item in latest["qualification"].values()
        if isinstance(item, str)
    }


def test_a7_security_rejection_is_bounded_and_qualification_axes_stay_independent(
    tmp_path: Path, capsys
) -> None:
    root = seed_run(tmp_path)
    oversized = root / "oversized.json"
    oversized.write_bytes(b"{" + b"x" * (256 * 1024) + b"}")
    rc, result = _invoke_cli(
        capsys,
        [
            "submission",
            "prepare",
            "--run-root",
            str(root),
            "--kind",
            "journal-requirements",
            "--input",
            str(oversized),
        ],
    )
    assert rc == 65
    assert result["status"] == "rejected"
    assert "x" not in json.dumps(result)

    license_verdict = json.loads(
        (PROJECT_ROOT / "supply-chain/license-verdict.json").read_text(encoding="utf-8")
    )
    assert license_verdict["technical_qualification"] == "PASS"
    assert license_verdict["release_qualification"] == "BLOCKED"
    assert {
        item["license"]
        for item in license_verdict["components"]
        if item["component_id"] in {"academic-research-skills", "experiment-agent"}
    } == {"CC-BY-NC-4.0"}

    route = installed_route(blocked_reason="integration_inputs_incomplete")
    assert route.integration_status == "BLOCKED"
    assert route.release_qualification == "BLOCKED"


def test_rollback_disables_provider_but_preserves_historical_readers_and_bytes(
    tmp_path: Path, capsys
) -> None:
    root = seed_run(tmp_path)
    packet, _packet_ref, _artifacts = _admit_cli_packet(
        root,
        capsys,
        submission_id="submission.rollback",
        number=2700,
    )
    before = SubmissionWorkflowService(root).check(packet.submission_id)
    journal = root / "journal/segments/00000001.jsonl"
    journal_bytes = journal.read_bytes()
    manifest = root / "rollback-plugin.json"
    manifest.write_text(
        '{"interface":{"capabilities":[]}}\n', encoding="utf-8"
    )
    router = default_router(plugin_manifest=manifest)
    with pytest.raises(CapabilityUnavailable):
        router.resolve("submission.prepare")
    after = SubmissionWorkflowService(root).check(packet.submission_id)
    assert after == before
    assert journal.read_bytes() == journal_bytes
    assert replay_run(root).event_count == before["accepted_artifacts"][-1]["sequence"]
