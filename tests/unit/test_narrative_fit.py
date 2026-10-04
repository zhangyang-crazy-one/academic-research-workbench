"""Frozen venue fit stays advisory and replayable over bound source bytes."""

from __future__ import annotations

import json
from datetime import date

import pytest
from arw_writing.narrative_fit import NarrativeFitError, freeze, freshness, report

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.narrative import approve, current, propose
from arw.kernel.state.narrative_fit import FitJudgment, VenueFitProfile

from . import test_narrative_realization
from .test_narrative import _accept_paper_artifact, plan
from .test_narrative_realization import _fixture


@pytest.fixture(name="paper")
def fit_paper(tmp_path):
    return test_narrative_realization.paper.__wrapped__(tmp_path)


def _profile(path):
    profile = {
        "schema_version": "arw.venue-fit-profile.v1", "venue_id": "venue.synthetic",
        "version": "2026-a",
        "verified_on": "2026-09-01", "review_due": "2026-10-01",
        "official_hard_requirements": [
            {"rule_id": "official.section", "statement": "Include a Limitations section",
             "source_url": "https://example.test/venue", "source_sha256": "a" * 64,
             "source_locator": "authors#limitations", "reviewed_by": "reviewer.fixture",
             "predicate": {"kind": "heading_present", "value": "Limitations"}},
            {"rule_id": "official.pages", "statement": "At most ten PDF pages",
             "source_url": "https://example.test/venue", "source_sha256": "a" * 64,
             "source_locator": "authors#pages", "reviewed_by": "reviewer.fixture",
             "predicate": {"kind": "pdf_page_count_at_most", "limit": 10}},
            {"rule_id": "official.freeform", "statement": "Describe societal impact",
             "source_url": "https://example.test/venue", "source_sha256": "a" * 64,
             "source_locator": "authors#impact"},
        ],
        "structural_expectations": [
            {"rule_id": "structure.anonymous", "statement": "Check listed author marker",
             "source_url": "https://example.test/venue", "source_sha256": "a" * 64,
             "source_locator": "authors#blind", "reviewed_by": "reviewer.fixture",
             "predicate": {"kind": "bounded_marker_absent", "value": "Author Name"}},
        ],
    }
    path.write_bytes(canonical_json_bytes(profile))
    return path


def _accepted_draft(paper):
    value = _fixture(paper)
    (paper / "outline.json").write_bytes(canonical_json_bytes(value))
    assert _accept_paper_artifact(paper, "outline.fit", "outline.json", 9101,
                                  kind="narrative-outline").accepted
    blueprint = {**value, "stage": "blueprint", "predecessor_artifact_id": "outline.fit"}
    (paper / "blueprint.json").write_bytes(canonical_json_bytes(blueprint))
    assert _accept_paper_artifact(paper, "blueprint.fit", "blueprint.json", 9102,
                                  kind="narrative-blueprint").accepted
    draft = {**value, "stage": "draft", "predecessor_artifact_id": "blueprint.fit"}
    (paper / "draft.json").write_bytes(canonical_json_bytes(draft))
    assert _accept_paper_artifact(paper, "draft.fit", "draft.json", 9103,
                                  kind="narrative-draft").accepted


def test_fit_layers_replay_and_tamper_detection(paper, tmp_path):
    _accepted_draft(paper)
    venue = _profile(tmp_path / "profile.json")
    snapshot = freeze(paper, "venue.synthetic", "draft.fit", venue)
    first = canonical_json_bytes(report(snapshot))
    replay = type(snapshot).model_validate_json(canonical_json_bytes(snapshot.model_dump(mode="json")))
    assert canonical_json_bytes(report(replay)) == first
    result = json.loads(first)
    assert result["structural_expectations"]["narrative_realization"]["mechanical_status"] == "PASS"
    assert [r["assessment"]["status"] for r in result["official_hard_requirements"]] == [
        "not_met", "not_evaluated", "unknown"]
    assert result["structural_expectations"]["venue_rules"][0]["assessment"]["status"] == "bounded_observation"
    assert result["reviewer_judgment"] is None
    assert result["judgment_status"] == "not_supplied"
    assert result["empirical_status"] == "not_evaluated"
    assert result["empirical_patterns"] == []
    tampered = snapshot.model_dump(mode="json")
    tampered["manuscript_source_base64"] = "eA=="
    with pytest.raises(NarrativeFitError, match="digest differs"):
        report(type(snapshot).model_validate_json(canonical_json_bytes(tampered)))
    tampered = snapshot.model_dump(mode="json")
    tampered["validation"]["mechanical_status"] = "FAIL"
    with pytest.raises(NarrativeFitError, match="structural result differs"):
        report(type(snapshot).model_validate_json(canonical_json_bytes(tampered)))
    tampered = snapshot.model_dump(mode="json")
    tampered["pdf_page_count"] = 1
    with pytest.raises(ValueError):
        type(snapshot).model_validate_json(canonical_json_bytes(tampered))


def test_frozen_report_unchanged_by_active_narrative_profile_and_optional_judgment(paper, tmp_path):
    _accepted_draft(paper)
    venue = _profile(tmp_path / "profile.json")
    snapshot = freeze(paper, "venue.synthetic", "draft.fit", venue)
    base = report(snapshot)
    assessment = FitJudgment(reviewer="reviewer.fixture", assessment="Possible venue fit; inspect scope.",
                             model_id="model.fixture", provider="local.fixture", prompt_version="v1",
                             input_sha256="0" * 64)
    from arw_writing.narrative_fit import _core_digest
    assessment = assessment.model_copy(update={"input_sha256": _core_digest(snapshot)})
    judged = snapshot.model_copy(update={"judgment": assessment})
    with_judgment = report(judged)
    assert with_judgment["reviewer_judgment"]["model_id"] == "model.fixture"
    assert with_judgment["judgment_status"] == "supplied"
    for layer in ("official_hard_requirements", "structural_expectations", "empirical_patterns"):
        assert with_judgment[layer] == base[layer]
    wrong = judged.model_copy(update={"judgment": assessment.model_copy(update={"input_sha256": "f" * 64})})
    with pytest.raises(NarrativeFitError, match="judgment does not bind"):
        report(wrong)
    before = canonical_json_bytes(base)
    (paper / "paper.md").write_text("active text changed", encoding="utf-8")
    with pytest.raises(NarrativeFitError, match="unresolved recovery tail"):
        freeze(paper, "venue.synthetic", "draft.fit", venue)
    venue.write_bytes(canonical_json_bytes({**VenueFitProfile.model_validate_json(venue.read_bytes()).model_dump(mode="json"),
                                             "version": "2026-b"}))
    proposal = propose(paper.parent.parent, plan("theory"), expected_sha256=current(paper.parent.parent).sha256,
                       reason="Synthetic author strategy change")
    approve(paper.parent.parent, proposal_sha256=proposal["proposal_sha256"], author_id="author.fixture")
    assert canonical_json_bytes(report(snapshot)) == before
    assert freshness(paper, snapshot, venue, as_of=date(2026, 10, 2))["status"] == "stale"


def test_expired_profile_without_byte_change_needs_recheck(paper, tmp_path):
    _accepted_draft(paper)
    venue = _profile(tmp_path / "profile.json")
    snapshot = freeze(paper, "venue.synthetic", "draft.fit", venue)
    assert freshness(paper, snapshot, venue, as_of=date(2026, 10, 2))["status"] == "needs_recheck"


def test_page_count_requires_and_recounts_accepted_pdf_bytes(paper, tmp_path):
    import io

    from pypdf import PdfWriter

    from arw.kernel.core.canonical import sha256_hex
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.ledger.journal import replay_run
    from arw.kernel.state.models import ArtifactAcceptanceRequest

    _accepted_draft(paper)
    venue = _profile(tmp_path / "profile.json")
    pdf = PdfWriter()
    pdf.add_blank_page(width=612, height=792)
    output = io.BytesIO()
    pdf.write(output)
    (paper / "fit.pdf").write_bytes(output.getvalue())
    state = replay_run(paper)
    accepted = RuntimeCommandService(paper).accept_artifact(
        ArtifactAcceptanceRequest.model_validate({
            "schema_version": "1.0.0", "run_id": state.run_id,
            "event_id": "evt-00000000-0000-4000-8000-000000009300",
            "command_id": "cmd-00000000-0000-4000-8000-000000009300",
            "expected_revision": state.revision, "occurred_at": "2026-07-13T00:01:00Z",
            "actor_id": "parent.runtime", "actor_role": "parent_control_plane",
            "artifact_id": "pdf.fit", "artifact_kind": "paper-pdf",
            "media_type": "application/pdf", "content_path": "fit.pdf",
            "content_sha256": sha256_hex(output.getvalue()),
            "base_revision": state.revision,
            "consumed_sha256": [state.last_event_sha256],
        }))
    assert accepted.accepted
    snapshot = freeze(paper, "venue.synthetic", "draft.fit", venue, pdf_artifact_id="pdf.fit")
    assert report(snapshot)["official_hard_requirements"][1]["assessment"] == {
        "status": "met", "observed_page_count": 1}
    altered = snapshot.model_copy(update={"pdf_page_count": 2})
    with pytest.raises(NarrativeFitError, match="page count differs"):
        report(altered)


def test_accepted_manuscript_with_failing_proposed_graph_reports_structural_failure(paper, tmp_path):
    _accepted_draft(paper)
    assert _accept_paper_artifact(paper, "source.fit", "paper.md", 9104,
                                  kind="manuscript-source").accepted
    proposed = _fixture(paper)
    proposed["stage"] = "draft"
    proposed["predecessor_artifact_id"] = "blueprint.fit"
    proposed["nodes"][3]["evidence_ref"] = "missing.evidence"
    (paper / "proposed-fit.json").write_bytes(canonical_json_bytes(proposed))
    venue = _profile(tmp_path / "profile.json")
    snapshot = freeze(paper, "venue.synthetic", "source.fit", venue,
                      realization_path="proposed-fit.json")
    result = report(snapshot)
    assert result["structural_expectations"]["narrative_realization"] == {
        "mechanical_status": "FAIL", "semantic_status": "UNKNOWN",
        "reason_code": "narrative_orphan_claim", "human_review_reason_codes": []}
    assert canonical_json_bytes(report(type(snapshot).model_validate_json(
        canonical_json_bytes(snapshot.model_dump(mode="json"))))) == canonical_json_bytes(result)


def test_cli_frozen_offline_repeat_does_not_touch_ledger_or_narrative(paper, tmp_path, capsys):
    from arw.cli import main

    _accepted_draft(paper)
    venue = _profile(tmp_path / "profile.json")
    frozen = tmp_path / "fit-snapshot.json"
    journal = (paper / "journal/segments/00000001.jsonl")
    narrative = paper.parent.parent / ".arw/narrative/events.jsonl"
    before = (journal.read_bytes(), narrative.read_bytes())
    assert main(["writing", "narrative-fit", "--run-root", str(paper), "--target", "venue.synthetic",
                 "--manuscript-artifact-id", "draft.fit", "--profile", str(venue),
                 "--snapshot-out", str(frozen)]) == 0
    first = capsys.readouterr().out
    assert main(["writing", "narrative-fit", "--target", "venue.synthetic",
                 "--snapshot", str(frozen)]) == 0
    second = capsys.readouterr().out
    assert first == second
    assert (journal.read_bytes(), narrative.read_bytes()) == before


def test_minimal_cli_uses_bundled_target_and_latest_accepted_draft(paper, capsys):
    from arw.cli import main

    _accepted_draft(paper)
    assert main(["writing", "narrative-fit", "--run-root", str(paper),
                 "--target", "coling-2027"]) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["input_binding"]["manuscript_artifact_id"] == "draft.fit"
    assert value["input_binding"]["venue_profile_version"].startswith("bundle:")
    assert value["official_hard_requirements"]
    assert {r["assessment"]["status"] for r in value["official_hard_requirements"]} == {"unknown"}
    assert all(r["provenance"]["source_url"].startswith("bundle:")
               for r in value["official_hard_requirements"])


@pytest.mark.parametrize("scope", ["project", "run"])
def test_promoted_venue_heuristic_is_empirical_only(paper, tmp_path, scope):
    from arw_research_learning.service import ResearchLearningService

    from arw.kernel.core.canonical import sha256_hex
    from tests.integration.test_research_artifacts import request
    from tests.integration.test_research_learning import (
        candidate,
        venue_exemplar,
    )

    _accepted_draft(paper)
    project_root = paper.parent.parent
    (project_root / ".arw/learning-policy.json").write_text('{"enabled":true}')
    learning = ResearchLearningService(project_root, run_root=paper)
    def write_accepted(artifact_id, body, number):
        relative = artifact_id + ".json"
        (paper / relative).write_bytes(canonical_json_bytes(body))
        assert _accept_paper_artifact(paper, artifact_id, relative, number,
                                      kind="learning-evidence").accepted
    observations = []
    for index in range(3):
        source_id = f"artifact.fitpaper{index}"
        source_body = {"synthetic_paper": index}
        write_accepted(source_id, source_body, 9200 + index)
        exemplar_id = f"artifact.fitvenue{index}"
        exemplar = venue_exemplar(index, source_artifact_id=source_id,
                       source_sha256=sha256_hex(canonical_json_bytes(source_body)))
        review_id = f"artifact.fitreview{index}"
        write_accepted(review_id, {"schema_version": "arw.venue-source-review.v1",
                "review_id": f"review.fit{index}", "source_artifact_id": source_id,
                "source_sha256": exemplar["source_sha256"],
                "official_url": exemplar["official_url"],
                "accepted_category": exemplar["accepted_category"],
                "accepted_year": exemplar["accepted_year"],
                "access_basis": exemplar["access_basis"], "reviewer": exemplar["source_reviewer"],
                "decision": "VERIFIED"}, 9205 + index)
        write_accepted(exemplar_id, {**exemplar, "source_review_artifact_id": review_id}, 9210 + index)
        observations.append(learning.observe_venue(exemplar_id, request=request(paper, 9220 + index))["record_id"])
    item = candidate(observations[0], heuristic_id="heuristic.fitvenue", scope=scope,
                     venue_applicability={"venue_id": "venue.synthetic", "domain_id": "domain.synthetic"})
    proposed = learning.extract(item, request=request(paper, 9230))
    policy = {"schema_version": "arw.venue-evidence-policy.v1", "policy_id": "policy.fitvenue",
              "version": "1", "mode": "venue-evidence", "exemplar_observation_ids": observations}
    write_accepted("artifact.fitpolicy", policy, 9231)
    (project_root / ".arw/learning-policy.json").write_text(
        '{"enabled":true,"evaluation_policy_artifact_id":"artifact.fitpolicy"}')
    samples = []
    for index, finding in enumerate(("supporting", "supporting", "counterexample")):
        artifact_id = f"artifact.fitsample{index}"
        write_accepted(artifact_id, {
            "schema_version": "arw.venue-evidence-sample.v1", "heuristic_id": item.heuristic_id,
            "policy_id": "policy.fitvenue", "policy_version": "1",
            "exemplar_observation_id": observations[index], "finding": finding,
            "rationale": "Synthetic reviewed venue pattern", "reviewer": "reviewer.fixture",
        }, 9240 + index)
        samples.append(artifact_id)
    learning.evaluate(item.heuristic_id, samples, request=request(paper, 9250))
    qualification = learning.qualify(item.heuristic_id, request=request(paper, 9251))
    approval = "artifact.fitapproval"
    write_accepted(approval, {"action": "promote_heuristic", "heuristic_id": item.heuristic_id,
                              "heuristic_digest": proposed["content_digest"],
                              "qualification_receipt_id": qualification["content_digest"],
                   "to_scope": scope, "status": "APPROVED",
                   "reviewer": "reviewer.fixture"}, 9253)
    learning.promote(item.heuristic_id, to_scope=scope, consent=True, approval_artifact_id=approval,
                     request=request(paper, 9252))
    venue = _profile(tmp_path / "profile.json")
    annotations = tmp_path / "reviewed-matches.json"
    annotations.write_bytes(canonical_json_bytes({item.heuristic_id: {
        "predicate": {"kind": "heading_present", "value": "Venue Fit"},
        "reviewed_by": "reviewer.fixture"}}))
    snapshot = freeze(paper, "venue.synthetic", "draft.fit", venue,
                      heuristic_ids=[item.heuristic_id], domain_id="domain.synthetic",
                      heuristic_annotations_path=annotations)
    result = report(snapshot)
    assert result["empirical_patterns"][0]["evaluation_counts"] == {
        "supporting": 2, "counterexample": 1, "unknown": 0}
    assert result["empirical_status"] == "evaluated_selected"
    assert result["empirical_patterns"][0]["assessment"]["status"] == "not_met"
    assert result["official_hard_requirements"][0]["assessment"]["status"] == "not_met"
    if scope == "run":
        altered = snapshot.model_copy(update={"run_id": "run-00000000-0000-4000-8000-000000000002"})
        with pytest.raises(NarrativeFitError, match="another run"):
            report(altered)


def test_old_frozen_heading_report_replays_exactly_under_current_admission_policy(paper, tmp_path, monkeypatch):
    from arw.kernel.ledger.journal import replay_run
    from arw.kernel.policy import narrative_realization as policy
    from arw.kernel.state.narrative_realization import NarrativeRealization

    value = _fixture(paper)
    old = (paper / "paper.md").read_bytes()
    raw = b"# " + old
    first_end = value["nodes"][0]["span"]["end"] + 2
    value["nodes"][0]["span"].update(end=first_end, sha256=sha256_hex(raw[:first_end]))
    for node in value["nodes"][1:]:
        node["span"].update(start=node["span"]["start"] + 2, end=node["span"]["end"] + 2)
    value["source_sha256"] = sha256_hex(raw)
    (paper / "paper.md").write_bytes(raw)
    venue = _profile(tmp_path / "old-fit-profile.json")
    with monkeypatch.context() as legacy:
        legacy.setattr(policy, "_heading_only", lambda _: False)
        for index, (stage, artifact_id, predecessor) in enumerate([
            ("outline", "outline.fit", None),
            ("blueprint", "blueprint.fit", "outline.fit"),
            ("draft", "draft.fit", "blueprint.fit"),
        ]):
            realization = {**value, "stage": stage, "predecessor_artifact_id": predecessor}
            path = f"old-{stage}.json"
            (paper / path).write_bytes(canonical_json_bytes(realization))
            accepted = _accept_paper_artifact(paper, artifact_id, path, 9501 + index, kind=f"narrative-{stage}")
            assert accepted.accepted, accepted.rejection
        snapshot = freeze(paper, "venue.synthetic", "draft.fit", venue)
        original = canonical_json_bytes(report(snapshot))
    assert snapshot.validation["mechanical_status"] == "PASS"
    assert snapshot.validation["semantic_status"] == "UNKNOWN"
    assert replay_run(paper).recovery_health == "healthy"
    # The current admission rule still rejects this exact historical prose.
    with pytest.raises(policy.NarrativeRealizationError) as rejected:
        policy.validate_realization(paper, NarrativeRealization.model_validate(value), current(paper.parent.parent))
    assert rejected.value.code == "narrative_heading_only"
    restored = type(snapshot).model_validate_json(canonical_json_bytes(snapshot.model_dump(mode="json")))
    assert canonical_json_bytes(report(restored)) == original
    # Capturing the same accepted old artifact also retains the replay policy.
    assert freeze(paper, "venue.synthetic", "draft.fit", venue).validation == snapshot.validation
