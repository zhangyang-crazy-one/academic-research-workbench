"""Evidence-backed learning lifecycle, explicit authority, and recovery boundaries."""

import json
import sqlite3

import pytest
from arw_research_learning.service import ResearchLearningService
from arw_research_learning.store import (
    LearningDisabled,
    LearningFault,
    ReevaluationRequired,
    body_path,
)

from arw.kernel.core.canonical import canonical_json_bytes
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.research_records import BodyUnavailable, publish_once
from arw.kernel.state.research_learning import HeuristicInput

from .test_precise_source_locators import accept, seed
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
