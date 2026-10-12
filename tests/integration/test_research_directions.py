"""Offline original-contract composition; candidates never become science gates."""

import json
import shutil
import uuid
from copy import deepcopy
from pathlib import Path

import pytest

from arw.cli import main
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import replay_run
from arw.kernel.state.accepted_ref import ParentArtifactRef
from arw.kernel.state.models import ArtifactAcceptanceRequest, RuntimeCommandRequest
from arw.research_directions import (
    DirectionError,
    bind,
    check,
    inspect_package,
    load_package,
    prepare_definition,
    prepare_intake,
    read_document,
    seal_package,
)
from arw.research_startup import load_plan, start

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "examples/research-directions/computational-pilot/package.json"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))
    return path


def runtime_request(run):
    replay = replay_run(run)
    return RuntimeCommandRequest(
        schema_version="1.0.0",
        run_id=replay.run_id,
        event_id=f"evt-{uuid.uuid4()}",
        command_id=f"cmd-{uuid.uuid4()}",
        expected_revision=replay.revision,
        occurred_at="2026-10-12T01:00:00Z",
        actor_id="parent.synthetic",
        actor_role="parent_control_plane",
    )


def accept(run, path, artifact_id="artifact.synthetic"):
    raw = path.read_bytes()
    request = ArtifactAcceptanceRequest(
        **runtime_request(run).model_dump(),
        artifact_id=artifact_id,
        artifact_kind="research-evidence",
        media_type="application/json",
        content_path=path.relative_to(run).as_posix(),
        content_sha256=sha256_hex(raw),
        base_revision=replay_run(run).revision,
        consumed_sha256=[],
    )
    result = RuntimeCommandService(run).accept_artifact(request)
    assert result.accepted, result
    return reference(run, replay_run(run).events[-1])


def reference(run, event):
    plan = load_plan(run.parents[3])
    return ParentArtifactRef(
        project_id=plan.project_id,
        run_id=plan.request.run_id,
        run_manifest_sha256=sha256_hex((run / "run-manifest.json").read_bytes()),
        artifact_id=event.payload.artifact_id,
        accepting_event_id=event.event_id,
        accepting_event_sha256=event.event_sha256,
        content_sha256=event.payload.artifact_sha256,
    )


def definition():
    return {
        "schema_version": "arw.operationalization.v1",
        "definition_id": "definition.local-boundary",
        "sources": [],
        "author_interpretation": "Candidate contextual revision, not a philosophical equivalence.",
        "rival_explanations": ["Extra context rather than conceptual understanding."],
        "local_definition": "Change an answer after observing counterexamples.",
        "measured_object": "Recorded synthetic answers",
        "metric_definition": "CSV mean score",
        "why_relevant": "Narrow behavioral proxy only.",
        "alternative_measurements": ["Human annotated explanatory consistency."],
        "confounders": ["Training leakage"],
        "refuting_observations": ["Held-out advantage disappears with a sham."],
        "cannot_conclude": ["Human experience alignment."],
    }


@pytest.fixture
def project(tmp_path):
    start(tmp_path, direction="修正对世界的理解", ars_project_ref="ars.synthetic")
    run = tmp_path / load_plan(tmp_path).run_relative
    return tmp_path, run


def branches(tmp_path, *, adopted=True):
    # These are the original bundled validators, not an adapter reimplementation.
    import sys

    tools = ROOT / "skills/academic-research-suite/ars/scripts"
    sys.path.insert(0, str(tools))
    from inquiry_branch_ledger import append_event, new_ledger

    profile = load_package(PACKAGE).profile
    ledger = new_ledger("ars.synthetic", profile)
    payload = {
        "parent_id": None,
        "statement": "Revise understanding from contrary evidence.",
        "assumptions": [],
        "evidence_sought": [],
        "reopen_conditions": [],
        "downstream_refs": [],
    }
    ledger = append_event(
        ledger,
        {
            "recorded_at": "2026-10-12T00:00:00Z",
            "actor": "author",
            "kind": "branch_created",
            "branch_id": "transfer",
            "payload": payload,
        },
        [profile],
        expected_project_ref="ars.synthetic",
    )
    if not adopted:
        ledger = append_event(
            ledger,
            {
                "recorded_at": "2026-10-12T00:01:00Z",
                "actor": "ai",
                "kind": "facet_surfaced",
                "branch_id": "candidate",
                "payload": {
                    "parent_id": "transfer",
                    "surfaced_text": "Possible alignment proxy",
                },
            },
            [profile],
            expected_project_ref="ars.synthetic",
        )
    return write(tmp_path / "branches.json", ledger)


def statuses(report):
    return {r["check"]: r["status"] for r in report["checks"]}


def test_both_original_profile_families_and_pure_data_bounds(tmp_path):
    theory = inspect_package(
        ROOT / "examples/research-directions/semantics-llm/package.json"
    )
    assert theory["stage_map"]["methodology"]["state"] == "intentionally_absent"
    assert theory["stage_map"]["drafting"]["state"] == "unresolved_fit"
    assert theory["hypothesis_state"] == "candidate_not_author_adopted"
    assert inspect_package(PACKAGE)["scientific_status"] == "not_evaluated"
    value = json.loads(PACKAGE.read_text())
    value["command"] = "touch /tmp/forbidden"
    with pytest.raises(ValueError):
        seal_package(value)
    value.pop("command")
    value["scope"] = "altered"
    with pytest.raises(DirectionError, match="digest"):
        load_package(write(tmp_path / "bad.json", value))
    (tmp_path / "linked").symlink_to(PACKAGE)
    with pytest.raises(DirectionError, match="regular"):
        read_document(tmp_path / "linked")
    (tmp_path / "large").write_bytes(b"x" * 524289)
    with pytest.raises(DirectionError, match="512"):
        read_document(tmp_path / "large")


def test_bind_is_idempotent_foreign_alias_fails_and_move_preserves_candidate(
    project, tmp_path
):
    root, run = project
    with pytest.raises(DirectionError, match="alias"):
        bind(root, PACKAGE, ars_project_ref="different")
    ledger = branches(root)
    first = bind(root, PACKAGE, branch_path=ledger)
    assert first == bind(root, PACKAGE, branch_path=ledger)
    report = check(root, first["binding_path"])
    assert statuses(report)["branch"] == "author_declared"
    assert statuses(report)["result"] == "not_evaluated"
    assert report["human_review_required"]
    assert replay_run(run).revision == 1
    moved = root.parent / (root.name + "-moved")
    shutil.move(root, moved)
    assert check(moved, first["binding_path"]) == report


def test_ai_candidate_and_changed_snapshot_never_adopt_or_overwrite(project):
    root, _ = project
    package = load_package(PACKAGE).model_dump(mode="json")
    package["hypotheses"][0]["branch_id"] = "candidate"
    path = write(root / "candidate.json", seal_package(package).model_dump(mode="json"))
    binding = bind(root, path, branch_path=branches(root, adopted=False))
    before = (root / binding["binding_path"]).read_bytes()
    assert statuses(check(root, binding["binding_path"]))["branch"] == "candidate"
    package["package_version"] = "1.0.1"
    package["hypotheses"][0]["statement"] = "A changed claim."
    changed = write(
        root / "updated.json", seal_package(package).model_dump(mode="json")
    )
    assert (
        check(root, binding["binding_path"], current_package=changed)["input_state"]
        == "stale"
    )
    assert (root / binding["binding_path"]).read_bytes() == before
    assert check(root, binding["binding_path"])["input_state"] == "retained_snapshot"
    snapshot = root / json.loads(before)["package_snapshot"]
    snapshot.write_bytes(changed.read_bytes())
    with pytest.raises(DirectionError, match="bound digest"):
        check(root, binding["binding_path"])


def test_definition_prepare_retry_explicit_cli_admission_and_no_duplicate(
    project, capsys
):
    root, run = project
    path = write(root / "definition.json", definition())
    report = prepare_definition(
        root, path, package_path=PACKAGE, hypothesis_id="hypothesis.transfer"
    )
    assert report == prepare_definition(
        root, path, package_path=PACKAGE, hypothesis_id="hypothesis.transfer"
    )
    assert replay_run(run).revision == 1
    assert main(report["next_command"][1:]) == 0
    assert json.loads(capsys.readouterr().out)["accepted"]
    assert replay_run(run).revision == 2
    again = prepare_definition(root, path)
    assert again["status"] == "already_accepted" and again["next_command"] is None
    assert replay_run(run).revision == 2


@pytest.mark.parametrize("metric,expected", [(0.75, "passed"), (0.5, "failed")])
def test_original_frozen_numeric_result_and_definition_binding(
    project, metric, expected
):
    from arw.kernel.artifacts.experiment_acceptance import (
        evaluate_experiment_acceptance,
        freeze_experiment_contract,
        publish_experiment_acceptance,
    )
    from arw.kernel.artifacts.experiment_provenance import (
        ProvenanceAuthorityEnvelope,
        ingest_experiment_provenance,
    )
    from tests.unit.test_experiment_acceptance import (
        _contract,
        _metric,
        _provenance,
        _reproduction,
    )

    root, run = project
    path = write(root / "definition.json", definition())
    prepared = prepare_definition(
        root, path, package_path=PACKAGE, hypothesis_id="hypothesis.transfer"
    )
    request = ArtifactAcceptanceRequest.model_validate_json(
        (run / prepared["request_path"]).read_bytes()
    )
    assert RuntimeCommandService(run).accept_artifact(request).accepted
    ref = reference(run, replay_run(run).events[-1])
    contract, _, _ = freeze_experiment_contract(
        _contract(
            _reproduction(),
            claim_id="hypothesis.transfer",
            claim_sha256=prepared["claim_sha256"],
        ),
        run,
        RuntimeCommandService(run),
        runtime_request(run),
    )
    provenance = _provenance(run, metrics=[_metric("accuracy", metric, "ratio")])
    provenance["run_id"] = replay_run(run).run_id
    ingested = ingest_experiment_provenance(
        provenance,
        run,
        ProvenanceAuthorityEnvelope(
            runtime=RuntimeCommandService(run), request=runtime_request(run)
        ),
    )
    result = evaluate_experiment_acceptance(
        contract, ingested.provenance, run, journal_prefix=replay_run(run)
    )
    publish_experiment_acceptance(run, result)
    case = {
        "hypothesis_id": "hypothesis.transfer",
        "definition_ref": ref.model_dump(mode="json"),
        "contract_sha256": contract.contract_sha256,
        "contract_version": 1,
        "result_sha256": result.result_sha256,
    }
    binding = bind(root, PACKAGE, branch_path=branches(root), cases=[case])
    report = check(root, binding["binding_path"])
    state = statuses(report)
    assert (
        state["hypothesis_definition_contract"] == "resolved"
        and state["contract"] == "frozen"
    )
    assert state["result"] == expected
    assert state["actual_costs"] == "missing" and state["all_attempts"] == "missing"
    assert state["narrative"] == "not_evaluated"
    altered = definition()
    altered["local_definition"] = "A different construct."
    otherref = accept(run, write(run / "changed.json", altered), "definition.changed")
    case["definition_ref"] = otherref.model_dump(mode="json")
    stale = check(root, bind(root, PACKAGE, cases=[case])["binding_path"])
    assert statuses(stale)["hypothesis_definition_contract"] == "stale_or_missing"
    case["contract_version"] = 2
    assert (
        statuses(check(root, bind(root, PACKAGE, cases=[case])["binding_path"]))[
            "result"
        ]
        == "unresolved"
    )


def test_version_carriers_receipt_status_and_source_bytes_remain_separate(project):
    from arw.kernel.policy.citations import (
        ReferenceRecord,
        check_response,
        check_unavailable,
        publish_check,
    )
    from tests.unit.test_citations import _crossref

    root, run = project
    ref = ReferenceRecord(
        reference_id="ref.alpha",
        citation_key="Smith2024",
        title="Evidence for Alpha",
        authors=("Smith",),
        year=2024,
        doi="10.1234/alpha",
    )
    receipts = []
    for raw in [_crossref(), _crossref(items=[])]:
        receipt = check_response(
            ref, "crossref", raw, observed_at="2026-10-12T00:00:00Z"
        )
        publish_check(root, receipt, raw)
        receipts.append(receipt.receipt_sha256)
    unavailable = check_unavailable(
        ref, "openalex", observed_at="2026-10-12T00:00:00Z", error_code="timeout"
    )
    publish_check(root, unavailable, b"")
    receipts.append(unavailable.receipt_sha256)
    source = accept(
        run,
        write(run / "source-v1.json", {"synthetic": True, "sample_count": 40}),
        "source.v1",
    )
    reading = {
        "source_id": "reading.v1",
        "reference": ref.model_dump(mode="json"),
        "version_label": "v1",
        "carrier": "text",
        "source_sha256": source.content_sha256,
        "source_ref": source.model_dump(mode="json"),
        "citation_receipts": receipts,
        "reader": "tool",
        "reading_status": "partial",
        "read_ranges": ["abstract"],
        "note": "Synthetic version1:40 cases.",
        "limitations": ["No philosophical or empirical support."],
        "affected_records": ["note.v1", "matrix.old"],
    }
    intake = {
        "schema_version": "arw.literature-intake.v1",
        "project_id": load_plan(root).project_id,
        "package_sha256": load_package(PACKAGE).package_sha256,
        "sources": [reading],
    }
    first = write(root / "intake-v1.json", intake)
    report = prepare_intake(root, PACKAGE, first)
    assert [r["status"] for r in report["sources"][0]["bibliographic"]] == [
        "verified",
        "not_found",
        "unavailable",
    ]
    assert report["sources"][0]["source_bytes"] == "retained_accepted_bytes"
    old = first.read_bytes()
    newer = deepcopy(intake)
    newer["sources"][0].update(
        source_id="reading.v2",
        version_label="v2",
        carrier="pdf",
        source_ref=None,
        source_sha256=None,
        note="Synthetic version2:100 cases.",
        reading_status="timed_out",
    )
    update = prepare_intake(
        root, PACKAGE, write(root / "intake-v2.json", newer), previous=first
    )
    assert update["sources"][0]["source_bytes"] == "missing_or_unaccepted"
    assert update["sources"][0]["recorded_reader"] == "tool"
    assert update["sources"][0]["experiment_replay"] == "not_evaluated"
    assert update["upgrade_impacts"][0]["status"] == "review_required_not_false"
    assert update["upgrade_impacts"][0]["affected_records"] == ["note.v1", "matrix.old"]
    assert first.read_bytes() == old


def test_preparation_interruption_and_stale_request_preserve_existing_writer(
    project, monkeypatch
):
    import arw.research_directions as adapter

    root, run = project
    path = write(root / "definition.json", definition())
    original = adapter.publish_once

    def interrupted(root, relative, raw):
        if "/request-" in relative:
            raise OSError("simulated interruption after durable artifact bytes")
        return original(root, relative, raw)

    monkeypatch.setattr(adapter, "publish_once", interrupted)
    with pytest.raises(OSError):
        prepare_definition(root, path)
    assert replay_run(run).revision == 1
    monkeypatch.setattr(adapter, "publish_once", original)
    prepared = prepare_definition(root, path)
    old_request = (run / prepared["request_path"]).read_bytes()
    accept(run, write(run / "unrelated.json", {"synthetic": True}), "record.unrelated")
    stale = RuntimeCommandService(run).accept_artifact(
        ArtifactAcceptanceRequest.model_validate_json(old_request)
    )
    assert not stale.accepted
    assert replay_run(run).revision == 2
    updated = prepare_definition(root, path)
    assert updated["request_path"] != prepared["request_path"]
    assert (run / prepared["request_path"]).read_bytes() == old_request
    assert (
        RuntimeCommandService(run)
        .accept_artifact(
            ArtifactAcceptanceRequest.model_validate_json(
                (run / updated["request_path"]).read_bytes()
            )
        )
        .accepted
    )
    assert prepare_definition(root, path)["status"] == "already_accepted"
    assert replay_run(run).revision == 3


def test_invalid_evidence_reason_and_control_differences_are_not_hidden(project):
    root, run = project
    ref = accept(
        run,
        write(run / "negative.json", {"synthetic": True, "effect": 0}),
        "evidence.negative",
    )
    invalid = ref.model_dump(mode="json")
    invalid["accepting_event_sha256"] = "f" * 64
    case = {
        "hypothesis_id": "hypothesis.transfer",
        "definition_ref": invalid,
        "evidence": [{"relation": "opposes", "ref": invalid}],
        "conditions": [
            {
                "condition_id": f"condition.{role}",
                "role": role,
                "model_label": "recorded-fixture",
                "data_sha256": "a" * 64,
                "evaluation_sha256": "b" * 64,
                "token_budget": budget,
            }
            for role, budget in [("baseline", 10), ("intervention", 20)]
        ],
    }
    report = check(root, bind(root, PACKAGE, cases=[case])["binding_path"])
    states = statuses(report)
    assert states["operationalization"] == "unresolved"
    assert states["evidence_opposes"] == "unresolved"
    assert next(r for r in report["checks"] if r["check"] == "evidence_opposes")[
        "reason_code"
    ]
    assert states["equal_budget_data_evaluation"] == "missing_or_different"
    assert states["sham"] == "missing" and states["held_out"] == "missing"
    assert (
        report["coverage"]["hypotheses_checked"]
        == report["coverage"]["package_hypotheses"]
        == 1
    )


def test_fixed_validator_does_not_forward_credentials(tmp_path, monkeypatch):
    import arw.research_directions as adapter

    original = adapter.subprocess.run
    observed = []

    def inspect(argv, **kwargs):
        observed.append((argv, kwargs["env"]))
        assert "-I" in argv
        assert kwargs["env"] == {
            "PATH": __import__("os").defpath,
            "PYTHONNOUSERSITE": "1",
        }
        return original(argv, **kwargs)

    monkeypatch.setattr(adapter.subprocess, "run", inspect)
    inspect_package(PACKAGE)
    assert len(observed) == 1


def test_actual_offline_walkthrough_preserves_scopes(tmp_path):
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "examples/research-directions/offline_walkthrough.py"),
            "--project-root",
            str(tmp_path / "research"),
            "--plugin-root",
            str(ROOT),
        ],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode()
    summary = json.loads((tmp_path / "research/observations/summary.json").read_bytes())
    assert summary["model_calls"] == 0 and summary["result_statuses"] == [
        "passed",
        "failed",
    ]
    assert summary["workflow_stage"] == "initialized"
    assert summary["scientific_status"] == "not_evaluated"
    assert statuses(summary["checks"])["result"] == "failed"
    assert statuses(summary["checks"])["narrative"] == "human_review_required"
    assert statuses(summary["checks"])["evidence_null_result"] == "resolved"
    assert summary["version_upgrade"][0]["status"] == "review_required_not_false"
