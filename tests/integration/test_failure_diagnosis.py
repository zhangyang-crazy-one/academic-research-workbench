"""Local, self-authored failure patterns; fixture answers never enter diagnosis."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arw.kernel.artifacts.failure_diagnosis import (
    FailureDiagnosisError,
    diagnose_failure,
)
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import replay_run
from arw.kernel.state.failure_diagnosis import FailureDiagnosisRequest

from .test_precise_source_locators import accept, seed

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/failure-diagnosis"


def _source_snapshot(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_hex(path.read_bytes())
        for path in root.rglob("*") if path.is_file()
    }


def _case(tmp_path: Path, name: str):
    fixture = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    root, _ = seed(tmp_path)
    acceptance = fixture["acceptance"]
    (root / "acceptance.json").write_bytes(canonical_json_bytes(acceptance))
    assert accept(root, "artifact.acceptance", "acceptance.json", 10, kind="learning-evidence").accepted
    failure_ids = []
    for index, body in enumerate(fixture["failures"]):
        body = {**body, "acceptance_sha256": sha256_hex((root / "acceptance.json").read_bytes())}
        artifact_id = f"artifact.failure-{index}"
        path = f"failure-{index}.json"
        (root / path).write_bytes(canonical_json_bytes(body))
        assert accept(root, artifact_id, path, 20 + index, kind="learning-evidence").accepted
        failure_ids.append(artifact_id)
    edit_ids = []
    for index, body in enumerate(fixture["edits"]):
        artifact_id = f"artifact.edit-{index}"
        path = f"edit-{index}.json"
        (root / path).write_bytes(canonical_json_bytes(body))
        assert accept(root, artifact_id, path, 30 + index, kind="learning-evidence").accepted
        edit_ids.append(artifact_id)
    payload = {
        "schema_version": "arw.failure-diagnosis-request.v1",
        "acceptance_artifact_id": "artifact.acceptance",
        "failure_artifact_ids": failure_ids,
        "change_artifact_ids": edit_ids,
    }
    request = FailureDiagnosisRequest.model_validate_json(canonical_json_bytes(payload))
    return root, fixture, request


@pytest.mark.parametrize("name", ["sign", "unit", "mapping"])
def test_hidden_cause_minimal_cases_are_advisory_and_read_only(tmp_path: Path, name: str) -> None:
    root, fixture, request = _case(tmp_path, name)
    assert "hidden_cause" not in FailureDiagnosisRequest.model_fields
    with pytest.raises(ValueError):
        FailureDiagnosisRequest.model_validate_json(canonical_json_bytes({
            **request.model_dump(mode="json"), "hidden_cause": fixture["hidden_cause"],
        }))
    before = _source_snapshot(root)
    first = diagnose_failure(root, request)
    second = diagnose_failure(root, request)
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.diagnosis_sha256 == second.diagnosis_sha256
    assert _source_snapshot(root) == before
    assert first.causal_status == "unknown"
    assert first.execution_effect == "read_only_advice"
    assert len(first.hypotheses) >= 2
    assert {item.mechanism_id for item in first.hypotheses if item.status == "kept"} == {fixture["hidden_cause"]}
    assert all(item.probe.actual_evidence is None and len(item.probe.expected_outcomes) >= 2 for item in first.hypotheses)
    assert all(item.sources and item.probe.expected_outcomes for item in first.hypotheses)
    assert all(judgment.sources for judgment in first.patterns)
    assert first.patterns[2].finding == "yes"
    if name == "sign":
        assert (first.patterns[0].finding, first.patterns[1].finding) == ("yes", "yes")
    else:
        assert (first.patterns[0].finding, first.patterns[1].finding) == ("unknown", "unknown")


def test_missing_corrupt_and_stale_inputs_fail_closed(tmp_path: Path) -> None:
    root, _, request = _case(tmp_path, "mapping")
    missing = request.model_copy(update={"failure_artifact_ids": ("artifact.absent",)})
    with pytest.raises(FailureDiagnosisError, match="source artifact must have one accepted event"):
        diagnose_failure(root, missing)
    source = root / "failure-0.json"
    source.write_bytes(source.read_bytes() + b" ")
    with pytest.raises(FailureDiagnosisError) as error:
        diagnose_failure(root, request)
    assert error.value.code == "source_digest_mismatch"

    other = tmp_path / "other"
    other.mkdir()
    root, _, request = _case(other, "unit")
    acceptance_path = root / "acceptance.json"
    receipt_path = root / "failure-0.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    # A second root is built with the failed receipt admitted before the
    # acceptance criteria; the receipt's digest is valid but its timing is not.
    from .test_precise_source_locators import seed as fresh_seed
    (tmp_path / "stale").mkdir()
    stale_root, _ = fresh_seed(tmp_path / "stale")
    (stale_root / "failure.json").write_bytes(canonical_json_bytes(receipt))
    assert accept(stale_root, "artifact.failure-0", "failure.json", 40, kind="learning-evidence").accepted
    (stale_root / "acceptance.json").write_bytes(acceptance_path.read_bytes())
    assert accept(stale_root, "artifact.acceptance", "acceptance.json", 41, kind="learning-evidence").accepted
    with pytest.raises(FailureDiagnosisError) as error:
        diagnose_failure(stale_root, request)
    assert error.value.code == "stale_acceptance"


def test_cli_base_mode_and_optional_memory_absence(tmp_path: Path, capsys, monkeypatch) -> None:
    from arw import composition
    from arw.cli import main

    root, _, request = _case(tmp_path, "sign")
    request_file = root / "diagnose-request.json"
    request_file.write_bytes(canonical_json_bytes(request.model_dump(mode="json")))
    before = _source_snapshot(root)
    command = ["learn", "diagnose", "--project-root", str(root), "--run-root", str(root), "--input", str(request_file)]
    assert main(command) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "diagnosed"
    assert result["diagnosis_sha256"] == diagnose_failure(root, request).diagnosis_sha256
    assert _source_snapshot(root) == before

    prior_report = diagnose_failure(root, request)
    (root / "prior.json").write_bytes(prior_report.canonical_bytes())
    assert accept(root, "artifact.prior", "prior.json", 50, kind="learning-evidence").accepted
    requiring_memory = request.model_copy(update={
        "prior_diagnosis_artifact_id": "artifact.prior",
        "handoff_memory_id": "memory.absent",
    })
    request_file.write_bytes(canonical_json_bytes(requiring_memory.model_dump(mode="json")))
    real_import = composition.import_module
    def absent(name):
        if name == "arw_research_memory.service":
            raise ModuleNotFoundError(name)
        return real_import(name)
    monkeypatch.setattr(composition, "import_module", absent)
    assert main(command) == 65
    assert json.loads(capsys.readouterr().out)["code"] == "CapabilityUnavailable"


def _handoff_input(root: Path, artifact_id: str, *, memory_id: str, supersedes=()):
    from arw.kernel.state.research_memory import MemoryInput

    event = next(item for item in replay_run(root).events if
                 item.event_type == "artifact.accepted" and item.payload.artifact_id == artifact_id)
    return MemoryInput.model_validate_json(canonical_json_bytes({
        "memory_id": memory_id,
        "kind": "handoff",
        "scope": "project",
        "title": "Failure diagnosis handoff",
        "body": "Read the accepted diagnosis and distinguish remaining mechanisms.",
        "source_ledger_event_ids": [event.event_id],
        "source_artifact_ids": [artifact_id],
        "links": [{"kind": "artifact", "target_id": artifact_id,
                   "sha256": event.payload.artifact_sha256, "event_id": event.event_id}],
        "supersedes": list(supersedes),
        "handoff": {
            "objective": "Determine which failure mechanism remains plausible",
            "current_state": "Accepted failed receipts inspected; causality unknown",
            "completed_work": ["Frozen acceptance and failure receipts reviewed"],
            "evidence_gathered": [artifact_id],
            "commands_evaluations_run": ["read-only diagnosis"],
            "relevant_artifacts_issues_files": [artifact_id],
            "open_questions": ["Which proposed probe would distinguish remaining mechanisms?"],
            "blockers": [],
            "risks": ["Do not claim cause from pattern compatibility"],
            "next_concrete_action": "Review the still unresolved discriminating probe",
            "source_run_harness": {"run_id": replay_run(root).run_id, "harness": "codex"},
            "intended_target_harness": "claude",
        },
    }))


def test_two_memory_handoffs_preserve_chain_and_suppress_ruled_out_probes(tmp_path: Path) -> None:
    from arw_research_memory.project import initialize_project
    from arw_research_memory.service import ResearchMemoryService

    from .test_research_artifacts import request as parent_request

    root, _, request = _case(tmp_path, "sign")
    first = diagnose_failure(root, request)
    (root / "diagnosis-1.json").write_bytes(first.canonical_bytes())
    assert accept(root, "artifact.diagnosis-1", "diagnosis-1.json", 60, kind="learning-evidence").accepted
    initialize_project(root, "project.failure")
    memory = ResearchMemoryService(root, run_root=root)
    first_handoff = memory.save(
        _handoff_input(root, "artifact.diagnosis-1", memory_id="memory.failure-one"),
        request=parent_request(root, 101),
    )
    second_request = request.model_copy(update={
        "prior_diagnosis_artifact_id": "artifact.diagnosis-1",
        "handoff_memory_id": first_handoff["memory_id"],
    })
    before = _source_snapshot(root)
    second = diagnose_failure(
        root, second_request,
        memory_provider=ResearchMemoryService(root, run_root=root, harness="claude"),
    )
    assert _source_snapshot(root) == before
    assert second.diagnosis_chain_id == first.diagnosis_chain_id
    assert second.acceptance == first.acceptance and second.failed_receipts == first.failed_receipts
    assert all(not item.recommend_probe for item in second.hypotheses if item.status == "ruled_out")
    (root / "diagnosis-2.json").write_bytes(second.canonical_bytes())
    assert accept(root, "artifact.diagnosis-2", "diagnosis-2.json", 61, kind="learning-evidence").accepted
    next_handoff = memory.save(
        _handoff_input(root, "artifact.diagnosis-2", memory_id="memory.failure-two",
                       supersedes=(first_handoff["memory_id"],)),
        request=parent_request(root, 102),
    )
    third_request = request.model_copy(update={
        "prior_diagnosis_artifact_id": "artifact.diagnosis-2",
        "handoff_memory_id": next_handoff["memory_id"],
        "previous_handoff_memory_id": first_handoff["memory_id"],
    })
    before = _source_snapshot(root)
    third = diagnose_failure(
        root, third_request,
        memory_provider=ResearchMemoryService(root, run_root=root, harness="cursor"),
    )
    assert _source_snapshot(root) == before
    assert third.diagnosis_chain_id == first.diagnosis_chain_id
    assert third.acceptance == first.acceptance and third.failed_receipts == first.failed_receipts
    assert all(not item.recommend_probe for item in third.hypotheses if item.status == "ruled_out")
    assert third.resumed_from_memory_id == next_handoff["memory_id"]


def test_handoff_without_exact_prior_source_is_rejected(tmp_path: Path) -> None:
    from arw_research_memory.project import initialize_project
    from arw_research_memory.service import ResearchMemoryService

    from arw.kernel.state.research_memory import MemoryInput

    from .test_research_artifacts import request as parent_request

    root, _, request = _case(tmp_path, "mapping")
    first = diagnose_failure(root, request)
    (root / "diagnosis.json").write_bytes(first.canonical_bytes())
    assert accept(root, "artifact.diagnosis", "diagnosis.json", 60, kind="learning-evidence").accepted
    initialize_project(root, "project.failure")
    memory = ResearchMemoryService(root, run_root=root)
    handoff = _handoff_input(root, "artifact.diagnosis", memory_id="memory.bad-link")
    payload = handoff.model_dump(mode="json")
    payload["links"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        memory.save(MemoryInput.model_validate(payload), request=parent_request(root, 103))

    class MissingMemory:
        def read(self, *_args, **_kwargs):
            raise ValueError("missing memory")

    continuation = request.model_copy(update={
        "prior_diagnosis_artifact_id": "artifact.diagnosis",
        "handoff_memory_id": "memory.missing",
    })
    with pytest.raises(FailureDiagnosisError) as raised:
        diagnose_failure(root, continuation, memory_provider=MissingMemory())
    assert raised.value.code == "handoff_invalid"


def test_prior_chain_staleness_and_conflicting_new_evidence_are_explicit(tmp_path: Path) -> None:
    root, _, request = _case(tmp_path, "sign")
    first = diagnose_failure(root, request)
    (root / "prior.json").write_bytes(first.canonical_bytes())
    assert accept(root, "artifact.prior", "prior.json", 60, kind="learning-evidence").accepted
    incomplete = request.model_copy(update={
        "failure_artifact_ids": request.failure_artifact_ids[:1],
        "change_artifact_ids": (),
        "prior_diagnosis_artifact_id": "artifact.prior",
    })
    with pytest.raises(FailureDiagnosisError) as error:
        diagnose_failure(root, incomplete)
    assert error.value.code == "prior_diagnosis_stale"

    new_failure = {
        "schema_version": "arw.failed-attempt.v1",
        "attempt_id": "attempt.sign-three",
        "acceptance_sha256": first.acceptance.artifact_sha256,
        "status": "failed",
        "cases": [
            {"sample_id": "sample.one", "value": "2", "unit": "percent", "source_sample_id": "sample.one"},
            {"sample_id": "sample.two", "value": "4", "unit": "percent", "source_sample_id": "sample.two"},
        ],
    }
    (root / "failure-3.json").write_bytes(canonical_json_bytes(new_failure))
    assert accept(root, "artifact.failure-3", "failure-3.json", 61, kind="learning-evidence").accepted
    changed = request.model_copy(update={
        "failure_artifact_ids": (*request.failure_artifact_ids, "artifact.failure-3"),
        "prior_diagnosis_artifact_id": "artifact.prior",
    })
    with pytest.raises(FailureDiagnosisError) as error:
        diagnose_failure(root, changed)
    assert error.value.code == "conflicting_successor_evidence"
