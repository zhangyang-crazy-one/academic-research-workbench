"""An accepted JSON document cannot self-attest experimental conformance."""

import pytest

from arw.kernel.artifacts.experiment_acceptance import ExperimentAcceptanceResult
from arw.kernel.ledger import claim_graph
from tests.integration.test_precise_source_locators import accept
from tests.unit.test_claim_graph import current_claim, record, registration, setup


def test_ordinary_receipt_without_contract_provenance_or_csv_is_not_trusted(tmp_path):
    project, run = setup(tmp_path)
    result = ExperimentAcceptanceResult.model_validate(
        {
            "schema_version": "arw.experiment-acceptance.v1",
            "evaluator_version": "1.1.0",
            "scope": "contract_conformance_only",
            "contract_id": "contract.example",
            "contract_version": 1,
            "contract_sha256": "a" * 64,
            "provenance_sha256": "b" * 64,
            "claim_id": "claim.example",
            "claim_sha256": "c" * 64,
            "predeclaration": "predeclaration_unverified",
            "checks": [
                {
                    "check_id": "check.example",
                    "kind": "numeric_reproduction",
                    "status": "passed",
                }
            ],
            "overall_status": "passed",
            "budget_status": "not_declared",
        }
    )
    (run / "self-reported.json").write_bytes(result.canonical_bytes())
    assert accept(
        run,
        "artifact.self-reported",
        "self-reported.json",
        42,
        kind="research-evidence",
    ).accepted
    view = claim_graph.graph(project, run_roots=(run,))
    node = next(
        n for n in view["nodes"] if n.get("artifact_kind") == "research-evidence"
    )
    assert node["checks"][0]["status"] == "not_checked"
    record(
        project,
        run,
        registration(
            view,
            evidence=[
                {
                    "evidence_id": "evidence.experiment",
                    "node_kind": "ExperimentResult",
                    "original": node["source"],
                }
            ],
        ),
    )
    checked = current_claim(claim_graph.graph(project, run_roots=(run,)))["checks"][0][
        "results"
    ]
    assert checked[0]["status"] == "not_checked"


def _regular_receipt(
    tmp_path,
    *,
    evaluator="1.2.0",
    metric=0.75,
    force_pass=False,
    admit_dependencies=True,
):
    from arw.kernel.artifacts.experiment_acceptance import (
        evaluate_experiment_acceptance,
        publish_experiment_acceptance,
        publish_experiment_contract,
        seal_experiment_contract,
    )
    from arw.kernel.artifacts.experiment_provenance import (
        ProvenanceAuthorityEnvelope,
        ingest_experiment_provenance,
        publish_experiment_provenance,
        seal_experiment_provenance,
    )
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.ledger.journal import replay_run
    from tests.integration.test_precise_source_locators import RUN
    from tests.unit.test_experiment_acceptance import (
        _contract,
        _journal_request,
        _metric,
        _provenance,
    )

    project, run = setup(tmp_path)
    service = RuntimeCommandService(run)
    contract = seal_experiment_contract(_contract())
    publish_experiment_contract(run, contract)

    def request(number):
        return _journal_request(replay_run(run).revision, number).model_copy(
            update={"run_id": RUN}
        )

    if admit_dependencies:
        assert service.append_experiment_contract(
            request(1100), contract=contract
        ).accepted
    value = _provenance(run, metrics=[_metric("accuracy", metric, "ratio")])
    value["run_id"] = RUN
    if admit_dependencies:
        provenance = ingest_experiment_provenance(
            value, run, ProvenanceAuthorityEnvelope(service, request(1101))
        ).provenance
    else:
        provenance = seal_experiment_provenance(value)
        publish_experiment_provenance(run, provenance)
    result = evaluate_experiment_acceptance(
        contract, provenance, run, evaluator_version=evaluator
    )
    if force_pass:
        body = result.model_dump(mode="json", exclude_none=True)
        for check in body["checks"]:
            check["status"] = "passed"
        body["overall_status"] = "passed"
        result = ExperimentAcceptanceResult.model_validate(body)
    path = publish_experiment_acceptance(run, result).relative_to(run).as_posix()
    assert accept(
        run, "artifact.experiment", path, 43, kind="experiment-acceptance-result"
    ).accepted
    return project, run, result


@pytest.mark.parametrize("evaluator", ["1.0.0", "1.1.0", "1.2.0"])
@pytest.mark.parametrize("metric", [0.75, 0.8])
def test_original_replay_retains_valid_passed_and_failed_results(
    tmp_path, evaluator, metric
):
    project, run, _result = _regular_receipt(
        tmp_path, evaluator=evaluator, metric=metric
    )
    view = claim_graph.graph(project, run_roots=(run,))
    node = next(
        n
        for n in view["nodes"]
        if n.get("artifact_kind") == "experiment-acceptance-result"
    )
    expected = "passed" if metric == 0.75 else "failed"
    assert node["checks"][0]["status"] == expected
    assert "reason" not in node["checks"][0]
    record(
        project,
        run,
        registration(
            view,
            evidence=[
                {
                    "evidence_id": "evidence.experiment",
                    "node_kind": "ExperimentResult",
                    "original": node["source"],
                }
            ],
        ),
    )
    assert (
        current_claim(claim_graph.graph(project, run_roots=(run,)))["checks"][0][
            "results"
        ][0]["status"]
        == expected
    )


@pytest.mark.parametrize(
    "damage", ["forged_pass", "missing_csv", "tampered_csv", "unaccepted_dependencies"]
)
def test_invalid_experiment_dependencies_never_become_trusted_pass(tmp_path, damage):
    project, run, _ = _regular_receipt(
        tmp_path,
        metric=0.8 if damage == "forged_pass" else 0.75,
        force_pass=damage == "forged_pass",
        admit_dependencies=damage != "unaccepted_dependencies",
    )
    csv = run / "results/artifact.scores.csv"
    if damage == "missing_csv":
        csv.unlink()
    elif damage == "tampered_csv":
        csv.write_text("sample,score\ns1,99\n")
    view = claim_graph.graph(project, run_roots=(run,))
    node = next(
        n
        for n in view["nodes"]
        if n.get("artifact_kind") == "experiment-acceptance-result"
    )
    assert node["checks"][0]["status"] == "not_checked"
    assert node["checks"][0]["reason"] == "experiment_replay_unverifiable"


def test_later_dependency_acceptance_cannot_retroactively_qualify_receipt(tmp_path):
    from arw.kernel.artifacts.experiment_acceptance import load_experiment_contract
    from arw.kernel.artifacts.experiment_provenance import (
        ProvenanceAuthorityEnvelope,
        ingest_experiment_provenance,
        load_experiment_provenance,
    )
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.ledger.journal import replay_run
    from tests.integration.test_precise_source_locators import RUN
    from tests.unit.test_experiment_acceptance import _journal_request

    project, run, result = _regular_receipt(tmp_path, admit_dependencies=False)
    service = RuntimeCommandService(run)
    request = _journal_request(replay_run(run).revision, 1110).model_copy(
        update={"run_id": RUN}
    )
    assert service.append_experiment_contract(
        request, contract=load_experiment_contract(run, result.contract_sha256)
    ).accepted
    request = _journal_request(replay_run(run).revision, 1111).model_copy(
        update={"run_id": RUN}
    )
    ingest_experiment_provenance(
        load_experiment_provenance(run, result.provenance_sha256),
        run,
        ProvenanceAuthorityEnvelope(service, request),
    )
    view = claim_graph.graph(project, run_roots=(run,))
    node = next(
        n
        for n in view["nodes"]
        if n.get("artifact_kind") == "experiment-acceptance-result"
    )
    assert node["checks"][0]["status"] == "not_checked"
