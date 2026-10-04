"""Evidence-backed learning lifecycle, explicit authority, and recovery boundaries."""

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from arw_research_learning.service import ResearchLearningService
from arw_research_learning.store import (
    LearningDisabled,
    LearningFault,
    ReevaluationRequired,
    body_path,
)

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.ledger.narrative import approve as narrative_approve
from arw.kernel.ledger.narrative import binding_for_start, propose, register, select
from arw.kernel.ledger.narrative import current as narrative_current
from arw.kernel.ledger.research_records import BodyUnavailable, publish_once
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.state.models import ArtifactAcceptanceRequest, InitRunRequest
from arw.kernel.state.research_learning import HeuristicInput
from tests.unit.test_narrative import plan as paper_plan
from tests.unit.test_narrative import project as paper_project
from tests.unit.test_narrative import run_request as paper_run_request

from .test_precise_source_locators import SOURCE, accept, seed
from .test_research_artifacts import request


def prepared(tmp_path):
    root, _ = seed(tmp_path)
    publish_once(
        root,
        ".arw/project.json",
        canonical_json_bytes(
            {"schema_version": "arw.project.v1", "project_id": "project.learning"}
        ),
    )
    (root / ".arw/learning-policy.json").write_text(json.dumps({"enabled": True}))
    service = ResearchLearningService(root, run_root=root)
    return root, service


def candidate(observation_id, **overrides):
    return HeuristicInput.model_validate_json(
        json.dumps(
            {
                "heuristic_id": "heuristic.retrieval",
                "domain": "literature review",
                "trigger": "Missing primary evidence",
                "proposed_action": "Check retrieval coverage before increasing judge calls",
                "applicability": {
                    "task": "literature_review",
                    "model": "recorded-model-v1",
                    "retrieval_coverage": "one indexed corpus",
                    "call_budget": 4,
                    "output_budget": 4096,
                    "metric": "citation_recall",
                },
                "confidence": 0.95,
                "supporting_observation_ids": [observation_id],
                "search_coverage": "All accepted run receipts",
                "evaluation_coverage": "One independent local run; transfer unmeasured",
                "producer": "manual-author",
                "producer_version": "1",
                **overrides,
            }
        )
    )


def observe_candidate(root, service):
    event = next(
        e for e in replay_run(root).events if e.event_type == "artifact.accepted"
    )
    observed = service.observe(event.event_id, request=request(root, 100))
    item = candidate(observed["record_id"])
    proposed = service.extract(item, request=request(root, 101))
    return item, proposed


def write_accepted(root, artifact_id, body, number):
    relative = artifact_id + ".json"
    (root / relative).write_bytes(canonical_json_bytes(body))
    assert accept(
        root, artifact_id, relative, number, kind="learning-evidence"
    ).accepted


def write_accepted_bound(root, artifact_id, body, number):
    relative = artifact_id + ".json"
    raw = canonical_json_bytes(body)
    (root / relative).write_bytes(raw)
    replay = replay_run(root)
    result = RuntimeCommandService(root).accept_artifact(ArtifactAcceptanceRequest.model_validate({
        "schema_version": "1.0.0", "run_id": replay.run_id,
        "occurred_at": "2026-09-08T00:01:00Z",
        "event_id": f"evt-00000000-0000-4000-8000-{number:012d}",
        "command_id": f"cmd-00000000-0000-4000-8000-{number:012d}",
        "actor_id": "parent.runtime", "actor_role": "parent_control_plane",
        "expected_revision": replay.revision, "artifact_id": artifact_id,
        "artifact_kind": "learning-evidence", "media_type": "application/json",
        "content_path": relative, "content_sha256": sha256_hex(raw),
        "base_revision": replay.revision, "consumed_sha256": [replay.last_event_sha256],
    }))
    assert result.accepted, result.rejection


def evaluation_inputs(root, item, mode="replay", version="1", minimum_delta=0.0):
    run_id = replay_run(root).run_id
    policy = {
        "schema_version": "arw.learning-policy.v1",
        "policy_id": "policy.learning",
        "version": version,
        "mode": mode,
        "run_subset": [run_id],
        "metric": "citation_recall",
        "minimum_delta": minimum_delta,
    }
    write_accepted(root, "artifact.policy" + version, policy, 110 + int(version))
    (root / ".arw/learning-policy.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "evaluation_policy_artifact_id": "artifact.policy" + version,
            }
        )
    )
    sample = {
        "schema_version": "arw.learning-sample.v1",
        "heuristic_id": item.heuristic_id,
        "policy_id": "policy.learning",
        "policy_version": version,
        "run_id": run_id,
        "mode": mode,
        "metric": "citation_recall",
        "baseline": 0.4,
        "outcome": 0.7,
        "proposed_action": item.proposed_action,
        "actual_action": "Measured retrieval before changing the judge",
        "reviewer": "author.review" if mode == "human-review" else None,
        "approved": True if mode == "human-review" else None,
    }
    write_accepted(root, "artifact.sample" + version, sample, 120 + int(version))
    return ["artifact.sample" + version]


def qualified(root, service, mode="replay"):
    item, proposed = observe_candidate(root, service)
    samples = evaluation_inputs(root, item, mode)
    evaluated = service.evaluate(item.heuristic_id, samples, request=request(root, 130))
    qualification = service.qualify(item.heuristic_id, request=request(root, 131))
    return item, proposed, evaluated, qualification


def approve(root, item, proposed, qualification, to_scope="project", **overrides):
    body = {
        "action": "promote_heuristic",
        "heuristic_id": item.heuristic_id,
        "heuristic_digest": proposed["content_digest"],
        "qualification_receipt_id": qualification["content_digest"],
        "to_scope": to_scope,
        "status": "APPROVED",
        "reviewer": "author.reviewer",
        **overrides,
    }
    write_accepted(root, "artifact.approval", body, 140)
    return "artifact.approval"


FUNCTIONS = ("problem", "gap", "contribution", "argument", "evidence", "knowledge_boundary")


def venue_exemplar(index, *, access_basis="official_full_text", source_artifact_id="artifact.source", source_sha256=None):
    full = access_basis == "official_full_text"
    return {
        "schema_version": "arw.venue-exemplar.v1",
        "exemplar_id": f"exemplar.synthetic{index}",
        "official_url": f"https://example.test/accepted/{index}",
        "source_sha256": source_sha256 or sha256_hex(SOURCE),
        "source_artifact_id": source_artifact_id,
        "source_review_artifact_id": f"artifact.review{index}",
        "source_reviewer": "synthetic.fixture",
        "accepted_category": "synthetic test paper",
        "accepted_year": 2025,
        "venue_id": "venue.synthetic",
        "domain_id": "domain.synthetic",
        "sections": [
            {"section": f"Section {n}", "locator": f"page {n}", "function": function}
            for n, function in enumerate(FUNCTIONS, 1)
        ] if full else [],
        "figure_roles": ["task example"] if full else [],
        "evidence_forms": ["experiment"] if full else [],
        "observed_patterns": ["bounded result framing"] if full else [],
        "access_basis": access_basis,
    }


def source_review(exemplar):
    return {
        "schema_version": "arw.venue-source-review.v1",
        "review_id": "review." + exemplar["exemplar_id"],
        "source_artifact_id": exemplar["source_artifact_id"],
        "source_sha256": exemplar["source_sha256"],
        "official_url": exemplar["official_url"],
        "doi": exemplar.get("doi"),
        "accepted_category": exemplar["accepted_category"],
        "accepted_year": exemplar["accepted_year"],
        "access_basis": exemplar["access_basis"],
        "reviewer": exemplar["source_reviewer"],
        "decision": "VERIFIED",
    }


@pytest.mark.parametrize(
    ("findings", "expected"),
    [(["supporting", "counterexample"], "FAIL"),
     (["supporting", "supporting", "counterexample"], "PASS")],
)
def test_venue_evidence_counterexample_policy_and_promoted_advice(tmp_path, findings, expected):
    root, service = prepared(tmp_path)
    observation_ids = []
    for index in range(len(findings)):
        source_id = f"artifact.paper{index}"
        source_body = {"synthetic_paper": index}
        write_accepted(root, source_id, source_body, 190 + index)
        artifact_id = f"artifact.venue{index}"
        exemplar = venue_exemplar(
            index, source_artifact_id=source_id,
            source_sha256=sha256_hex(canonical_json_bytes(source_body)),
        )
        write_accepted(root, exemplar["source_review_artifact_id"], source_review(exemplar), 195 + index)
        write_accepted(root, artifact_id, exemplar, 200 + index)
        receipt = service.observe_venue(artifact_id, request=request(root, 210 + index))
        observation_ids.append(receipt["record_id"])
    item = candidate(
        observation_ids[0],
        heuristic_id="heuristic.venue",
        venue_applicability={"venue_id": "venue.synthetic", "domain_id": "domain.synthetic"},
    )
    proposed = service.extract(item, request=request(root, 230))
    policy = {
        "schema_version": "arw.venue-evidence-policy.v1",
        "policy_id": "policy.venue", "version": "1",
        "mode": "venue-evidence", "exemplar_observation_ids": observation_ids,
    }
    write_accepted(root, "artifact.venuepolicy", policy, 231)
    (root / ".arw/learning-policy.json").write_text(json.dumps({
        "enabled": True, "evaluation_policy_artifact_id": "artifact.venuepolicy"
    }))
    sample_ids = []
    for index, finding in enumerate(findings):
        artifact_id = f"artifact.venuesample{index}"
        write_accepted(root, artifact_id, {
            "schema_version": "arw.venue-evidence-sample.v1",
            "heuristic_id": item.heuristic_id,
            "policy_id": "policy.venue", "policy_version": "1",
            "exemplar_observation_id": observation_ids[index],
            "finding": finding, "rationale": "Synthetic reviewer classification",
            "reviewer": "synthetic.fixture",
        }, 240 + index)
        sample_ids.append(artifact_id)
    evaluated = service.evaluate(item.heuristic_id, sample_ids, request=request(root, 250))
    assert evaluated["qualification"] == expected
    assert evaluated["metrics"]["counts"]["counterexample"] == 1
    if expected == "FAIL":
        with pytest.raises(LearningFault, match="failed evaluation"):
            service.qualify(item.heuristic_id, request=request(root, 251))
        return
    qualified_receipt = service.qualify(item.heuristic_id, request=request(root, 251))
    approval = approve(root, item, proposed, qualified_receipt)
    service.promote(item.heuristic_id, consent=True, approval_artifact_id=approval, request=request(root, 252))
    assert service.applicable(item.applicability)["items"] == []
    advice = service.applicable(
        item.applicability, venue_id="venue.synthetic", domain_id="domain.synthetic"
    )["items"]
    assert advice[0]["evidence_counts"] == {"supporting": 2, "counterexample": 1, "unknown": 0}
    assert advice[0]["approved_scope"] == "project"


def test_metadata_only_venue_exemplar_cannot_support_pattern(tmp_path):
    root, service = prepared(tmp_path)
    metadata = venue_exemplar(0, access_basis="official_metadata_only")
    write_accepted(root, metadata["source_review_artifact_id"], source_review(metadata), 259)
    write_accepted(root, "artifact.metadata", metadata, 260)
    observed = service.observe_venue("artifact.metadata", request=request(root, 261))
    item = candidate(observed["record_id"], heuristic_id="heuristic.metadata",
                     venue_applicability={"venue_id": "venue.synthetic", "domain_id": "domain.synthetic"})
    service.extract(item, request=request(root, 262))
    write_accepted(root, "artifact.metapolicy", {
        "schema_version": "arw.venue-evidence-policy.v1", "policy_id": "policy.metadata",
        "version": "1", "mode": "venue-evidence",
        "exemplar_observation_ids": [observed["record_id"]],
    }, 263)
    (root / ".arw/learning-policy.json").write_text(json.dumps({
        "enabled": True, "evaluation_policy_artifact_id": "artifact.metapolicy"
    }))
    write_accepted(root, "artifact.metasample", {
        "schema_version": "arw.venue-evidence-sample.v1",
        "heuristic_id": item.heuristic_id, "policy_id": "policy.metadata",
        "policy_version": "1", "exemplar_observation_id": observed["record_id"],
        "finding": "supporting", "rationale": "Unsupported classification",
        "reviewer": "synthetic.fixture",
    }, 264)
    with pytest.raises(LearningFault, match="metadata-only"):
        service.evaluate(item.heuristic_id, ["artifact.metasample"], request=request(root, 265))


def test_duplicate_venue_paper_alias_cannot_inflate_support(tmp_path):
    root, service = prepared(tmp_path)
    first = venue_exemplar(0)
    first["doi"] = "10.1234/SYNTHETIC"
    write_accepted(root, first["source_review_artifact_id"], source_review(first), 279)
    write_accepted(root, "artifact.firstpaper", first, 280)
    service.observe_venue("artifact.firstpaper", request=request(root, 281))
    duplicate = venue_exemplar(1)
    duplicate["doi"] = "https://doi.org/10.1234/synthetic"
    duplicate["official_url"] = "https://example.test/another-url"
    write_accepted(root, duplicate["source_review_artifact_id"], source_review(duplicate), 2810)
    write_accepted(root, "artifact.duplicatepaper", duplicate, 282)
    with pytest.raises(LearningFault, match="duplicate venue exemplar"):
        service.observe_venue("artifact.duplicatepaper", request=request(root, 283))


def test_exemplar_without_accepted_source_review_is_not_observed(tmp_path):
    root, service = prepared(tmp_path)
    write_accepted(root, "artifact.unreviewedpaper", venue_exemplar(9), 287)
    with pytest.raises(LearningFault, match="accepted artifact reference"):
        service.observe_venue("artifact.unreviewedpaper", request=request(root, 288))


def test_venue_outcome_binds_historical_run_narrative_after_author_change(tmp_path):
    project_root = paper_project(tmp_path)
    register(project_root)
    first = select(project_root, paper_plan())
    run_root = project_root / "runs/one"
    binding = binding_for_start(project_root, run_root)
    initial = paper_run_request(project_root, binding=binding)
    initialize_run(run_root, InitRunRequest.model_validate({
        **initial.model_dump(mode="json"), "journal_layout": "segmented-v1",
        "workflow_definition_id": CORE_WORKFLOW.definition_id,
        "workflow_definition_sha256": CORE_WORKFLOW.sha256,
    }))
    (project_root / ".arw/learning-policy.json").write_text('{"enabled":true}')
    evidence = {"synthetic_outcome": "reviewed by fixture"}
    write_accepted_bound(run_root, "artifact.outcome-evidence", evidence, 284)
    write_accepted_bound(run_root, "artifact.venue-outcome", {
        "schema_version": "arw.venue-outcome.v1",
        "outcome_id": "outcome.synthetic", "venue_id": "venue.synthetic",
        "domain_id": "domain.synthetic", "narrative_sha256": first.sha256,
        "narrative_version": first.version, "heuristic_ids": [],
        "heuristic_use_artifact_ids": [], "outcome": "Synthetic reviewed outcome",
        "evidence_artifact_id": "artifact.outcome-evidence",
        "evidence_digest": sha256_hex(canonical_json_bytes(evidence)),
    }, 285)
    service = ResearchLearningService(project_root, run_root=run_root)
    before = replay_run(run_root).events
    advice = service.phase2_advisories(
        candidate("observation-placeholder").applicability,
        venue_id="venue.synthetic", domain_id="domain.synthetic",
    )
    assert advice["narrative_sha256"] == first.sha256
    assert advice["items"] == [] and advice["narrative_modified"] is False
    assert replay_run(run_root).events == before
    pending = propose(project_root, paper_plan("theory"), expected_sha256=first.sha256,
                      reason="Author revised paper strategy")
    narrative_approve(project_root, proposal_sha256=pending["proposal_sha256"], author_id="author.owner")
    observed = service.observe_venue("artifact.venue-outcome", request=request(run_root, 286))
    assert observed["status"] == "recorded"


def test_phase2_receives_only_governed_promoted_venue_advice(tmp_path):
    project_root = paper_project(tmp_path)
    register(project_root)
    selected = select(project_root, paper_plan())
    run_root = project_root / "runs/one"
    binding = binding_for_start(project_root, run_root)
    initial = paper_run_request(project_root, binding=binding)
    initialize_run(run_root, InitRunRequest.model_validate({
        **initial.model_dump(mode="json"), "journal_layout": "segmented-v1",
        "workflow_definition_id": CORE_WORKFLOW.definition_id,
        "workflow_definition_sha256": CORE_WORKFLOW.sha256,
    }))
    (project_root / ".arw/learning-policy.json").write_text('{"enabled":true}')
    service = ResearchLearningService(project_root, run_root=run_root)
    observations = []
    for index in range(4):
        source_id = f"artifact.phase2source{index}"
        source = {"synthetic_paper": index}
        write_accepted_bound(run_root, source_id, source, 300 + index)
        exemplar = venue_exemplar(
            index, source_artifact_id=source_id,
            source_sha256=sha256_hex(canonical_json_bytes(source)),
        )
        write_accepted_bound(run_root, exemplar["source_review_artifact_id"], source_review(exemplar), 310 + index)
        exemplar_id = f"artifact.phase2exemplar{index}"
        write_accepted_bound(run_root, exemplar_id, exemplar, 320 + index)
        observations.append(service.observe_venue(exemplar_id, request=request(run_root, 330 + index))["record_id"])
    item = candidate(observations[0], heuristic_id="heuristic.phase2",
                     venue_applicability={"venue_id": "venue.synthetic", "domain_id": "domain.synthetic"})
    proposed = service.extract(item, request=request(run_root, 340))
    pending = candidate(observations[0], heuristic_id="heuristic.pending",
                        venue_applicability={"venue_id": "venue.synthetic", "domain_id": "domain.synthetic"})
    service.extract(pending, request=request(run_root, 341))
    # Actual ARS planning CLI must not consume unpromoted candidates.
    unpromoted = _phase2_planner_cli(project_root, run_root, item.applicability, tmp_path)
    assert unpromoted.returncode == 0, unpromoted.stderr
    assert json.loads(unpromoted.stdout)["phase2_venue_context"]["advisories"]["items"] == []
    rejected = candidate(observations[0], heuristic_id="heuristic.rejected",
                         venue_applicability={"venue_id": "venue.synthetic", "domain_id": "domain.synthetic"})
    service.extract(rejected, request=request(run_root, 342))
    service.reject(rejected.heuristic_id, reason="Synthetic counterexample", request=request(run_root, 343))
    policy = {"schema_version": "arw.venue-evidence-policy.v1", "policy_id": "policy.phase2",
              "version": "1", "mode": "venue-evidence", "exemplar_observation_ids": observations}
    write_accepted_bound(run_root, "artifact.phase2policy", policy, 344)
    (project_root / ".arw/learning-policy.json").write_text(json.dumps({
        "enabled": True, "evaluation_policy_artifact_id": "artifact.phase2policy"
    }))
    sample_ids = []
    for index, finding in enumerate(("supporting", "supporting", "counterexample", "unknown")):
        artifact_id = f"artifact.phase2sample{index}"
        write_accepted_bound(run_root, artifact_id, {
            "schema_version": "arw.venue-evidence-sample.v1", "heuristic_id": item.heuristic_id,
            "policy_id": "policy.phase2", "policy_version": "1",
            "exemplar_observation_id": observations[index], "finding": finding,
            "rationale": "Synthetic fixture classification", "reviewer": "synthetic.fixture",
        }, 350 + index)
        sample_ids.append(artifact_id)
    evaluation = service.evaluate(item.heuristic_id, sample_ids, request=request(run_root, 360))
    assert evaluation["qualification"] == "PASS"
    failed = candidate(observations[0], heuristic_id="heuristic.failed",
                       venue_applicability={"venue_id": "venue.synthetic", "domain_id": "domain.synthetic"})
    service.extract(failed, request=request(run_root, 470))
    failed_samples = []
    for index, finding in enumerate(("supporting", "supporting", "counterexample", "counterexample")):
        artifact_id = f"artifact.failedsample{index}"
        write_accepted_bound(run_root, artifact_id, {
            "schema_version": "arw.venue-evidence-sample.v1", "heuristic_id": failed.heuristic_id,
            "policy_id": "policy.phase2", "policy_version": "1",
            "exemplar_observation_id": observations[index], "finding": finding,
            "rationale": "Synthetic counterexample fixture", "reviewer": "synthetic.fixture",
        }, 471 + index)
        failed_samples.append(artifact_id)
    failure = service.evaluate(failed.heuristic_id, failed_samples, request=request(run_root, 475))
    assert failure["qualification"] == "FAIL"
    assert failure["metrics"]["counts"] == {"supporting": 2, "counterexample": 2, "unknown": 0}
    with pytest.raises(LearningFault, match="failed evaluation cannot qualify"):
        service.qualify(failed.heuristic_id, request=request(run_root, 476))
    with pytest.raises(LearningFault, match="promotion requires qualified status"):
        service.promote(failed.heuristic_id, consent=True, approval_artifact_id="artifact.phase2approval",
                        request=request(run_root, 477))
    qualification = service.qualify(item.heuristic_id, request=request(run_root, 361))
    approval_body = {
        "action": "promote_heuristic", "heuristic_id": item.heuristic_id,
        "heuristic_digest": proposed["content_digest"],
        "qualification_receipt_id": qualification["content_digest"],
        "to_scope": "project", "status": "APPROVED", "reviewer": "synthetic.fixture",
    }
    write_accepted_bound(run_root, "artifact.phase2approval", approval_body, 362)
    service.promote(item.heuristic_id, consent=True,
                    approval_artifact_id="artifact.phase2approval", request=request(run_root, 363))
    before_events = replay_run(run_root).events
    before_narrative = narrative_current(project_root)
    advice = service.phase2_advisories(
        item.applicability, venue_id="venue.synthetic", domain_id="domain.synthetic"
    )
    assert advice["narrative_sha256"] == selected.sha256
    assert advice["narrative_modified"] is False and advice["executable"] is False
    assert len(advice["items"]) == 1
    only = advice["items"][0]
    assert only["heuristic_id"] == item.heuristic_id
    assert only["approved_scope"] == "project"
    assert only["evidence_counts"] == {"supporting": 2, "counterexample": 1, "unknown": 1}
    assert only["evaluated_supporting"] == observations[:2]
    assert only["evaluated_counterexample"] == [observations[2]]
    assert only["evaluated_unknown"] == [observations[3]]
    assert service.phase2_advisories(item.applicability, venue_id="venue.synthetic",
                                    domain_id="domain.other")["items"] == []
    assert replay_run(run_root).events == before_events
    assert narrative_current(project_root) == before_narrative
    planned = _phase2_planner_cli(project_root, run_root, item.applicability, tmp_path)
    assert planned.returncode == 0, planned.stderr
    routed = json.loads(planned.stdout)
    context = routed["phase2_venue_context"]
    assert context["advisories"] == advice
    assert context["applicability_sha256"] == sha256_hex(canonical_json_bytes(item.applicability.model_dump(mode="json")))
    architect = next(agent for agent in routed["agent_team_plan"] if agent["agent"] == "structure_architect_agent")
    assert architect["task_context"]["phase2_venue_context"] == context
    role_items = architect["task_context"]["phase2_venue_context"]["advisories"]["items"]
    assert [lesson["heuristic_id"] for lesson in role_items] == [item.heuristic_id]
    assert role_items[0]["approved_scope"] == "project"
    assert role_items[0]["evidence_counts"] == {"supporting": 2, "counterexample": 1, "unknown": 1}
    repository = Path(__file__).resolve().parents[2]
    assert Path(context["runtime_sources"]["core"]).resolve() == repository / "src/arw/composition.py"
    assert Path(context["runtime_sources"]["learning"]).resolve() == repository / "extensions/research-learning/src/arw_research_learning/service.py"
    assert context["executable"] is False and context["author_choice_required"] is True
    assert replay_run(run_root).events == before_events
    assert narrative_current(project_root) == before_narrative
    unsafe_input = tmp_path / "phase2-conditions-alias.json"
    unsafe_input.symlink_to(tmp_path / "phase2-conditions.json")
    unsafe = _phase2_planner_cli(project_root, run_root, item.applicability, tmp_path,
                                applicability_override=unsafe_input)
    assert unsafe.returncode == 2
    assert json.loads(unsafe.stdout)["code"] == "source-locator-invalid"
    # Even a containing directory with copied fixture identity is the wrong project.
    outer = project_root.parent
    (outer / ".arw").mkdir(exist_ok=True)
    (outer / ".arw/project.json").write_bytes((project_root / ".arw/project.json").read_bytes())
    mismatched = _phase2_planner_cli(outer, run_root, item.applicability, tmp_path)
    assert mismatched.returncode == 2
    assert "different selected project" in json.loads(mismatched.stdout)["message"]

    evidence = {"synthetic_outcome": "no decision yet"}
    write_accepted_bound(run_root, "artifact.bad-outcome-evidence", evidence, 364)
    write_accepted_bound(run_root, "artifact.incomplete-use", {
        "schema_version": "arw.learning-decision.v1",
        "heuristic_id": item.heuristic_id,
        "promotion_event_id": service.inspect(item.heuristic_id)["accepted_ledger_event_id"],
        "author": "synthetic.fixture",
    }, 365)
    write_accepted_bound(run_root, "artifact.bad-venue-outcome", {
        "schema_version": "arw.venue-outcome.v1", "outcome_id": "outcome.incomplete",
        "venue_id": "venue.synthetic", "domain_id": "domain.synthetic",
        "narrative_sha256": selected.sha256, "narrative_version": selected.version,
        "heuristic_ids": [item.heuristic_id],
        "heuristic_use_artifact_ids": ["artifact.incomplete-use"],
        "outcome": "Unsupported learning claim",
        "evidence_artifact_id": "artifact.bad-outcome-evidence",
        "evidence_digest": sha256_hex(canonical_json_bytes(evidence)),
    }, 366)
    with pytest.raises(LearningFault, match="heuristic-use evidence"):
        service.observe_venue("artifact.bad-venue-outcome", request=request(run_root, 367))
    narrative_path = project_root / ".arw/narrative/events.jsonl"
    original_history = narrative_path.read_bytes()
    narrative_path.write_bytes(original_history.splitlines(keepends=True)[0])
    missing = _phase2_planner_cli(project_root, run_root, item.applicability, tmp_path)
    assert missing.returncode == 2
    assert json.loads(missing.stdout)["code"] == "missing_selection"
    narrative_path.write_bytes(original_history)
    revised = propose(project_root, paper_plan("theory"), expected_sha256=selected.sha256,
                      reason="Fixture author changes the narrative after planning")
    narrative_approve(project_root, proposal_sha256=revised["proposal_sha256"], author_id="synthetic.fixture")
    stale = _phase2_planner_cli(project_root, run_root, item.applicability, tmp_path)
    assert stale.returncode == 2
    assert json.loads(stale.stdout)["code"] == "stale_narrative"


def _phase2_planner_cli(project_root, run_root, conditions, tmp_path, *, applicability_override=None):
    """Synthetic governed fixture; no approval or selection of the public corpus."""
    repository = Path(__file__).resolve().parents[2]
    planner = repository / "skills/academic-research-suite/codex/scripts/ars_codex_full_runtime.py"
    applicability = tmp_path / "phase2-conditions.json"
    applicability.write_bytes(canonical_json_bytes(conditions.model_dump(mode="json")))
    environment = {**os.environ, "ARS_CODEX_FULL_RUNTIME": "1", "ARS_CODEX_AGENT_TEAM": "1"}
    for key in ("ARW_PLUGIN_ROOT", "ARW_PLUGIN_MANIFEST"):
        environment.pop(key, None)
    environment["PYTHONPATH"] = os.pathsep.join([
        str(repository / "src"),
        *(str(source) for source in (repository / "extensions").glob("*/src")),
    ])
    return subprocess.run([
        sys.executable, str(planner), "ars-outline",
        "--arw-project-root", str(project_root), "--arw-run-root", str(run_root),
        "--venue-id", "venue.synthetic", "--domain-id", "domain.synthetic",
        "--applicability-file", str(applicability_override or applicability),
    ], cwd=repository, env=environment, capture_output=True, text=True, check=False)


def test_legacy_style_clause_is_rebuildable_unverified_candidate(tmp_path):
    root, service = prepared(tmp_path)
    profile = {
        "schema_version": "1.0",
        "sources": {"paper.synthetic": {"url": "https://example.test/paper"}},
        "style_learning": {
            "exemplars": [{"source_id": "paper.synthetic", "observed_patterns": ["Use a bounded example"]}],
            "consensus_argument_slots": ["Explain the evidence boundary"],
            "artifact_contract": {"table_density_rule": "Four to eight rows is advisory"},
        },
    }
    write_accepted(root, "artifact.legacyprofile", profile, 270)
    observed = service.observe_venue("artifact.legacyprofile", request=request(root, 271))
    migrated = service.migrate_style_candidate({
        "legacy_observation_id": observed["record_id"],
        "draft_id": "paper.synthetic:0",
        "heuristic_id": "heuristic.legacy",
        "domain": "synthetic domain",
        "applicability": candidate(observed["record_id"]).applicability.model_dump(mode="json"),
        "venue_applicability": {"venue_id": "venue.synthetic", "domain_id": "domain.synthetic"},
        "legacy_guidance_review": {
            "nonmandatory": True,
            "counterexample_needs": "Review genuine accepted papers with different structures",
            "exception_conditions": ["Different task or page budget"],
        },
    }, request=request(root, 272))
    assert migrated["status"] == "candidate"
    before = service.inspect("heuristic.legacy")
    assert before["migration_status"] == "unverified_legacy"
    assert before["supporting_observation_ids"] == []
    assert before["unknown"][0]["observation_id"] == observed["record_id"]
    service.rebuild()
    assert service.inspect("heuristic.legacy") == before
    assert service.applicable(candidate(observed["record_id"]).applicability)["items"] == []


@pytest.mark.parametrize(
    "mode", ["replay", "held-out", "shadow", "A-B", "human-review", "benchmark"]
)
def test_actual_evaluation_and_project_promotion(tmp_path, mode):
    root, service = prepared(tmp_path)
    item, proposed, evaluated, qualification = qualified(root, service, mode)
    assert evaluated["metrics"]["mean_delta"] == pytest.approx(0.3)
    approval = approve(root, item, proposed, qualification)
    promoted = service.promote(
        item.heuristic_id,
        consent=True,
        approval_artifact_id=approval,
        request=request(root, 141),
    )
    assert promoted["status"] == "promoted"
    inspected = service.inspect(item.heuristic_id)
    assert inspected["evaluation"]["mode"] == mode
    assert inspected["evaluation"]["workflow_modified"] is False
    applicable = service.applicable(item.applicability)
    assert applicable["items"][0]["author_choice_required"]
    assert "unmeasured" in applicable["items"][0]["outcome"]
    before = service.list()
    (root / ".arw/learning/index.sqlite3").unlink()
    service.rebuild()
    assert service.list() == before
    assert replay_run(root).events[-1].schema_version == "1.3.0"
    with sqlite3.connect(root / ".arw/learning/index.sqlite3") as db:
        assert (
            db.execute("SELECT COUNT(*) FROM heuristic_promotions").fetchone()[0] == 1
        )


def test_disabled_historical_inspection_and_dedup(tmp_path):
    root, service = prepared(tmp_path)
    item, _proposed = observe_candidate(root, service)
    source = next(
        e for e in replay_run(root).events if e.event_type == "artifact.accepted"
    )
    duplicate = service.observe(source.event_id, request=request(root, 102))
    assert duplicate["duplicate_of"] == item.supporting_observation_ids[0]
    (root / ".arw/learning-policy.json").write_text('{"enabled":false}')
    events = replay_run(root).events
    with pytest.raises(LearningDisabled):
        service.reject(item.heuristic_id, reason="disabled", request=request(root, 103))
    assert replay_run(root).events == events
    assert service.inspect(item.heuristic_id)["status"] == "candidate"


def test_policy_change_requires_reevaluation(tmp_path):
    root, service = prepared(tmp_path)
    item, proposed, _evaluated, qualification = qualified(root, service)
    evaluation_inputs(root, item, version="2")
    approval = approve(root, item, proposed, qualification)
    with pytest.raises(ReevaluationRequired):
        service.promote(
            item.heuristic_id,
            consent=True,
            approval_artifact_id=approval,
            request=request(root, 141),
        )
    service.evaluate(
        item.heuristic_id, ["artifact.sample2"], request=request(root, 142)
    )
    service.qualify(item.heuristic_id, request=request(root, 143))


def test_rejection_and_successor(tmp_path):
    root, service = prepared(tmp_path)
    item, _ = observe_candidate(root, service)
    service.reject(
        item.heuristic_id, reason="Insufficient coverage", request=request(root, 102)
    )
    with pytest.raises(LearningFault, match="successor"):
        service.promote(
            item.heuristic_id,
            consent=True,
            approval_artifact_id="missing",
            request=request(root, 103),
        )
    successor = candidate(
        item.supporting_observation_ids[0],
        heuristic_id="heuristic.next",
        supersedes=item.heuristic_id,
    )
    service.extract(successor, request=request(root, 104))
    assert service.inspect(item.heuristic_id)["status"] == "superseded"
    assert service.inspect(successor.heuristic_id)["status"] == "candidate"


def test_purge_preserves_hashchain(tmp_path):
    root, service = prepared(tmp_path)
    item, proposed = observe_candidate(root, service)
    digest = proposed["content_digest"]
    write_accepted(
        root,
        "artifact.retention",
        {"action": "purge_learning", "content_digest": digest},
        110,
    )
    before = replay_run(root).events
    service.purge(
        digest,
        consent=True,
        authorization_artifact_id="artifact.retention",
        request=request(root, 111),
    )
    assert replay_run(root).events == before
    assert not (root / body_path(digest)).exists()
    with pytest.raises(BodyUnavailable):
        service.inspect(item.heuristic_id)
    assert service.list()["items"][0]["body_recoverable"] is False


def test_exact_command_retries_and_conflicts(tmp_path):
    root, service = prepared(tmp_path)
    item, proposed = observe_candidate(root, service)
    samples = evaluation_inputs(root, item)
    evaluated_request = request(root, 130)
    service.evaluate(item.heuristic_id, samples, request=evaluated_request)
    assert service.evaluate(item.heuristic_id, samples, request=evaluated_request)[
        "idempotent"
    ]
    qualify_request = request(root, 131)
    qualification = service.qualify(item.heuristic_id, request=qualify_request)
    assert service.qualify(item.heuristic_id, request=qualify_request)["idempotent"]
    approval = approve(root, item, proposed, qualification)
    promote_request = request(root, 141)
    service.promote(
        item.heuristic_id,
        consent=True,
        approval_artifact_id=approval,
        request=promote_request,
    )
    before = replay_run(root).events
    assert service.promote(
        item.heuristic_id,
        consent=True,
        approval_artifact_id=approval,
        request=promote_request,
    )["idempotent"]
    assert replay_run(root).events == before
    with pytest.raises(LearningFault, match="changes"):
        service.promote(
            item.heuristic_id,
            to_scope="domain",
            consent=True,
            approval_artifact_id=approval,
            request=promote_request,
        )


@pytest.mark.parametrize(
    "boundary", ["files_durable", "event_durable", "projection_updated"]
)
def test_killed_writer_recovers_exact_retry(tmp_path, boundary):
    import subprocess
    import sys

    root, service = prepared(tmp_path)
    source = next(
        e for e in replay_run(root).events if e.event_type == "artifact.accepted"
    )
    req = request(root, 100)
    script = """import os,signal,sys
from arw_research_learning.service import ResearchLearningService
from arw.kernel.state.models import RuntimeCommandRequest
from pathlib import Path
root=Path(sys.argv[1])
def boundary(point):
    if point==sys.argv[2]: os.kill(os.getpid(),signal.SIGKILL)
service=ResearchLearningService(root,run_root=root,boundary=boundary)
service.observe(sys.argv[3],request=RuntimeCommandRequest.model_validate_json(sys.argv[4]))
"""
    process = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(root),
            boundary,
            source.event_id,
            req.model_dump_json(),
        ],
        capture_output=True,
        check=False,
    )
    assert process.returncode == -9, process.stderr.decode()
    result = service.observe(source.event_id, request=req)
    assert result["accepted"]
    assert (
        sum(
            e.event_type == "learning_observation_recorded"
            for e in replay_run(root).events
        )
        == 1
    )


def test_privacy_unknown_vocabulary_and_untrusted_import(tmp_path):
    from pydantic import ValidationError

    from arw.kernel.core.privacy import SecretRejected
    from arw.kernel.state.research_learning import LearningObservation

    root, service = prepared(tmp_path)
    item, _ = observe_candidate(root, service)
    before = replay_run(root).events
    with pytest.raises(SecretRejected):
        service.extract(
            candidate(
                item.supporting_observation_ids[0],
                heuristic_id="heuristic.secret",
                proposed_action="-----BEGIN PRIVATE KEY-----\nsecret bytes",
            ),
            request=request(root, 102),
        )
    assert replay_run(root).events == before
    with pytest.raises(ValidationError):
        LearningObservation.model_validate_json(
            '{"observation_kind":"full_transcript"}'
        )
    imported = item.model_dump(mode="json") | {
        "heuristic_id": "heuristic.import",
        "status": "promoted",
        "trust": "verified",
        "accepted_ledger_event_id": "pretend",
    }
    service.import_heuristic(imported, request=request(root, 103))
    assert service.inspect("heuristic.import")["status"] == "candidate"
    assert service.inspect("heuristic.import")["trust"] == "unreviewed"


def test_confidence_and_missing_consent_do_not_authorize(tmp_path):
    root, service = prepared(tmp_path)
    item, proposed, _evaluated, qualification = qualified(root, service)
    approval = approve(root, item, proposed, qualification)
    with pytest.raises(LearningFault, match="consent"):
        service.promote(
            item.heuristic_id,
            consent=False,
            approval_artifact_id=approval,
            request=request(root, 141),
        )
    with pytest.raises(LearningFault):
        service.promote(
            item.heuristic_id,
            to_scope="global",
            consent=True,
            approval_artifact_id=approval,
            request=request(root, 142),
        )


def test_cli_and_absent_capability(tmp_path, capsys, monkeypatch):
    from arw import composition
    from arw.cli import main
    from arw.kernel.capabilities import CapabilityUnavailable

    root, _service = prepared(tmp_path)
    event = next(
        e for e in replay_run(root).events if e.event_type == "artifact.accepted"
    )
    req = request(root, 100)
    request_path = root / "learning-request.json"
    request_path.write_text(req.model_dump_json())
    assert (
        main(
            [
                "learn",
                "observe",
                "--project-root",
                str(root),
                "--run-root",
                str(root),
                "--event-id",
                event.event_id,
                "--request",
                str(request_path),
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["status"] == "recorded"
    assert (
        main(["learn", "evolve", "heuristic.none", "--project-root", str(root)]) == 65
    )
    assert (
        json.loads(capsys.readouterr().out)["follow_up"] == "research-workflow-evolver"
    )
    original = composition.import_module

    def absent(name):
        if name.startswith("arw_research_learning"):
            raise ImportError("disabled")
        return original(name)

    monkeypatch.setattr(composition, "import_module", absent)
    with pytest.raises(CapabilityUnavailable):
        composition.default_router().resolve("research.learning.observe")


def test_unknown_evidence_and_formula(tmp_path):
    root, service = prepared(tmp_path)
    source = next(
        e for e in replay_run(root).events if e.event_type == "artifact.accepted"
    )
    first = service.observe(source.event_id, request=request(root, 100))
    write_accepted(
        root,
        "artifact.unknown",
        {"outcome": "No comparable baseline was measured"},
        101,
    )
    second = service.observe(
        replay_run(root).events[-1].event_id, request=request(root, 102)
    )
    item = candidate(
        first["record_id"],
        unknown=[
            {
                "observation_id": second["record_id"],
                "rationale": "No comparable baseline was measured in this receipt",
            }
        ],
    )
    service.extract(item, request=request(root, 103))
    samples = evaluation_inputs(root, item)
    # A new accepted policy explicitly defines the advisory confidence formula.
    policy = json.loads((root / "artifact.policy1.json").read_text())
    policy.update(
        use_confidence=True, formula_id="supporting-fraction", formula_version="1"
    )
    write_accepted(root, "artifact.formula-policy", policy, 124)
    (root / ".arw/learning-policy.json").write_text(
        json.dumps(
            {
                "enabled": True,
                "evaluation_policy_artifact_id": "artifact.formula-policy",
            }
        )
    )
    service.evaluate(item.heuristic_id, samples, request=request(root, 130))
    receipt = service.inspect(item.heuristic_id)["evaluation"]
    assert receipt["confidence"]["inputs"] == {"supporting": 1, "counterexample": 0}
    assert receipt["unknown"][0]["rationale"].startswith("No comparable")
    assert receipt["counterexample"] == []


def test_lesson_consumed_by_author_choice_without_invented_improvement(tmp_path):
    root, service = prepared(tmp_path)
    item, proposed, _, qualification = qualified(root, service)
    approval = approve(root, item, proposed, qualification)
    promoted = service.promote(
        item.heuristic_id,
        consent=True,
        approval_artifact_id=approval,
        request=request(root, 141),
    )
    suggested = service.applicable(item.applicability)["items"][0]
    decision = {
        "schema_version": "arw.learning-decision.v1",
        "heuristic_id": item.heuristic_id,
        "promotion_event_id": promoted["event_id"],
        "applicability": item.applicability.model_dump(mode="json"),
        "author": "research.author",
        "chosen_action": "Expand primary-source retrieval before changing judges",
        "outcome": {"measured": False, "value": None},
    }
    write_accepted(root, "artifact.decision", decision, 142)
    context = service.decision_context(item.heuristic_id, "artifact.decision")
    assert context["suggested_action"] == suggested["suggested_action"]
    assert context["outcome"] == {"measured": False, "value": None}
    write_accepted(
        root,
        "artifact.bad-decision",
        decision | {"outcome": {"measured": False, "value": 0.3}},
        143,
    )
    with pytest.raises(LearningFault, match="unmeasured"):
        service.decision_context(item.heuristic_id, "artifact.bad-decision")


def test_failed_evaluation_and_heldout_subset(tmp_path):
    root, service = prepared(tmp_path)
    item, _ = observe_candidate(root, service)
    samples = evaluation_inputs(root, item, mode="held-out", minimum_delta=0.5)
    result = service.evaluate(item.heuristic_id, samples, request=request(root, 130))
    assert result["qualification"] == "FAIL"
    with pytest.raises(LearningFault, match="failed"):
        service.qualify(item.heuristic_id, request=request(root, 131))
    policy = json.loads((root / "artifact.policy1.json").read_text())
    policy["run_subset"] = ["run-00000000-0000-4000-8000-000000000088"]
    write_accepted(root, "artifact.other-subset", policy, 132)
    (root / ".arw/learning-policy.json").write_text(
        json.dumps(
            {"enabled": True, "evaluation_policy_artifact_id": "artifact.other-subset"}
        )
    )
    with pytest.raises(LearningFault, match="subset"):
        service.evaluate(item.heuristic_id, samples, request=request(root, 133))


def test_project_run_privacy_and_corrupted_source(tmp_path):
    root, service = prepared(tmp_path)
    item, _ = observe_candidate(root, service)
    (root / ".arw/learning-policy.json").write_text(
        json.dumps({"enabled": True, "disabled_run_ids": [replay_run(root).run_id]})
    )
    with pytest.raises(LearningDisabled):
        service.reject(
            item.heuristic_id, reason="disabled run", request=request(root, 102)
        )
    (root / ".arw/learning-policy.json").write_text('{"enabled":true}')
    (root / "source.txt").write_text("Tampered source")
    with pytest.raises(LearningFault, match="digest"):
        service.inspect(item.heuristic_id)
    outside = tmp_path / "other"
    outside.mkdir()
    with pytest.raises(LearningFault):
        ResearchLearningService(outside, run_root=root)


def test_symlink_and_evaluation_retention(tmp_path):
    root, service = prepared(tmp_path)
    item, _, evaluated, _ = qualified(root, service)
    digest = evaluated["content_digest"]
    write_accepted(
        root,
        "artifact.retention",
        {"action": "purge_learning", "content_digest": digest},
        140,
    )
    before = replay_run(root).events
    service.purge(
        digest,
        consent=True,
        authorization_artifact_id="artifact.retention",
        request=request(root, 141),
    )
    assert replay_run(root).events == before
    with pytest.raises(BodyUnavailable):
        service.inspect(item.heuristic_id)
    path = root / ".arw/learning/index.sqlite3"
    path.unlink()
    outside = tmp_path / "outside.sqlite3"
    outside.write_bytes(b"untouched")
    path.symlink_to(outside)
    with pytest.raises(LearningFault, match="unsafe"):
        service.rebuild()
    assert outside.read_bytes() == b"untouched"


def test_broader_promotion_requires_reviewed_transfer_receipt(tmp_path):
    root, service = prepared(tmp_path)
    item, proposed, _, qualification = qualified(root, service)
    transfer = {
        "project_id": "project.independent",
        "run_id": "run-00000000-0000-4000-8000-000000000088",
        "source_digest": "a" * 64,
        "evaluation_receipt_id": "b" * 64,
        "reviewer": "external.review",
    }
    approval = approve(
        root,
        item,
        proposed,
        qualification,
        to_scope="domain",
        allow_cross_project=True,
        cross_project_evidence=[transfer],
    )
    result = service.promote(
        item.heuristic_id,
        to_scope="domain",
        consent=True,
        approval_artifact_id=approval,
        request=request(root, 141),
    )
    assert result["accepted"]
    event = replay_run(root).events[-1]
    assert event.payload.supporting_projects == [
        "project.independent",
        "project.learning",
    ]
    assert service.inspect(item.heuristic_id)["scope"] == "domain"


def test_v2_capsule_observation_rebuild_and_duplicate_pdf(tmp_path):
    from tests.unit.test_venue_learning import capsule_v2_documents
    root, service = prepared(tmp_path)
    capsule, exemplar, review = capsule_v2_documents()
    write_accepted(root, exemplar["source_artifact_id"], capsule, 7001)
    write_accepted(root, exemplar["source_review_artifact_id"], review, 7002)
    write_accepted(root, "artifact.annotation", exemplar, 7003)
    observed = service.observe_venue("artifact.annotation", request=request(root, 7004))
    assert observed["record_id"]
    before = service.list()
    (root / ".arw/learning/index.sqlite3").unlink()
    service.rebuild()
    assert service.list() == before
    # Same PDF, distinct retained capsule/title/URL: still one independent source.
    capsule = {**capsule, "title": "Second capsule", "official_url": "https://example.test/duplicate"}
    exemplar = {**exemplar, "exemplar_id": "exemplar.duplicate", "official_url": capsule["official_url"],
                "source_artifact_id": "artifact.duplicate", "source_review_artifact_id": "artifact.duplicatereview",
                "source_sha256": sha256_hex(canonical_json_bytes(capsule))}
    review = {**review, "official_url": capsule["official_url"], "source_artifact_id": exemplar["source_artifact_id"],
              "source_sha256": exemplar["source_sha256"]}
    write_accepted(root, exemplar["source_artifact_id"], capsule, 7005)
    write_accepted(root, exemplar["source_review_artifact_id"], review, 7006)
    write_accepted(root, "artifact.duplicateannotation", exemplar, 7007)
    with pytest.raises(LearningFault, match="duplicate venue exemplar"):
        service.observe_venue("artifact.duplicateannotation", request=request(root, 7008))


def test_v2_capsule_annotation_mismatch_fails_before_observation(tmp_path):
    from tests.unit.test_venue_learning import capsule_v2_documents
    root, service = prepared(tmp_path)
    capsule, exemplar, review = capsule_v2_documents()
    exemplar = {**exemplar, "figure_roles": ["Invented capsule-unbound figure"]}
    write_accepted(root, exemplar["source_artifact_id"], capsule, 7101)
    write_accepted(root, exemplar["source_review_artifact_id"], review, 7102)
    write_accepted(root, "artifact.annotation", exemplar, 7103)
    revision = replay_run(root).revision
    with pytest.raises(LearningFault, match="capsule provenance mismatch"):
        service.observe_venue("artifact.annotation", request=request(root, 7104))
    assert replay_run(root).revision == revision


def test_v2_pdf_digest_deduplicates_v1_retained_source(tmp_path):
    from tests.unit.test_venue_learning import capsule_v2_documents
    root, service = prepared(tmp_path)
    first = venue_exemplar(0)
    write_accepted(root, first["source_review_artifact_id"], source_review(first), 7201)
    write_accepted(root, "artifact.v1annotation", first, 7202)
    service.observe_venue("artifact.v1annotation", request=request(root, 7203))
    capsule, exemplar, review = capsule_v2_documents()
    capsule["provenance"]["pdf_sha256"] = sha256_hex(SOURCE)
    # The helper fixture shares provenance values across these records.
    digest = sha256_hex(canonical_json_bytes(capsule))
    exemplar["source_sha256"] = review["source_sha256"] = digest
    write_accepted(root, exemplar["source_artifact_id"], capsule, 7204)
    write_accepted(root, exemplar["source_review_artifact_id"], review, 7205)
    write_accepted(root, "artifact.v2annotation", exemplar, 7206)
    with pytest.raises(LearningFault, match="duplicate venue exemplar"):
        service.observe_venue("artifact.v2annotation", request=request(root, 7207))


def test_v2_accepted_author_survey_evaluates_without_method_experiment(tmp_path):
    from tests.unit.test_venue_learning import survey_v2_documents
    root, service = prepared(tmp_path)
    capsule, exemplar, review = survey_v2_documents()
    exemplar["venue_id"] = "venue.ieee-tkde"
    write_accepted(root, exemplar["source_artifact_id"], capsule, 7301)
    write_accepted(root, exemplar["source_review_artifact_id"], review, 7302)
    write_accepted(root, "artifact.surveyannotation", exemplar, 7303)
    observed = service.observe_venue("artifact.surveyannotation", request=request(root, 7304))
    item = candidate(observed["record_id"], heuristic_id="heuristic.survey",
        venue_applicability={"venue_id": "venue.ieee-tkde", "domain_id": "domain.fixture"},
        proposed_action="Consider an explicit literature taxonomy; descriptive and nonmandatory")
    service.extract(item, request=request(root, 7305))
    write_accepted(root, "artifact.surveypolicy", {
        "schema_version": "arw.venue-evidence-policy.v1", "policy_id": "policy.survey", "version": "1",
        "mode": "venue-evidence", "exemplar_observation_ids": [observed["record_id"]]}, 7306)
    (root / ".arw/learning-policy.json").write_text(json.dumps({"enabled": True, "evaluation_policy_artifact_id": "artifact.surveypolicy"}))
    write_accepted(root, "artifact.surveysample", {
        "schema_version": "arw.venue-evidence-sample.v1", "heuristic_id": item.heuristic_id,
        "policy_id": "policy.survey", "policy_version": "1", "exemplar_observation_id": observed["record_id"],
        "finding": "supporting", "rationale": "Synthetic taxonomy and literature comparison; no new experiment asserted", "reviewer": "agent.fixture"}, 7307)
    result = service.evaluate(item.heuristic_id, ["artifact.surveysample"], request=request(root, 7308))
    assert result["qualification"] == "PASS"
    assert service.inspect(item.heuristic_id)["status"] == "evaluated"
    assert service.applicable(item.applicability, venue_id="venue.ieee-tkde", domain_id="domain.fixture")["items"] == []
    before = service.list()
    service.rebuild()
    assert service.list() == before
