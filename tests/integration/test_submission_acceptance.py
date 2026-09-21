from __future__ import annotations

import pytest

from arw.kernel.state.submission import (
    CHECK_DEPENDENCY_CATEGORIES,
    ReviewResponse,
    evaluate_submission_readiness,
    submission_dependency_input_sha256,
)
from tests.unit.test_submission_contracts import check, packet, ref

CATEGORY_NAMES = tuple(
    dict.fromkeys(
        category
        for categories in CHECK_DEPENDENCY_CATEGORIES.values()
        for category in categories
    )
) + ("author_decisions",)
BASELINE_CATEGORIES = {
    category: f"{index:064x}"
    for index, category in enumerate(CATEGORY_NAMES, start=1)
}


@pytest.mark.parametrize("changed_category", tuple(BASELINE_CATEGORIES))
def test_a3_dependency_change_invalidates_only_affected_checks_and_aggregate(
    changed_category: str,
) -> None:
    """A3: dependency changes stale the bound report, not its history."""

    submission = packet(round_number=1)
    response = ReviewResponse(
        schema_version="arw.submission-response.v1",
        response_id="response.a3",
        submission_id=submission.submission_id,
        round_number=1,
        comment_id="review.comment.a3",
        status="not_adopted",
        response_text="The requested change is not adopted.",
        rationale="The request is outside the study scope.",
        evidence=(ref("response-evidence.a3"),),
        author_decision_id="decision.response.a3",
    )
    check_kinds = tuple(CHECK_DEPENDENCY_CATEGORIES)
    historical_checks = tuple(
        check(kind).model_copy(
            update={
                "input_sha256": submission_dependency_input_sha256(
                    kind, BASELINE_CATEGORIES
                )
            }
        )
        for kind in check_kinds
    )

    historical = evaluate_submission_readiness(
        submission,
        packet_manifest_sha256="f" * 64,
        checks=historical_checks,
        responses=(response,),
        dependency_sha256=tuple(BASELINE_CATEGORIES.values()),
        valid_input_sha256=("e" * 64, *BASELINE_CATEGORIES.values()),
        dependency_categories=BASELINE_CATEGORIES,
        evaluated_at="2026-09-21T12:00:00Z",
    )
    assert historical.readiness == "READY_FOR_HUMAN_SUBMIT"

    changed_categories = {
        **BASELINE_CATEGORIES,
        changed_category: "a" * 64,
    }
    current = evaluate_submission_readiness(
        submission,
        packet_manifest_sha256="f" * 64,
        checks=historical_checks,
        responses=(response,),
        dependency_sha256=tuple(changed_categories.values()),
        valid_input_sha256=("d" * 64, *changed_categories.values()),
        dependency_categories=changed_categories,
        evaluated_at="2026-09-21T12:05:00Z",
    )

    affected = {
        kind
        for kind, categories in CHECK_DEPENDENCY_CATEGORIES.items()
        if changed_category in categories
    }
    affected.add(
        "review_response_coverage"
        if changed_category == "responses"
        else "__not_a_check__"
    )
    required_kinds = set(check_kinds)

    assert current.readiness == "STALE"
    assert {
        code.removeprefix("check_input_stale:")
        for code in current.reason_codes
        if code.startswith("check_input_stale:")
    } == affected & required_kinds
    assert affected & required_kinds
    assert {
        kind
        for kind in required_kinds
        if kind not in affected
    } == {
        kind
        for kind in required_kinds
        if f"check_input_stale:{kind}" not in current.reason_codes
    }

    # The historical report/check receipts remain usable records and are not
    # mutated when present-time aggregation discovers stale dependencies.
    assert historical.readiness == "READY_FOR_HUMAN_SUBMIT"
    assert all(item.status == "PASS" for item in historical_checks)
    assert all(
        item.input_sha256
        == submission_dependency_input_sha256(item.check_kind, BASELINE_CATEGORIES)
        for item in historical_checks
    )
