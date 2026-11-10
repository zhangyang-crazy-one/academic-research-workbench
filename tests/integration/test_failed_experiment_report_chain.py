"""Bounded pilot: pinned failures survive accepted evidence and governed writing.

This is not a semantic classifier. The report author explicitly protects the
observed outcome; removing that protection is outside this pilot's guarantee.
"""

import json
from datetime import UTC, datetime

import pytest
from arw_writing.service import WritingService

from arw.kernel.artifacts.experiment_acceptance import (
    evaluate_experiment_acceptance,
    publish_experiment_acceptance,
    publish_experiment_contract,
    seal_experiment_contract,
)
from arw.kernel.artifacts.experiment_provenance import (
    ProvenanceAuthorityEnvelope,
    ProvenanceError,
    evaluate_controlled_execution_policy,
    ingest_experiment_provenance,
    publish_experiment_provenance,
    seal_experiment_provenance,
)
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger import claim_graph
from arw.kernel.ledger.journal import replay_run
from evals.experiment_reporting import render_outcome
from tests.integration.test_precise_source_locators import RUN, accept
from tests.integration.test_research_artifacts import request
from tests.integration.test_writing import approve, proposal
from tests.unit.test_claim_graph import (
    current_claim,
    occurrences,
    record,
    registration,
    setup,
)
from tests.unit.test_experiment_acceptance import (
    _comparison,
    _contract,
    _journal_request,
    _metric,
    _provenance,
    _reproduction,
)

CASES = (
    "unauthorized_substitute",
    "solver_never_started",
    "shrunk_scope",
    "honest_negative",
)


def _chain(tmp_path, case, *, invalid_status="invalid_contract"):
    project, run = setup(tmp_path)
    runtime = RuntimeCommandService(run)

    def command(number):
        return _journal_request(replay_run(run).revision, number).model_copy(
            update={"run_id": RUN}
        )

    checks = [_reproduction()]
    metrics = [_metric("accuracy", 0.75, "ratio")]
    files = None
    if case == "shrunk_scope":
        checks.append(
            _reproduction(
                check_id="check.full-scope",
                reported_metric="required_samples",
                operator="count@1",
                unit="sample",
            )
        )
        metrics.append(_metric("required_samples", 3, "sample"))
        files = {"artifact.scores": "sample,score\ns1,0.75\n"}
    elif case == "solver_never_started":
        files = {"artifact.execution-log": "status\nblocked\n"}
    elif case in {"honest_negative", "invalid_comparison"}:
        checks.append(_comparison())
        metrics.append(_metric("baseline_accuracy", 0.9, "ratio"))
        if case == "invalid_comparison":
            invalid = _comparison(check_id="check.invalid-comparison")
            if invalid_status == "invalid_contract":
                invalid["baseline"]["context"]["dataset"] = "different-dataset"
            else:
                invalid["valid_range"] = {"maximum": "0.8"}
            checks.append(invalid)

    contract = seal_experiment_contract(_contract(*checks))
    publish_experiment_contract(run, contract)
    assert runtime.append_experiment_contract(command(1100), contract=contract).accepted
    value = _provenance(run, metrics=metrics, files=files)
    value["run_id"] = RUN
    if case == "unauthorized_substitute":
        # The original input really is unavailable. The attempted substitute is
        # readable but cannot satisfy the original, pinned source identity.
        original = run / "input.csv"
        with pytest.raises(FileNotFoundError):
            original.read_bytes()
        original.write_text("sample,score\nsynthetic,0.75\n")
        value["source_datasets"][0].update(
            {
                "uri_or_path": "input.csv",
                "content_sha256": sha256_hex(b"sample,score\nreal,0.1\n"),
            }
        )
        with pytest.raises(ProvenanceError, match="digest mismatch"):
            ingest_experiment_provenance(
                value, run, ProvenanceAuthorityEnvelope(runtime, command(1101))
            )
        # An attacker can retain bytes and get generic artifact acceptance.
        # That must not turn a missing provenance admission into trusted checks.
        provenance = seal_experiment_provenance(value)
        publish_experiment_provenance(run, provenance)
        fact = "The original input was unavailable; its substitute failed source identity verification."
    else:
        provenance = ingest_experiment_provenance(
            value, run, ProvenanceAuthorityEnvelope(runtime, command(1101))
        ).provenance
        fact = {
            "solver_never_started": "The solver did not start and no result artifact was produced.",
            "shrunk_scope": "Only 1 of the required 3 samples was evaluated; full-scope acceptance failed.",
            "invalid_comparison": "The baseline comparison used incompatible datasets.",
            "honest_negative": "Accuracy was 0.75 versus baseline 0.9; the improvement criterion failed.",
        }[case]
    decision = None
    if case == "solver_never_started":
        decision = evaluate_controlled_execution_policy(
            provenance, now=datetime(2026, 7, 15, 10, 30, tzinfo=UTC)
        )
        assert decision.status == "BLOCKED" and not decision.subprocess_allowed
        assert "controlled_execution_adapter_disabled" in decision.reason_codes
        assert not (run / "results/artifact.scores.csv").exists()
    result = evaluate_experiment_acceptance(contract, provenance, run)
    if case == "invalid_comparison":
        assert result.checks[-1].status == invalid_status
    path = publish_experiment_acceptance(run, result).relative_to(run).as_posix()
    assert accept(
        run, "artifact.experiment", path, 43, kind="experiment-acceptance-result"
    ).accepted
    source = f"Moreover, {fact} [@experiment] No verified success is established."
    (run / "report.txt").write_text(source)
    assert accept(run, "artifact.report", "report.txt", 44, kind="manuscript").accepted
    view = claim_graph.graph(project, run_roots=(run,))
    evidence = next(
        n
        for n in view["nodes"]
        if n.get("artifact_kind") == "experiment-acceptance-result"
    )
    reg = registration(
        view,
        statement=fact,
        evidence=[
            {
                "evidence_id": "evidence.experiment",
                "node_kind": "ExperimentResult",
                "original": evidence["source"],
            }
        ],
    )
    report_occurrence = next(
        n
        for n in occurrences(view)
        if n["manuscript_ref"]["artifact_id"] == "artifact.report"
    )
    reg = reg.model_copy(
        update={
            "occurrences": (
                type(reg.occurrences[0]).model_validate(
                    {
                        k: v
                        for k, v in report_occurrence.items()
                        if k not in ("id", "node_kind", "registration")
                    }
                ),
            )
        }
    )
    record(project, run, reg)
    view = claim_graph.graph(project, run_roots=(run,))
    statuses = [c["status"] for c in current_claim(view)["checks"][0]["results"]]
    expected = {
        "unauthorized_substitute": ["not_checked"],
        "solver_never_started": ["failed"],
        "shrunk_scope": ["passed", "failed"],
        "honest_negative": ["passed", "failed"],
        "invalid_comparison": ["passed", "failed", "failed"],
    }
    assert statuses == expected[case]
    assert result.scope == "contract_conformance_only"
    assert result.external_execution_timing == "not_observed"
    final = render_outcome(
        result=result, graph=view, claim_id="claim.relation", execution=decision
    )
    assert final == render_outcome(
        result=result, graph=view, claim_id="claim.relation", execution=decision
    )
    assert (
        final["outcome"]["outcome"]
        == {
            "unauthorized_substitute": "unverified",
            "solver_never_started": "blocked",
            "shrunk_scope": "blocked",
            "honest_negative": "negative_result",
            "invalid_comparison": "blocked",
        }[case]
    )
    assert final["outcome"]["outcome"] != "verified_success"
    assert "No verified success is established." in final["outcome_section"]
    # The canonical artifact contains both structured outcome and rendered section,
    # including hashes and the exact accepted evidence / graph snapshot bindings.
    (run / "final-outcome.json").write_bytes(canonical_json_bytes(final))
    assert accept(
        run,
        "artifact.final-outcome",
        "final-outcome.json",
        45,
        kind="pilot-final-report",
    ).accepted
    retained = json.loads((run / "final-outcome.json").read_text())
    assert retained == final
    assert (
        sha256_hex(retained["outcome_section"].encode())
        == retained["outcome_section_sha256"]
    )
    return run, fact


@pytest.mark.parametrize("case", CASES)
def test_failed_experiment_to_governed_report(tmp_path, case):
    run, fact = _chain(tmp_path, case)
    source = (run / "report.txt").read_text()
    candidate = source.removeprefix("Moreover, ")
    service = WritingService(run)
    edit = proposal(source, candidate)
    # Supported author-owned preservation contract, not inferred semantics.
    edit["protected_spans"] = [fact, "No verified success is established."]
    prepared = service.prepare("artifact.report", edit)
    assert prepared["disposition"] == "human_review"
    assert not prepared["verification"]["semantic_equivalence_proven"]
    assert not service.record("artifact.report", edit, request=request(run, 50))[
        "candidate_accepted"
    ]
    review = approve(run, prepared)
    honest = service.record(
        "artifact.report", edit, request=request(run, 70), review_artifact_id=review
    )
    assert honest["candidate_accepted"]
    bundle = json.loads((run / honest["bundle_path"]).read_text())
    assert bundle["candidate"] == candidate
    assert fact in bundle["candidate"]

    dishonest = proposal(source, "The experiment was a verified success.")
    dishonest["protected_spans"] = edit["protected_spans"]
    rejected = service.prepare("artifact.report", dishonest)
    assert rejected["disposition"] == "reject"
    assert any(
        f["dimension"] == "protected_spans" and f["status"] == "reject"
        for f in rejected["verification"]["findings"]
    )
    assert not service.record("artifact.report", dishonest, request=request(run, 80))[
        "candidate_accepted"
    ]
    bad_review = approve(run, rejected, number=81)
    with pytest.raises(ValueError, match="hard preservation"):
        service.record(
            "artifact.report",
            dishonest,
            request=request(run, 82),
            review_artifact_id=bad_review,
        )


def test_unprotected_conclusion_is_not_a_semantic_guarantee(tmp_path):
    """An explicit boundary witness; acceptance must not be advertised as truth."""
    run, _fact = _chain(tmp_path, "honest_negative")
    source = (run / "report.txt").read_text()
    candidate = (
        source.removeprefix("Moreover, ") + " The experiment was a verified success."
    )
    service = WritingService(run)
    edit = proposal(source, candidate)
    prepared = service.prepare("artifact.report", edit)
    assert prepared["disposition"] == "human_review"
    assert not prepared["verification"]["semantic_equivalence_proven"]
    assert not service.record("artifact.report", edit, request=request(run, 50))[
        "candidate_accepted"
    ]
    # A knowingly incorrect, fixture-only reviewer can admit this contradiction.
    # Production callers must protect known outcome facts or supply sound review.
    review = approve(run, prepared)
    outcome = service.record(
        "artifact.report", edit, request=request(run, 70), review_artifact_id=review
    )
    assert outcome["candidate_accepted"]


def test_identical_checks_from_another_receipt_do_not_bind_claim(tmp_path):
    from arw.kernel.artifacts.experiment_provenance import load_experiment_provenance
    from tests.unit.test_claim_experiment_replay import _regular_receipt

    project, run, selected = _regular_receipt(tmp_path)
    runtime = RuntimeCommandService(run)
    other_contract = seal_experiment_contract(_contract(contract_id="contract.other"))
    publish_experiment_contract(run, other_contract)
    command = _journal_request(replay_run(run).revision, 1200).model_copy(
        update={"run_id": RUN}
    )
    assert runtime.append_experiment_contract(command, contract=other_contract).accepted
    other_result = evaluate_experiment_acceptance(
        other_contract, load_experiment_provenance(run, selected.provenance_sha256), run
    )
    path = publish_experiment_acceptance(run, other_result).relative_to(run).as_posix()
    assert accept(
        run, "artifact.other", path, 1201, kind="experiment-acceptance-result"
    ).accepted
    view = claim_graph.graph(project, run_roots=(run,))
    receipts = {
        n["source"]["artifact_id"]: n
        for n in view["nodes"]
        if n.get("artifact_kind") == "experiment-acceptance-result"
    }
    assert (
        receipts["artifact.experiment"]["checks"]
        == receipts["artifact.other"]["checks"]
    )
    assert selected.result_sha256 != other_result.result_sha256
    record(
        project,
        run,
        registration(
            view,
            evidence=[
                {
                    "evidence_id": "evidence.other",
                    "node_kind": "ExperimentResult",
                    "original": receipts["artifact.other"]["source"],
                }
            ],
        ),
    )
    view = claim_graph.graph(project, run_roots=(run,))
    with pytest.raises(ValueError, match="receipt is not bound"):
        render_outcome(result=selected, graph=view, claim_id="claim.relation")
    actual = render_outcome(result=other_result, graph=view, claim_id="claim.relation")
    assert actual["outcome"]["claim_evidence_id"] == "evidence.other"
    assert (
        actual["outcome"]["experiment_accepted_ref"]
        == receipts["artifact.other"]["source"]
    )


@pytest.mark.parametrize("status", ["invalid_contract", "invalid_artifact"])
def test_invalid_comparison_is_not_an_honest_negative(tmp_path, status):
    _chain(tmp_path, "invalid_comparison", invalid_status=status)


def test_rendered_outcome_does_not_alias_replayed_graph(tmp_path):
    from copy import deepcopy

    from tests.unit.test_claim_experiment_replay import _regular_receipt

    project, run, result = _regular_receipt(tmp_path)
    view = claim_graph.graph(project, run_roots=(run,))
    receipt = next(
        n
        for n in view["nodes"]
        if n.get("artifact_kind") == "experiment-acceptance-result"
    )
    record(
        project,
        run,
        registration(
            view,
            evidence=[
                {
                    "evidence_id": "evidence.experiment",
                    "node_kind": "ExperimentResult",
                    "original": receipt["source"],
                }
            ],
        ),
    )
    view = claim_graph.graph(project, run_roots=(run,))
    rendered = render_outcome(result=result, graph=view, claim_id="claim.relation")
    assert all(check.status == "passed" for check in result.checks)
    assert rendered["outcome"]["outcome"] == "unverified"
    assert rendered["outcome"]["reason_codes"] == [
        "contract_conformance_is_not_verified_execution"
    ]
    retained = deepcopy(rendered)
    for node in view["nodes"]:
        if "source" in node:
            node["source"]["content_sha256"] = "0" * 64
        if (
            node.get("node_kind") == "ExperimentResult"
            and node.get("checks")
            and "accepted_ref" in node
        ):
            node["checks"][0]["status"] = "failed"
            node["accepted_ref"]["content_sha256"] = "0" * 64
    assert rendered == retained
    assert (
        sha256_hex(canonical_json_bytes(rendered["outcome"]))
        == rendered["outcome_sha256"]
    )


@pytest.mark.parametrize("damage", ["delete", "tamper"])
def test_damaged_honest_negative_becomes_unverified(tmp_path, damage):
    from arw.kernel.artifacts.experiment_acceptance import load_experiment_acceptance

    run, _fact = _chain(tmp_path, "honest_negative")
    retained = json.loads((run / "final-outcome.json").read_text())
    assert retained["outcome"]["outcome"] == "negative_result"
    result = load_experiment_acceptance(
        run, retained["outcome"]["experiment_result_sha256"]
    )
    scores = run / "results/artifact.scores.csv"
    if damage == "delete":
        scores.unlink()
    else:
        scores.write_text("sample,score\ns1,99\n")
    current = claim_graph.graph(run.parent, run_roots=(run,))
    rendered = render_outcome(result=result, graph=current, claim_id="claim.relation")
    assert rendered["outcome"]["outcome"] == "unverified"
    assert rendered["outcome"]["reason_codes"] == ["experiment_evidence_not_verified"]
    assert all(
        check["status"] == "not_checked" for check in rendered["outcome"]["checks"]
    )
    # Historical bytes remain unchanged; a fresh report cannot reuse their
    # negative-result classification after the underlying evidence is damaged.
    assert json.loads((run / "final-outcome.json").read_text()) == retained
