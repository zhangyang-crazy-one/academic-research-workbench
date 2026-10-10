"""Real accepted Figures and body numbers share verified exact derivation identity."""

from __future__ import annotations

from arw_research_artifact.service import ResearchArtifactService, verify_plot_receipt

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger import claim_graph, narrative
from arw.kernel.ledger.journal import replay_run
from arw.kernel.state.claim_graph import ClaimRegistration, Occurrence
from arw.kernel.state.models import ArtifactAcceptanceRequest
from arw.kernel.state.numeric_core import NumericPresentation
from tests.integration.test_research_artifacts import request as parent_request
from tests.integration.test_result_plots import aggregate, plot, result_fixture
from tests.unit.test_narrative import plan


def accept_file(run, name, raw, number, kind="manuscript"):
    (run / name).write_bytes(raw)
    state = replay_run(run)
    outcome = RuntimeCommandService(run).accept_artifact(
        ArtifactAcceptanceRequest(
            schema_version="1.0.0",
            run_id=state.run_id,
            event_id=f"evt-00000000-0000-4000-8000-{number:012d}",
            command_id=f"cmd-00000000-0000-4000-8000-{number:012d}",
            occurred_at="2026-07-13T00:02:00Z",
            actor_id="parent.runtime",
            actor_role="parent_control_plane",
            expected_revision=state.revision,
            artifact_id="artifact." + name.replace(".", "-"),
            artifact_kind=kind,
            media_type="application/json",
            content_path=name,
            content_sha256=sha256_hex(raw),
            base_revision=state.revision,
            consumed_sha256=[state.last_event_sha256],
        )
    )
    assert outcome.accepted, outcome.rejection


def scene(tmp_path):
    run, context, ref, _ = result_fixture(tmp_path)
    project = context.project_root
    narrative.register(project)
    narrative.select(project, plan())
    a = aggregate(ref)
    b = aggregate(ref, category="B", pointer="/B", layer_id="layer.b")
    ir = plot((a, b))
    service = ResearchArtifactService()
    outcome = service.qualify(ir, run_root=run, request=parent_request(run, 100))
    assert outcome["qualification"] == "PASS", outcome
    accept_file(run, "body.txt", b"Our accuracy is 0.83 [@a].", 200)
    graph = claim_graph.graph(
        project, run_roots=(run,), figure_verifier=verify_plot_receipt
    )
    figure = next(n for n in graph["nodes"] if n["node_kind"] == "Figure")
    values = figure["figure_adapter"]["plot_values"]
    number = next(
        n
        for n in graph["nodes"]
        if n["node_kind"] == "Occurrence" and n["kind"] == "numeric_token"
    )
    return project, run, graph, figure, values, number


def register_numeric(
    project, run, graph, figure, values, number, *, wrong=False, unknown=False
):
    original = {k: v for k, v in number.items() if k in Occurrence.model_fields}
    a, b = values
    original.update(
        numeric_class="own_result",
        derivation_id="f" * 64
        if unknown
        else b["derivation_id"]
        if wrong
        else a["derivation_id"],
        figure_ref=figure["source"],
        plot_value_id=a["plot_value_id"],
        plot_revision=a["revision"],
    )
    original["presentation"] = NumericPresentation(
        derivation_id=original["derivation_id"],
        decimals=2,
        rounding_mode="ROUND_HALF_EVEN",
    ).model_dump(mode="json")
    reg = ClaimRegistration.model_validate(
        {
            "claim": {
                "claim_id": "claim.accuracy",
                "revision": 1,
                "statement": "Accuracy is the specified result.",
                "claim_kind": "result",
            },
            "occurrences": [original],
            "evidence": [
                {
                    "evidence_id": "evidence.figure",
                    "node_kind": "Figure",
                    "original": figure["source"],
                }
            ],
            "author_id": "author.owner",
        }
    )
    claim_graph.register_claim(
        project, reg, run_roots=(run,), expected_head=graph["snapshot_sha256"]
    )
    return claim_graph.graph(
        project, run_roots=(run,), figure_verifier=verify_plot_receipt
    )


def numeric(view):
    return next(
        n["numeric_verification"]
        for n in view["nodes"]
        if n["node_kind"] == "Occurrence" and n["kind"] == "numeric_token"
    )


def test_verified_figure_shares_exact_body_derivation_and_default_kernel_is_explicit(
    tmp_path,
):
    project, run, view, figure, values, number = scene(tmp_path)
    assert figure["figure_adapter"]["status"] == "verified"
    assert figure["figure_adapter"]["scope"] == "figure_source_integrity_only"
    updated = register_numeric(project, run, view, figure, values, number)
    checked = numeric(updated)
    assert (
        checked["status"] == "passed"
        and checked["derivation_id"] == values[0]["derivation_id"]
    )
    assert (
        checked["exact"] == values[0]["exact"] and checked["expected_display"] == "0.83"
    )
    kernel = claim_graph.graph(project, run_roots=(run,))
    assert numeric(kernel)["status"] == "unsupported"
    assert (
        next(n for n in kernel["nodes"] if n["node_kind"] == "Figure")[
            "figure_adapter"
        ]["status"]
        == "unsupported"
    )
    assert (
        claim_graph.graph(
            project,
            run_roots=(run,),
            as_of=updated["snapshot_manifest"],
            figure_verifier=verify_plot_receipt,
        )
        == updated
    )


def test_same_rounded_value_different_semantics_cannot_reuse_other_derivation(tmp_path):
    project, run, view, figure, values, number = scene(tmp_path)
    assert values[0]["exact"] != values[1]["exact"]
    assert values[0]["derivation_id"] != values[1]["derivation_id"]
    checked = numeric(
        register_numeric(project, run, view, figure, values, number, wrong=True)
    )
    assert (
        checked["status"] == "failed"
        and checked["reason"] == "plot_value_context_mismatch"
    )


def test_unknown_derivation_id_is_not_an_exact_result(tmp_path):
    project, run, view, figure, values, number = scene(tmp_path)
    checked = numeric(
        register_numeric(project, run, view, figure, values, number, unknown=True)
    )
    assert checked["status"] == "unsupported" and "exact" not in checked


def test_accepted_standalone_derivation_is_recomputed_without_a_figure(tmp_path):
    from arw.kernel.policy.numeric_core import evaluate_derivation
    from tests.unit.test_numeric_core import request, selection

    run, context, ref, _ = result_fixture(tmp_path, b"id,score\na,0\nb,0\nc,1\n")
    project = context.project_root
    narrative.register(project)
    narrative.select(project, plan())
    derived = evaluate_derivation(request("mean", selection(ref)), context)
    assert derived.exact.numerator == 1 and derived.exact.denominator == 3
    accept_file(
        run,
        "numeric.json",
        canonical_json_bytes(derived.model_dump(mode="json")),
        201,
        kind="numeric-derivation",
    )
    accept_file(run, "body.txt", b"Our mean is 0.33 [@a].", 202)
    view = claim_graph.graph(project, run_roots=(run,))
    number = next(
        n
        for n in view["nodes"]
        if n["node_kind"] == "Occurrence" and n["kind"] == "numeric_token"
    )
    original = {k: v for k, v in number.items() if k in Occurrence.model_fields}
    original.update(
        numeric_class="own_result",
        derivation_id=derived.derivation_id,
        presentation=NumericPresentation(
            derivation_id=derived.derivation_id,
            decimals=2,
            rounding_mode="ROUND_HALF_EVEN",
        ).model_dump(mode="json"),
    )
    evidence = next(
        n["source"]
        for n in view["nodes"]
        if n.get("source", {}).get("artifact_id") == "artifact.numeric-json"
    )
    registration = ClaimRegistration.model_validate(
        {
            "claim": {
                "claim_id": "claim.mean",
                "revision": 1,
                "statement": "The exact mean is a third.",
                "claim_kind": "result",
            },
            "occurrences": [original],
            "evidence": [
                {
                    "evidence_id": "evidence.derivation",
                    "node_kind": "ExperimentResult",
                    "original": evidence,
                }
            ],
            "author_id": "author.owner",
        }
    )
    claim_graph.register_claim(
        project, registration, run_roots=(run,), expected_head=view["snapshot_sha256"]
    )
    result = numeric(claim_graph.graph(project, run_roots=(run,)))
    assert result["status"] == "passed" and result["exact"] == {
        "numerator": 1,
        "denominator": 3,
    }
    assert result["expected_display"] == "0.33"


def test_generic_parent_acceptance_cannot_make_a_forged_derivation_exact(tmp_path):
    from arw.kernel.policy.numeric_core import evaluate_derivation
    from tests.unit.test_numeric_core import request, scalar

    run, context, ref, _ = result_fixture(tmp_path)
    project = context.project_root
    narrative.register(project)
    narrative.select(project, plan())
    derived = evaluate_derivation(request("value", scalar(ref, "/A")), context)
    forged = derived.model_dump(mode="json")
    forged["derivation_id"] = "f" * 64
    accept_file(
        run,
        "numeric.json",
        canonical_json_bytes(forged),
        201,
        kind="numeric-derivation",
    )
    accept_file(run, "body.txt", b"Our result is 0.83 [@a].", 202)
    view = claim_graph.graph(project, run_roots=(run,))
    number = next(
        n
        for n in view["nodes"]
        if n["node_kind"] == "Occurrence" and n["kind"] == "numeric_token"
    )
    original = {k: v for k, v in number.items() if k in Occurrence.model_fields}
    original.update(
        numeric_class="own_result",
        derivation_id="f" * 64,
        presentation=NumericPresentation(
            derivation_id="f" * 64, decimals=2, rounding_mode="ROUND_HALF_EVEN"
        ).model_dump(mode="json"),
    )
    reg = ClaimRegistration.model_validate(
        {
            "claim": {
                "claim_id": "claim.forged",
                "revision": 1,
                "statement": "Reported own result.",
                "claim_kind": "result",
            },
            "occurrences": [original],
            "author_id": "author.owner",
        }
    )
    claim_graph.register_claim(
        project, reg, run_roots=(run,), expected_head=view["snapshot_sha256"]
    )
    checked = numeric(claim_graph.graph(project, run_roots=(run,)))
    assert (
        checked["status"] == "failed"
        and checked["reason"] == "sealed_derivation_replay_mismatch"
    )
    assert "exact" not in checked


def test_public_claims_handler_composes_the_real_figure_verifier(tmp_path):
    from argparse import ArgumentParser

    from arw.cli_claims import configure, handle

    project, run, _view, figure, _values, _number = scene(tmp_path)
    parser = ArgumentParser()
    configure(parser.add_subparsers(dest="command", required=True))
    args = parser.parse_args(
        [
            "claims",
            "graph",
            "--project-root",
            str(project),
            "--run-root",
            str(run),
            "--json",
        ]
    )
    composed = handle(args)
    actual = next(n for n in composed["nodes"] if n["node_kind"] == "Figure")
    assert actual["figure_adapter"]["status"] == "verified"
    assert (
        actual["figure_adapter"]["plot_values"]
        == figure["figure_adapter"]["plot_values"]
    )


def test_same_numeric_bytes_keep_separate_claim_binding_verdicts(tmp_path):
    project, run, view, figure, values, number = scene(tmp_path)
    first = register_numeric(project, run, view, figure, values, number, wrong=True)
    original = {k: v for k, v in number.items() if k in Occurrence.model_fields}
    original.update(
        numeric_class="own_result",
        derivation_id=values[0]["derivation_id"],
        figure_ref=figure["source"],
        plot_value_id=values[0]["plot_value_id"],
        plot_revision=values[0]["revision"],
        presentation=NumericPresentation(
            derivation_id=values[0]["derivation_id"],
            decimals=2,
            rounding_mode="ROUND_HALF_EVEN",
        ).model_dump(mode="json"),
    )
    reg = ClaimRegistration.model_validate(
        {
            "claim": {
                "claim_id": "claim.accuracy.second",
                "revision": 1,
                "statement": "The second explicitly bound proposition.",
                "claim_kind": "result",
            },
            "occurrences": [original],
            "evidence": [
                {
                    "evidence_id": "evidence.figure",
                    "node_kind": "Figure",
                    "original": figure["source"],
                }
            ],
            "author_id": "author.owner",
        }
    )
    claim_graph.register_claim(
        project, reg, run_roots=(run,), expected_head=first["snapshot_sha256"]
    )
    after = claim_graph.graph(
        project, run_roots=(run,), figure_verifier=verify_plot_receipt, hard_check=True
    )
    claims = {n["claim_id"]: n for n in after["nodes"] if n["node_kind"] == "Claim"}
    assert claims["claim.accuracy"]["numeric_checks"][0]["status"] == "failed"
    assert claims["claim.accuracy.second"]["numeric_checks"][0]["status"] == "passed"
    assert numeric(after) == {
        "status": "not_checked",
        "reason": "multiple_claim_specific_bindings",
    }
    assert any(
        f["code"] == "claim_numeric_binding_not_verified"
        and f["claim_id"] == "claim.accuracy"
        for f in after["hard_checks"]["failures"]
    )
    assert after["hard_checks"]["denominator"]["registered_occurrences"] == 1
    assert after["hard_checks"]["denominator"]["registered_claims"] == 2


def test_verified_figure_historical_snapshot_ignores_a_later_torn_run_tail(tmp_path):
    project, run, view, figure, values, number = scene(tmp_path)
    view = register_numeric(project, run, view, figure, values, number)
    with (run / "journal/segments/00000001.jsonl").open("ab") as handle:
        handle.write(b"{later broken tail")
    rebuilt = claim_graph.graph(
        project,
        run_roots=(run,),
        as_of=view["snapshot_manifest"],
        figure_verifier=verify_plot_receipt,
    )
    assert rebuilt == view
