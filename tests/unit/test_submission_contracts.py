from __future__ import annotations

import pytest
from pydantic import ValidationError

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.execution.submission import (
    SubmissionWorkflowError,
    validate_submission_payload,
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
    SubmissionPacket,
    SubmissionResultObservation,
    evaluate_submission_readiness,
    review_comment_identity,
    submission_dependency_input_sha256,
)

HASH = "a" * 64
RUN_ID = "run-00000000-0000-4000-8000-000000000901"
EVENT_ID = "evt-00000000-0000-4000-8000-000000000902"


def ref(name: str) -> SubmissionArtifactReference:
    return SubmissionArtifactReference(
        artifact_id=f"artifact.{name}",
        manifest_sha256=HASH,
        content_sha256="b" * 64,
        accepting_event_id=EVENT_ID,
    )


def declaration() -> DeclarationField:
    return DeclarationField(
        status="confirmed",
        value="confirmed by author",
        human_decision_id="decision.author",
    )


def packet(**updates) -> SubmissionPacket:
    round_number = updates.pop("round_number", 0)
    value = SubmissionPacket(
        schema_version="arw.submission-packet.v1",
        project_id="project.demo",
        run_id=RUN_ID,
        submission_id="submission.demo",
        packet_version=1,
        journal_id="journal.demo",
        journal_name="Journal of Demonstrations",
        article_type="research-article",
        round_number=round_number,
        manuscript_id="manuscript.demo",
        manuscript_version="v1",
        manuscript=ref("manuscript"),
        components=(
            {
                "component_id": "component.manuscript",
                "role": "main_manuscript",
                "artifact": ref("manuscript"),
                "media_type": "text/markdown",
                "byte_length": 128,
                "required": True,
            },
            {
                "component_id": "component.title",
                "role": "title_page",
                "artifact": ref("title"),
                "media_type": "text/markdown",
                "byte_length": 32,
                "required": True,
            },
        ),
        policy_snapshot=ref("policy"),
        authors=(
            {
                "person_id": "person.author",
                "display_name": "Author One",
                "order": 0,
                "corresponding": True,
                "contributions": ("conceptualization",),
                "funding": declaration(),
                "conflicts": declaration(),
                "ethics": declaration(),
                "data": declaration(),
                "ai_use": declaration(),
            },
        ),
        created_at="2026-09-21T12:00:00Z",
        created_by="parent.runtime",
    )
    return value.model_copy(update=updates)


def check(kind: str) -> SubmissionCheck:
    return SubmissionCheck(
        check_id=f"check.{kind}",
        check_kind=kind,
        applicability="REQUIRED",
        status="PASS",
        source_identity="fixture.checker",
        source_version="1.0",
        input_sha256=HASH,
        output_sha256="c" * 64,
        coverage="fixture-labelled evidence only",
        evidence=(ref(f"evidence.{kind}"),),
        evaluated_at="2026-09-21T12:00:00Z",
        valid_until="2026-09-22T12:00:00Z",
    )


def test_packet_rejects_unknown_fields_and_duplicate_singletons() -> None:
    with pytest.raises(ValidationError):
        SubmissionPacket.model_validate_json(
            canonical_json_bytes({**packet().model_dump(mode="json"), "unexpected": True})
        )
    duplicate = packet().model_dump(mode="json")
    duplicate["components"].append(
        {
            **duplicate["components"][0],
            "component_id": "component.manuscript-copy",
            "artifact": {**duplicate["components"][0]["artifact"], "artifact_id": "artifact.manuscript-copy"},
        }
    )
    with pytest.raises(ValidationError, match="duplicate singleton"):
        SubmissionPacket.model_validate_json(canonical_json_bytes(duplicate))


def test_journal_snapshot_rejects_credentials_and_retains_unknowns() -> None:
    with pytest.raises(ValidationError, match="credentials"):
        JournalRequirementsSnapshot(
            schema_version="arw.journal-requirements.v1",
            snapshot_id="snapshot.demo",
            journal_id="journal.demo",
            journal_name="Journal",
            article_type="research-article",
            official_source_urls=("https://user:secret@example.test/policy",),
            retained_source_artifacts=(ref("policy-source"),),
            captured_at="2026-09-21T12:00:00Z",
            verified_at="2026-09-21T12:00:00Z",
            requirements=(),
            verifier_id="parent.runtime",
        )


def test_review_ids_are_source_bound_and_locations_require_render_digest() -> None:
    locator = ReviewLocator(locator_type="paragraph", value="methods.p1")
    assert review_comment_identity("submission.demo", 1, HASH, locator).startswith("review.")
    with pytest.raises(ValidationError, match="rendered file digest"):
        ReviewLocator(locator_type="page", value="p.2")


def test_review_round_rejects_dependency_cycles() -> None:
    source = ref("letter-cycle")
    first_locator = ReviewLocator(locator_type="paragraph", value="p1")
    second_locator = ReviewLocator(locator_type="paragraph", value="p2")
    first_id = review_comment_identity("submission.demo", 1, HASH, first_locator)
    second_id = review_comment_identity("submission.demo", 1, HASH, second_locator)
    with pytest.raises(ValidationError, match="dependency cycle"):
        ReviewRound(
            schema_version="arw.submission-review-round.v1",
            round_id="round.cycle",
            submission_id="submission.demo",
            round_number=1,
            source_letter=source,
            comments=(
                ReviewComment(
                    comment_id=first_id,
                    submission_id="submission.demo",
                    round_number=1,
                    source_locator=first_locator,
                    quote="First",
                    original_order=0,
                    depends_on=(second_id,),
                ),
                ReviewComment(
                    comment_id=second_id,
                    submission_id="submission.demo",
                    round_number=1,
                    source_locator=second_locator,
                    quote="Second",
                    original_order=1,
                    depends_on=(first_id,),
                ),
            ),
            imported_at="2026-09-21T12:00:00Z",
            imported_by="parent.runtime",
        )


def test_submission_payload_rejects_oversized_json_before_admission() -> None:
    with pytest.raises(SubmissionWorkflowError, match="256 KiB"):
        validate_submission_payload("journal-requirements", b"{" + b"a" * (256 * 1024) + b"}")


def test_response_cannot_close_without_revision_evidence() -> None:
    with pytest.raises(ValidationError, match="revision evidence"):
        ReviewResponse(
            schema_version="arw.submission-response.v1",
            response_id="response.demo",
            submission_id="submission.demo",
            round_number=1,
            comment_id="review.comment",
            status="addressed",
            response_text="We changed the manuscript.",
        )


def test_addressed_response_location_must_bind_current_manuscript() -> None:
    with pytest.raises(ValidationError, match="manuscript digest"):
        ReviewResponse(
            schema_version="arw.submission-response.v1",
            response_id="response.locator",
            submission_id="submission.demo",
            round_number=1,
            comment_id="review.comment",
            status="addressed",
            response_text="We changed the manuscript.",
            author_decision_id="decision.author",
            evidence=(ref("revision"),),
            locations=(ReviewLocator(locator_type="paragraph", value="methods.p1"),),
        )


def test_revision_round_fixture_keeps_comment_identity_and_disposition() -> None:
    locator = ReviewLocator(locator_type="paragraph", value="methods.p1")
    comment_id = review_comment_identity("submission.demo", 1, HASH, locator)
    round_value = ReviewRound(
        schema_version="arw.submission-review-round.v1",
        round_id="round.demo",
        submission_id="submission.demo",
        round_number=1,
        source_letter=ref("review-letter"),
        comments=(
            ReviewComment(
                comment_id=comment_id,
                submission_id="submission.demo",
                round_number=1,
                source_locator=locator,
                quote="Please clarify the method.",
                original_order=0,
            ),
        ),
        imported_at="2026-09-21T12:00:00Z",
        imported_by="parent.runtime",
    )
    assert round_value.comments[0].comment_id == comment_id
    response = ReviewResponse(
        schema_version="arw.submission-response.v1",
        response_id="response.demo",
        submission_id="submission.demo",
        round_number=1,
        comment_id=comment_id,
        status="not_adopted",
        response_text="We retain the method and explain the limitation.",
        rationale="The requested change would alter the registered analysis.",
        author_decision_id="decision.author",
    )
    assert response.status == "not_adopted"


def test_readiness_fails_closed_when_required_checks_are_missing() -> None:
    result = evaluate_submission_readiness(
        packet(),
        packet_manifest_sha256=HASH,
        checks=(check("component_integrity"),),
        evaluated_at="2026-09-21T12:00:00Z",
    )
    assert result.readiness == "BLOCKED"
    assert "check_not_checked:journal_requirements" in result.reason_codes


def test_initial_submission_reaches_human_submit_boundary_only_after_all_checks_pass() -> None:
    result = evaluate_submission_readiness(
        packet(),
        packet_manifest_sha256=HASH,
        checks=tuple(
            check(kind)
            for kind in (
                "component_integrity",
                "journal_requirements",
                "author_declarations",
                "claim_citation_coverage",
                "scientific_review",
            )
        ),
        evaluated_at="2026-09-21T12:00:00Z",
    )
    assert result.readiness == "READY_FOR_HUMAN_SUBMIT"


def test_revision_readiness_requires_every_leaf_comment() -> None:
    result = evaluate_submission_readiness(
        packet(round_number=1),
        packet_manifest_sha256=HASH,
        checks=tuple(
            check(kind)
            for kind in (
                "component_integrity",
                "journal_requirements",
                "author_declarations",
                "claim_citation_coverage",
                "scientific_review",
                "review_response_coverage",
            )
        ),
        expected_comment_ids=("review.comment",),
        evaluated_at="2026-09-21T12:00:00Z",
    )
    assert result.readiness == "BLOCKED"
    assert "review_comments_unresolved" in result.reason_codes


def test_readiness_reports_stale_required_checks_fail_closed() -> None:
    expired = check("component_integrity").model_copy(
        update={"status": "STALE", "valid_until": "2026-09-20T12:00:00Z"}
    )
    result = evaluate_submission_readiness(
        packet(),
        packet_manifest_sha256=HASH,
        checks=(expired,),
        evaluated_at="2026-09-21T12:00:00Z",
    )
    assert result.readiness == "STALE"
    assert "check_stale:component_integrity" in result.reason_codes


def test_heuristic_pass_is_not_strict_readiness_evidence() -> None:
    heuristic = check("component_integrity").model_copy(
        update={"limitations": ("heuristic-only",)}
    )
    result = evaluate_submission_readiness(
        packet(),
        packet_manifest_sha256=HASH,
        checks=(heuristic,),
        evaluated_at="2026-09-21T12:00:00Z",
    )
    assert result.readiness == "BLOCKED"
    assert "check_limited:component_integrity" in result.reason_codes


def test_required_check_with_unbound_input_digest_is_stale() -> None:
    result = evaluate_submission_readiness(
        packet(),
        packet_manifest_sha256=HASH,
        checks=(check("component_integrity"),),
        valid_input_sha256=("d" * 64,),
        evaluated_at="2026-09-21T12:00:00Z",
    )
    assert result.readiness == "STALE"
    assert "check_input_stale:component_integrity" in result.reason_codes


def test_dependency_category_change_invalidates_only_dependent_required_checks() -> None:
    categories = {
        "packet": "1" * 64,
        "attachments": "2" * 64,
        "policy": "3" * 64,
        "roster": "4" * 64,
        "contributions": "5" * 64,
        "disclosures": "6" * 64,
        "author_decisions": "7" * 64,
        "manuscript": "8" * 64,
        "bibliography": "9" * 64,
        "render": "a" * 64,
    }
    checks = tuple(
        check(kind).model_copy(
            update={"input_sha256": input_sha256}
        )
        for kind, input_sha256 in (
            (
                "component_integrity",
                submission_dependency_input_sha256("component_integrity", categories),
            ),
            ("journal_requirements", categories["policy"]),
            (
                "author_declarations",
                submission_dependency_input_sha256("author_declarations", categories),
            ),
            (
                "claim_citation_coverage",
                submission_dependency_input_sha256("claim_citation_coverage", categories),
            ),
            (
                "scientific_review",
                submission_dependency_input_sha256("scientific_review", categories),
            ),
        )
    )
    changed = {**categories, "attachments": "b" * 64}
    result = evaluate_submission_readiness(
        packet(),
        packet_manifest_sha256=HASH,
        checks=checks,
        dependency_sha256=tuple(changed.values()),
        valid_input_sha256=("f" * 64, *changed.values()),
        dependency_categories=changed,
        evaluated_at="2026-09-21T12:00:00Z",
    )
    assert result.readiness == "STALE"
    assert "check_input_stale:component_integrity" in result.reason_codes
    assert "check_input_stale:scientific_review" in result.reason_codes
    assert "check_input_stale:journal_requirements" not in result.reason_codes
    assert "check_input_stale:claim_citation_coverage" not in result.reason_codes


def test_external_result_requires_attributed_evidence_and_never_implies_submit_action() -> None:
    with pytest.raises(ValidationError, match="platform receipt"):
        SubmissionResultObservation(
            schema_version="arw.submission-result-observation.v1",
            observation_id="observation.unverified",
            submission_id="submission.demo",
            packet_manifest_sha256=HASH,
            state="submitted",
            attribution="platform_receipt",
            recorded_at="2026-09-21T12:00:00Z",
        )
    observation = SubmissionResultObservation(
        schema_version="arw.submission-result-observation.v1",
        observation_id="observation.user",
        submission_id="submission.demo",
        packet_manifest_sha256=HASH,
        state="submitted",
        attribution="user_confirmation",
        recorded_at="2026-09-21T12:00:00Z",
        deviation_codes=("local_readiness_blocked",),
    )
    assert observation.attribution == "user_confirmation"
    assert not hasattr(observation, "submit")
