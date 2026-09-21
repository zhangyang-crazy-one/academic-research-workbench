from __future__ import annotations

import hashlib
from pathlib import Path

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.execution.submission import (
    SubmissionWorkflowError,
    SubmissionWorkflowService,
)
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.state.models import (
    ArtifactAcceptanceRequest,
    InitRunRequest,
    RuntimeCommandRequest,
)
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
    review_comment_identity,
)

RUN = "run-00000000-0000-4000-8000-000000000951"


def seed_run(tmp_path: Path) -> Path:
    root = tmp_path / "run"
    root.mkdir()
    source = root / "source.txt"
    source.write_bytes(b"source")
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN,
                "occurred_at": "2026-09-21T12:00:00Z",
                "immutable_input": {
                    "path": "source.txt",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                },
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "workflow_definition_id": CORE_WORKFLOW.definition_id,
                "workflow_definition_sha256": CORE_WORKFLOW.sha256,
                "journal_layout": "segmented-v1",
                "capabilities": ["canonical-journal"],
                "event_id": "evt-00000000-0000-4000-8000-000000000951",
                "command_id": "cmd-00000000-0000-4000-8000-000000000951",
                "actor_id": "parent.runtime",
            }
        ),
    )
    return root


def submit_file(
    root: Path, artifact_id: str, name: str, content: bytes, number: int, kind: str
):
    path = root / name
    path.write_bytes(content)
    digest = hashlib.sha256(content).hexdigest()
    replay = replay_run(root)
    outcome = RuntimeCommandService(root).accept_artifact(
        ArtifactAcceptanceRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN,
                "occurred_at": "2026-09-21T12:01:00Z",
                "event_id": f"evt-00000000-0000-4000-8000-{number:012d}",
                "command_id": f"cmd-00000000-0000-4000-8000-{number:012d}",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
                "expected_revision": replay.revision,
                "artifact_id": artifact_id,
                "artifact_kind": kind,
                "media_type": "application/json" if name.endswith(".json") else "text/plain",
                "content_path": name,
                "content_sha256": digest,
                "base_revision": replay.revision,
                "consumed_sha256": [replay.last_event_sha256],
            }
        )
    )
    return outcome


def accept_file(root: Path, artifact_id: str, name: str, content: bytes, number: int, kind: str):
    outcome = submit_file(root, artifact_id, name, content, number, kind)
    assert outcome.accepted, outcome.rejection
    payload = outcome.event.payload
    digest = hashlib.sha256(content).hexdigest()
    return SubmissionArtifactReference(
        artifact_id=artifact_id,
        manifest_sha256=payload.manifest_sha256,
        content_sha256=digest,
        accepting_event_id=outcome.event.event_id,
    )


def request_for(root: Path, artifact_id: str, name: str, content: bytes, number: int, kind: str):
    replay = replay_run(root)
    return ArtifactAcceptanceRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN,
            "occurred_at": "2026-09-21T12:01:00Z",
            "event_id": f"evt-00000000-0000-4000-8000-{number:012d}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012d}",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "expected_revision": replay.revision,
            "artifact_id": artifact_id,
            "artifact_kind": kind,
            "media_type": "application/json" if name.endswith(".json") else "text/plain",
            "content_path": name,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "base_revision": replay.revision,
            "consumed_sha256": [replay.last_event_sha256],
        }
    )


def test_submission_packet_is_admitted_only_with_parent_accepted_references(tmp_path: Path) -> None:
    root = seed_run(tmp_path)
    source_ref = accept_file(root, "artifact.policy-source", "policy.txt", b"policy", 952, "source")
    policy = JournalRequirementsSnapshot(
        schema_version="arw.journal-requirements.v1",
        snapshot_id="snapshot.demo",
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
    policy_ref = accept_file(
        root,
        "artifact.policy",
        "policy.json",
        canonical_json_bytes(policy.model_dump(mode="json")),
        953,
        "journal-requirements",
    )
    manuscript_ref = accept_file(root, "artifact.manuscript", "manuscript.md", b"draft", 954, "manuscript")
    title_ref = accept_file(root, "artifact.title", "title.md", b"title", 955, "title-page")
    field = DeclarationField(status="confirmed", value="yes", human_decision_id="decision.author")
    packet = SubmissionPacket(
        schema_version="arw.submission-packet.v1",
        project_id="project.demo",
        run_id=RUN,
        submission_id="submission.demo",
        packet_version=1,
        journal_id="journal.demo",
        journal_name="Journal",
        article_type="research-article",
        round_number=0,
        manuscript_id="manuscript.demo",
        manuscript_version="v1",
        manuscript=manuscript_ref,
        components=(
            {
                "component_id": "component.manuscript",
                "role": "main_manuscript",
                "artifact": manuscript_ref,
                "media_type": "text/markdown",
                "byte_length": 5,
            },
            {
                "component_id": "component.title",
                "role": "title_page",
                "artifact": title_ref,
                "media_type": "text/markdown",
                "byte_length": 5,
            },
        ),
        policy_snapshot=policy_ref,
        authors=(
            {
                "person_id": "person.author",
                "display_name": "Author",
                "order": 0,
                "corresponding": True,
                "contributions": ("conceptualization",),
                "funding": field,
                "conflicts": field,
                "ethics": field,
                "data": field,
                "ai_use": field,
            },
        ),
        created_at="2026-09-21T12:00:00Z",
        created_by="parent.runtime",
    )
    packet_ref = accept_file(
        root,
        "artifact.packet",
        "packet.json",
        canonical_json_bytes(packet.model_dump(mode="json")),
        956,
        "submission-packet",
    )
    assert packet_ref.artifact_id == "artifact.packet"
    status = SubmissionWorkflowService(root).check("submission.demo")
    assert status["readiness"]["readiness"] == "BLOCKED"
    assert "check_not_checked:component_integrity" in status["readiness"]["reason_codes"]
    page = SubmissionWorkflowService(root).check("submission.demo", limit=1)
    assert page["next_cursor"] is None
    try:
        SubmissionWorkflowService(root).check("submission.demo", cursor="invalid", limit=1)
    except SubmissionWorkflowError as error:
        assert "cursor" in str(error)
    else:
        raise AssertionError("invalid submission cursor was accepted")
    observation = SubmissionResultObservation(
        schema_version="arw.submission-result-observation.v1",
        observation_id="observation.demo",
        submission_id="submission.demo",
        packet_manifest_sha256=packet_ref.manifest_sha256,
        state="submitted",
        attribution="user_confirmation",
        recorded_at="2026-09-21T12:02:00Z",
        deviation_codes=("local_readiness_blocked",),
    )
    result_ref = accept_file(
        root,
        "artifact.submission-result",
        "submission-result.json",
        canonical_json_bytes(observation.model_dump(mode="json")),
        957,
        "submission-result-observation",
    )
    assert result_ref.artifact_id == "artifact.submission-result"

    letter_ref = accept_file(root, "artifact.editor-letter", "editor-letter.txt", b"clarify", 958, "review-letter")
    locator = ReviewLocator(locator_type="paragraph", value="methods.p1")
    comment_id = review_comment_identity("submission.demo", 1, letter_ref.manifest_sha256, locator)
    round_value = ReviewRound(
        schema_version="arw.submission-review-round.v1",
        round_id="round.demo",
        submission_id="submission.demo",
        round_number=1,
        source_letter=letter_ref,
        comments=(ReviewComment(
            comment_id=comment_id,
            submission_id="submission.demo",
            round_number=1,
            source_locator=locator,
            quote="Please clarify the method.",
            original_order=0,
        ),),
        imported_at="2026-09-21T12:00:00Z",
        imported_by="parent.runtime",
    )
    accept_file(root, "artifact.review-round", "review-round.json", canonical_json_bytes(round_value.model_dump(mode="json")), 959, "submission-review-round")
    response = ReviewResponse(
        schema_version="arw.submission-response.v1",
        response_id="response.initial",
        submission_id="submission.demo",
        round_number=1,
        comment_id=comment_id,
        status="needs_author_confirmation",
        response_text="Awaiting author confirmation.",
    )
    accept_file(root, "artifact.response-initial", "response-initial.json", canonical_json_bytes(response.model_dump(mode="json")), 970, "submission-response")
    successor_without_predecessor = response.model_copy(update={"response_id": "response.successor"})
    stale_response = submit_file(
        root,
        "artifact.response-stale",
        "response-stale.json",
        canonical_json_bytes(successor_without_predecessor.model_dump(mode="json")),
        971,
        "submission-response",
    )
    assert not stale_response.accepted
    assert stale_response.rejection.code == "submission-response-predecessor-stale"
    page = SubmissionWorkflowService(root).check("submission.demo", limit=1)
    assert page["next_cursor"] is not None
    next_page = SubmissionWorkflowService(root).check(
        "submission.demo", cursor=page["next_cursor"], limit=1
    )
    assert next_page["ledger_head_sha256"] == page["ledger_head_sha256"]
    assert next_page["accepted_artifacts"][0]["sequence"] != page["accepted_artifacts"][0]["sequence"]
    observation = SubmissionResultObservation(
        schema_version="arw.submission-result-observation.v1",
        observation_id="observation.cursor-head",
        submission_id="submission.demo",
        packet_manifest_sha256=packet_ref.manifest_sha256,
        state="not_submitted",
        attribution="user_confirmation",
        recorded_at="2026-09-21T12:03:00Z",
    )
    accept_file(
        root,
        "artifact.cursor-head",
        "cursor-head.json",
        canonical_json_bytes(observation.model_dump(mode="json")),
        972,
        "submission-result-observation",
    )
    try:
        SubmissionWorkflowService(root).check(
            "submission.demo", cursor=page["next_cursor"], limit=1
        )
    except SubmissionWorkflowError as error:
        assert "cursor" in str(error)
    else:
        raise AssertionError("cursor was reused across a changed submission head")


def test_submission_packet_reference_tampering_is_rejected(tmp_path: Path) -> None:
    root = seed_run(tmp_path)
    raw = b"{}"
    (root / "packet.json").write_bytes(raw)
    replay = replay_run(root)
    outcome = RuntimeCommandService(root).accept_artifact(
        ArtifactAcceptanceRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN,
                "occurred_at": "2026-09-21T12:01:00Z",
                "event_id": "evt-00000000-0000-4000-8000-000000000957",
                "command_id": "cmd-00000000-0000-4000-8000-000000000957",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
                "expected_revision": replay.revision,
                "artifact_id": "artifact.bad-packet",
                "artifact_kind": "submission-packet",
                "media_type": "application/json",
                "content_path": "packet.json",
                "content_sha256": hashlib.sha256(raw).hexdigest(),
                "base_revision": replay.revision,
                "consumed_sha256": [replay.last_event_sha256],
            }
        )
    )
    assert not outcome.accepted
    assert outcome.rejection.code == "submission-contract-invalid"


def test_packet_successor_is_current_and_forks_are_rejected(tmp_path: Path) -> None:
    root = seed_run(tmp_path)
    source_ref = accept_file(root, "artifact.source", "source.md", b"source", 960, "source")
    policy = JournalRequirementsSnapshot(
        schema_version="arw.journal-requirements.v1",
        snapshot_id="snapshot.successor",
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
    policy_ref = accept_file(
        root, "artifact.policy-successor", "policy-successor.json",
        canonical_json_bytes(policy.model_dump(mode="json")), 961, "journal-requirements"
    )
    manuscript_ref = accept_file(root, "artifact.manuscript-successor", "manuscript-successor.md", b"draft", 962, "manuscript")
    title_ref = accept_file(root, "artifact.title-successor", "title-successor.md", b"title", 963, "title-page")
    field = DeclarationField(status="not_applicable", rationale="not required")
    packet = SubmissionPacket(
        schema_version="arw.submission-packet.v1",
        project_id="project.demo",
        run_id=RUN,
        submission_id="submission.successor",
        packet_version=1,
        journal_id="journal.demo",
        journal_name="Journal",
        article_type="research-article",
        round_number=0,
        manuscript_id="manuscript.demo",
        manuscript_version="v1",
        manuscript=manuscript_ref,
        components=(
            {"component_id": "component.manuscript-successor", "role": "main_manuscript", "artifact": manuscript_ref, "media_type": "text/markdown", "byte_length": 5},
            {"component_id": "component.title-successor", "role": "title_page", "artifact": title_ref, "media_type": "text/markdown", "byte_length": 5},
        ),
        policy_snapshot=policy_ref,
        authors=({
            "person_id": "person.author", "display_name": "Author", "order": 0, "corresponding": True,
            "contributions": ("conceptualization",), "funding": field, "conflicts": field,
            "ethics": field, "data": field, "ai_use": field,
        },),
        created_at="2026-09-21T12:00:00Z",
        created_by="parent.runtime",
    )
    first_ref = accept_file(root, "artifact.packet-successor-v1", "packet-successor-v1.json", canonical_json_bytes(packet.model_dump(mode="json")), 964, "submission-packet")
    second = packet.model_copy(update={"packet_version": 2, "predecessor_manifest_sha256": first_ref.manifest_sha256})
    second_ref = accept_file(root, "artifact.packet-successor-v2", "packet-successor-v2.json", canonical_json_bytes(second.model_dump(mode="json")), 965, "submission-packet")
    fork = packet.model_copy(update={"packet_version": 2, "predecessor_manifest_sha256": first_ref.manifest_sha256})
    fork_outcome = submit_file(root, "artifact.packet-successor-fork", "packet-successor-fork.json", canonical_json_bytes(fork.model_dump(mode="json")), 966, "submission-packet")
    assert second_ref.content_sha256 == hashlib.sha256(canonical_json_bytes(second.model_dump(mode="json"))).hexdigest()
    assert not fork_outcome.accepted
    assert fork_outcome.rejection.code == "submission-predecessor-stale"


def test_submission_record_exact_retry_reuses_one_artifact_event(tmp_path: Path) -> None:
    root = seed_run(tmp_path)
    source_ref = accept_file(root, "artifact.retry-source", "retry-source.txt", b"source", 980, "source")
    policy = JournalRequirementsSnapshot(
        schema_version="arw.journal-requirements.v1",
        snapshot_id="snapshot.retry",
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
    (root / "retry-policy.json").write_bytes(raw)
    replay = replay_run(root)
    request = ArtifactAcceptanceRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN,
            "occurred_at": "2026-09-21T12:01:00Z",
            "event_id": "evt-00000000-0000-4000-8000-000000000981",
            "command_id": "cmd-00000000-0000-4000-8000-000000000981",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "expected_revision": replay.revision,
            "artifact_id": "artifact.retry-policy",
            "artifact_kind": "journal-requirements",
            "media_type": "application/json",
            "content_path": "retry-policy.json",
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "base_revision": replay.revision,
            "consumed_sha256": [replay.last_event_sha256],
        }
    )
    service = SubmissionWorkflowService(root)
    first = service.record("journal-requirements", raw, request)
    second = service.record("journal-requirements", raw, request)
    assert first["accepted"] is True
    assert second["accepted"] is True
    assert second["event"]["event_id"] == first["event"]["event_id"]
    assert replay_run(root).revision == first["state"]["accepted_revision"]


def _admit_complete_initial_packet(root: Path) -> tuple[SubmissionPacket, SubmissionArtifactReference]:
    source_ref = accept_file(root, "artifact.qualify-source", "qualify-source.txt", b"source", 990, "source")
    policy = JournalRequirementsSnapshot(
        schema_version="arw.journal-requirements.v1",
        snapshot_id="snapshot.qualify",
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
    policy_ref = accept_file(
        root,
        "artifact.qualify-policy",
        "qualify-policy.json",
        canonical_json_bytes(policy.model_dump(mode="json")),
        991,
        "journal-requirements",
    )
    manuscript_ref = accept_file(root, "artifact.qualify-manuscript", "qualify-manuscript.md", b"draft", 992, "manuscript")
    title_ref = accept_file(root, "artifact.qualify-title", "qualify-title.md", b"title", 993, "title-page")
    field = DeclarationField(status="not_applicable", rationale="not required")
    packet = SubmissionPacket(
        schema_version="arw.submission-packet.v1",
        project_id="project.demo",
        run_id=RUN,
        submission_id="submission.qualify",
        packet_version=1,
        journal_id="journal.demo",
        journal_name="Journal",
        article_type="research-article",
        round_number=0,
        manuscript_id="manuscript.qualify",
        manuscript_version="v1",
        manuscript=manuscript_ref,
        components=(
            {"component_id": "component.qualify-manuscript", "role": "main_manuscript", "artifact": manuscript_ref, "media_type": "text/markdown", "byte_length": 5},
            {"component_id": "component.qualify-title", "role": "title_page", "artifact": title_ref, "media_type": "text/markdown", "byte_length": 5},
        ),
        policy_snapshot=policy_ref,
        authors=({
            "person_id": "person.qualify",
            "display_name": "Author",
            "order": 0,
            "corresponding": True,
            "contributions": ("conceptualization",),
            "funding": field,
            "conflicts": field,
            "ethics": field,
            "data": field,
            "ai_use": field,
        },),
        created_at="2026-09-21T12:00:00Z",
        created_by="parent.runtime",
    )
    packet_ref = accept_file(
        root,
        "artifact.qualify-packet",
        "qualify-packet.json",
        canonical_json_bytes(packet.model_dump(mode="json")),
        994,
        "submission-packet",
    )
    return packet, packet_ref


def test_qualify_retries_report_and_gate_without_duplicate_writes(tmp_path: Path) -> None:
    root = seed_run(tmp_path)
    packet, packet_ref = _admit_complete_initial_packet(root)
    evidence = tuple(
        accept_file(root, f"artifact.qualify-evidence-{index}", f"qualify-evidence-{index}.txt", b"evidence", 994 + index, "audit")
        for index in range(1, 6)
    )
    status = SubmissionWorkflowService(root).check(packet.submission_id)
    checks = tuple(
        SubmissionCheck(
            check_id=f"check.qualify.{kind}",
            check_kind=kind,
            applicability="REQUIRED",
            status="PASS",
            source_identity="fixture.strict",
            source_version="v1",
            input_sha256=status["readiness"]["input_fingerprint"],
            output_sha256="c" * 64,
            coverage="fixture-labelled exact evidence",
            evidence=(evidence[index],),
            evaluated_at="2026-09-21T12:10:00Z",
            valid_until="2026-09-22T12:10:00Z",
        )
        for index, kind in enumerate(
            (
                "component_integrity",
                "journal_requirements",
                "author_declarations",
                "claim_citation_coverage",
                "scientific_review",
            )
        )
    )
    report = SubmissionCheckReport(
        schema_version="arw.submission-check-report.v1",
        report_id="report.qualify",
        submission_id=packet.submission_id,
        packet_manifest_sha256=packet_ref.manifest_sha256,
        input_fingerprint=status["readiness"]["input_fingerprint"],
        evaluated_at="2026-09-21T12:10:00Z",
        valid_until="2026-09-22T12:10:00Z",
        checks=checks,
        readiness="READY_FOR_HUMAN_SUBMIT",
    )
    raw = canonical_json_bytes(report.model_dump(mode="json"))
    (root / "qualify-report.json").write_bytes(raw)
    replay = replay_run(root)
    request = ArtifactAcceptanceRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN,
            "occurred_at": "2026-09-21T12:11:00Z",
            "event_id": "evt-00000000-0000-4000-8000-000001000000",
            "command_id": "cmd-00000000-0000-4000-8000-000001000000",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "expected_revision": replay.revision,
            "artifact_id": "artifact.qualify-report",
            "artifact_kind": "submission-check-report",
            "media_type": "application/json",
            "content_path": "qualify-report.json",
            "content_sha256": hashlib.sha256(raw).hexdigest(),
            "base_revision": replay.revision,
            "consumed_sha256": [replay.last_event_sha256],
        }
    )
    service = SubmissionWorkflowService(root)
    first = service.qualify(report, request)
    second = service.qualify(report, request)
    assert first["gate"]["accepted"] is True
    assert first["gate"]["event"]["payload"]["decision"]["verdict"] == "PASS"
    assert second["gate"]["accepted"] is True
    assert second["gate"]["event"]["event_id"] == first["gate"]["event"]["event_id"]
    assert replay_run(root).revision == first["gate"]["state"]["accepted_revision"]
    before_stale_check = replay_run(root).revision
    stale = service.check(packet.submission_id, as_of="2026-09-23T12:10:00Z")
    assert stale["readiness"]["readiness"] == "STALE"
    assert replay_run(root).revision == before_stale_check


def test_confirmation_qualification_is_narrow_and_requires_later_human_decision(tmp_path: Path) -> None:
    root = seed_run(tmp_path)
    packet, _packet_ref = _admit_complete_initial_packet(root)
    scope = f"submission:{packet.submission_id}:author:person.qualify:funding"
    subject_sha256 = declaration_subject_sha256(
        packet.submission_id,
        "person.qualify",
        "funding",
        packet.authors[0].funding,
    )
    replay = replay_run(root)
    request = RuntimeCommandRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN,
            "occurred_at": "2026-09-21T12:02:00Z",
            "event_id": "evt-00000000-0000-4000-8000-000001000001",
            "command_id": "cmd-00000000-0000-4000-8000-000001000001",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "expected_revision": replay.revision,
        }
    )
    result = SubmissionWorkflowService(root).qualify_confirmation(
        packet.submission_id, scope, subject_sha256, request
    )
    assert result["gate"]["accepted"] is True
    assert result["gate"]["event"]["payload"]["decision"]["verdict"] == "PASS"
    assert result["human_decision_required"] is True
