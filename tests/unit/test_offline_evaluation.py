"""Offline evaluation contracts; synthetic data never implies empirical quality."""

import json
import os
import socket
from pathlib import Path

import jsonschema
import pytest

from evals.offline import (
    EvaluationError,
    candidate_sample,
    compare,
    digest,
    load_json,
    read_local,
    validate_corpus,
    verify_receipt,
)

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "evals/corpus/v1.json"
SCHEMA = json.loads((ROOT / "schemas/v1/eval-run.schema.json").read_text())


def bundles(tmp_path, corpus=None):
    corpus = corpus or load_json(CORPUS)
    paths = []
    for route in ("baseline", "arw-route"):
        path = tmp_path / f"{route}.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": "arw.eval-bundle.v1",
                    "route": route,
                    "corpus_version": corpus["version"],
                    "results": [
                        {"task_id": c["id"], "answer": c["expected"]}
                        for c in corpus["cases"]
                    ],
                }
            )
        )
        paths.append(path)
    return paths


def test_corpus_contract():
    corpus = load_json(CORPUS)
    validate_corpus(corpus)
    cases = corpus["cases"]
    assert len(cases) >= 30
    assert {c["language"] for c in cases} == {"en", "zh"}
    assert sum(c["adversarial"] for c in cases) >= 10
    assert {c["checker"] for c in cases} == {
        "citation",
        "quote_locator",
        "gate",
        "route",
        "leakage",
    }
    for change in (
        lambda c: c["cases"].append(c["cases"][0]),
        lambda c: c["cases"][0].update(checker="judge"),
        lambda c: c["cases"][0].pop("expected"),
    ):
        bad = json.loads(json.dumps(corpus))
        change(bad)
        with pytest.raises(EvaluationError):
            validate_corpus(bad)


def test_corpus_rejects_duplicate_expected_citation_ids_and_missing_checker():
    corpus = load_json(CORPUS)
    duplicate = json.loads(json.dumps(corpus))
    citations = next(c for c in duplicate["cases"] if c["id"] == "cite-03")["expected"][
        "citations"
    ]
    citations[1]["id"] = citations[0]["id"]
    citations[1]["status"] = "retracted"
    with pytest.raises(EvaluationError, match="duplicate_expected_citation"):
        validate_corpus(duplicate)
    missing = json.loads(json.dumps(corpus))
    for case in missing["cases"]:
        if case["checker"] == "route":
            case["checker"] = "gate"
            case["expected"] = {"gate": "block"}
    with pytest.raises(EvaluationError, match="checker_coverage"):
        validate_corpus(missing)


def test_corpus_rejects_zero_expected_citation_ids():
    corpus = load_json(CORPUS)
    for case in corpus["cases"]:
        if case["checker"] == "citation":
            case["expected"] = {"citations": []}
    with pytest.raises(EvaluationError, match="citation_reference_coverage"):
        validate_corpus(corpus)


def test_retracted_research_object_gate_cases_and_three_way_confusion(tmp_path):
    corpus = load_json(CORPUS)
    research_object_cases = [
        case
        for case in corpus["cases"]
        if case["checker"] == "gate"
        and case["expected"] == {"gate": "human_review"}
        and case["adversarial"]
    ]
    assert {case["language"] for case in research_object_cases} == {"en", "zh"}
    assert len(research_object_cases) >= 2
    assert all(
        "retract" in case["prompt"].lower() or "撤稿" in case["prompt"]
        for case in research_object_cases
    )
    baseline, route = bundles(tmp_path, corpus)
    data = json.loads(route.read_text())
    by_id = {item["task_id"]: item["answer"] for item in data["results"]}
    by_id[research_object_cases[0]["id"]] = {"gate": "block"}
    by_id[research_object_cases[1]["id"]] = {"gate": "pass"}
    by_id["gate-05"] = {"gate": "human_review"}
    by_id["gate-01"] = {"gate": "human_review"}
    for item in data["results"]:
        item["answer"] = by_id[item["task_id"]]
    route.write_text(json.dumps(data))
    receipt = json.loads(compare(CORPUS, baseline, route))
    baseline_scores = receipt["summary"]["baseline"]
    route_scores = receipt["summary"]["arw-route"]
    assert baseline_scores["gate_human_review_as_human_review"] >= 2
    assert route_scores["gate_human_review_as_block"] == 1
    assert route_scores["gate_human_review_as_pass"] == 1
    assert route_scores["gate_block_as_human_review"] == 1
    assert route_scores["gate_pass_as_human_review"] == 1
    assert receipt["summary"]["delta"]["gate_human_review_as_block"] == 1
    assert sum(
        route_scores[f"gate_{expected}_as_{actual}"]
        for expected in ("pass", "block", "human_review")
        for actual in ("pass", "block", "human_review")
    ) == sum(case["checker"] == "gate" for case in corpus["cases"])
    assert route_scores["gate_fp"] == (
        route_scores["gate_pass_as_block"] + route_scores["gate_human_review_as_block"]
    )


def test_stable_receipt_and_schema(tmp_path):
    baseline, route = bundles(tmp_path)
    first = compare(CORPUS, baseline, route)
    second = compare(CORPUS, baseline, route)
    assert first == second
    receipt = json.loads(first)
    jsonschema.Draft202012Validator(SCHEMA).validate(receipt)
    assert receipt["summary"]["baseline"]["citation_recall"] == 1
    assert receipt["summary"]["arw-route"]["citation_recall"] == 1
    assert receipt["summary"]["delta"]["citation_recall"] == 0
    assert receipt["cost"]["baseline"] == {
        "tokens": "unavailable",
        "usd": "unavailable",
        "elapsed_ms": "unavailable",
    }
    assert receipt["model_id"]["baseline"] == "unavailable"
    assert receipt["pairing"] == "unavailable"
    assert len(receipt["cases"]) == 32
    assert verify_receipt(first, CORPUS, baseline, route)
    damaged = first.replace(b'"evaluator_version":"2"', b'"evaluator_version":"3"')
    with pytest.raises((EvaluationError, jsonschema.ValidationError)):
        verify_receipt(damaged, CORPUS, baseline, route)


def test_fail_closed_missing_duplicate_oversized_and_tampered(tmp_path):
    baseline, route = bundles(tmp_path)
    original = json.loads(baseline.read_text())
    for results in (
        original["results"][:-1],
        original["results"] + original["results"][:1],
    ):
        bad = dict(original, results=results)
        baseline.write_text(json.dumps(bad))
        with pytest.raises(EvaluationError):
            compare(CORPUS, baseline, route)
    baseline.write_text(json.dumps(original) + " " * 1_100_000)
    with pytest.raises(EvaluationError, match="size"):
        compare(CORPUS, baseline, route)
    original["results"][0]["answer"] = {"unexpected": True}
    baseline.write_text(json.dumps(original))
    with pytest.raises(EvaluationError):
        compare(CORPUS, baseline, route)


@pytest.mark.parametrize("bundle_name", ["baseline", "arw-route"])
@pytest.mark.parametrize("root", [[], None, "invalid"])
def test_malformed_bundle_root_returns_json_error(tmp_path, capsys, bundle_name, root):
    from evals.offline import main

    baseline, route = bundles(tmp_path)
    bad_path = baseline if bundle_name == "baseline" else route
    bad_path.write_text(json.dumps(root))
    with pytest.raises(EvaluationError, match="invalid_bundle"):
        compare(CORPUS, baseline, route)

    receipt = tmp_path / "receipt.json"
    assert (
        main(
            [
                "--baseline",
                str(baseline),
                "--arw-route",
                str(route),
                "--receipt",
                str(receipt),
            ]
        )
        == 2
    )
    output = capsys.readouterr()
    assert output.out == ""
    assert json.loads(output.err)["error"].startswith("invalid_bundle:")
    assert "Traceback" not in output.err
    assert not receipt.exists()


def test_adversarial_metrics_and_optional_cost(tmp_path):
    baseline, route = bundles(tmp_path)
    corpus = load_json(CORPUS)
    data = json.loads(route.read_text())
    by_id = {r["task_id"]: r for r in data["results"]}
    for case in corpus["cases"]:
        if case["checker"] == "citation" and case["adversarial"]:
            by_id[case["id"]]["answer"] = {
                "citations": [{"id": "fabricated", "status": "valid"}]
            }
        elif case["checker"] == "leakage" and case["adversarial"]:
            by_id[case["id"]]["answer"] = {"text": case["sentinel"]}
        elif case["checker"] == "gate" and case["adversarial"]:
            by_id[case["id"]]["answer"] = {"gate": "pass"}
    data["cost"] = {"tokens": 123, "usd": 0.01, "elapsed_ms": 30}
    data["model_id"] = "recorded-local-id"
    route.write_text(json.dumps(data))
    receipt = json.loads(compare(CORPUS, baseline, route))
    summary = receipt["summary"]["arw-route"]
    assert summary["citation_recall"] < 1
    assert summary["gate_fn"] > 0
    assert summary["leakage_hits"] > 0
    assert receipt["cost"]["arw-route"]["tokens"] == 123
    assert receipt["model_id"]["arw-route"] == "recorded-local-id"


def test_omitted_citations_are_not_perfect_precision(tmp_path):
    baseline, route = bundles(tmp_path)
    data = json.loads(route.read_text())
    for item in data["results"]:
        if item["task_id"].startswith("cite-"):
            item["answer"] = {"citations": []}
    route.write_text(json.dumps(data))
    summary = json.loads(compare(CORPUS, baseline, route))["summary"]["arw-route"]
    assert summary["citation_precision"] == 0
    assert summary["citation_recall"] == 0


def test_exact_status_locator_and_route_are_distinct(tmp_path):
    baseline, route = bundles(tmp_path)
    data = json.loads(route.read_text())
    by_id = {result["task_id"]: result["answer"] for result in data["results"]}
    by_id["cite-06"]["citations"][0]["status"] = "valid"
    by_id["quote-05"]["locator"] = "source-e#other-section"
    by_id["route-05"]["route"] = "writing"
    route.write_text(json.dumps(data))
    receipt = json.loads(compare(CORPUS, baseline, route))
    summary = receipt["summary"]["arw-route"]
    assert summary["citation_recall"] == 1
    assert summary["citation_status_accuracy"] < 1
    assert summary["quote_locator_digest_accuracy"] < 1
    assert summary["route_accuracy"] < 1


def test_candidate_requires_recorded_policy_and_run_identity(tmp_path):
    baseline, route = bundles(tmp_path)
    run_id = "run-00000000-0000-4000-8000-000000000038"
    for path in (baseline, route):
        data = json.loads(path.read_text())
        data["run_id"] = run_id
        path.write_text(json.dumps(data))
    receipt = compare(CORPUS, baseline, route)
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "heuristic_id": "heuristic.eval",
                "proposed_action": "Check citations",
                "actual_action": "Checked exact citation IDs",
                "policy": {
                    "schema_version": "arw.learning-policy.v1",
                    "policy_id": "policy.eval",
                    "version": "1",
                    "mode": "benchmark",
                    "run_subset": [run_id],
                    "metric": "citation_recall",
                    "minimum_delta": 0.0,
                },
            }
        )
    )
    sample = json.loads(candidate_sample(receipt, baseline, route, context))
    sample_schema = json.loads(
        (ROOT / "schemas/v1/research-learning-sample.schema.json").read_text()
    )
    jsonschema.Draft202012Validator(sample_schema).validate(sample)
    assert sample["run_id"] == run_id
    assert sample["mode"] == "benchmark"
    candidate_context = json.loads(context.read_text())
    candidate_context["policy"]["metric"] = "gate_human_review_as_block"
    context.write_text(json.dumps(candidate_context))
    with pytest.raises(EvaluationError, match="bounded_rate"):
        candidate_sample(receipt, baseline, route, context)
    data = json.loads(route.read_text())
    del data["run_id"]
    route.write_text(json.dumps(data))
    with pytest.raises(EvaluationError, match="receipt_or_input_mismatch"):
        candidate_sample(receipt, baseline, route, context)
    new_receipt = compare(CORPUS, baseline, route)
    with pytest.raises(EvaluationError, match="identity"):
        candidate_sample(new_receipt, baseline, route, context)


def test_candidate_replays_full_receipt_not_just_its_hash(tmp_path):
    baseline, route = bundles(tmp_path)
    run_id = "run-00000000-0000-4000-8000-000000000038"
    for path in (baseline, route):
        body = json.loads(path.read_text())
        body["run_id"] = run_id
        path.write_text(json.dumps(body))
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "heuristic_id": "heuristic.eval",
                "proposed_action": "Check citations",
                "actual_action": "Checked IDs",
                "policy": {
                    "schema_version": "arw.learning-policy.v1",
                    "policy_id": "policy.eval",
                    "version": "1",
                    "mode": "benchmark",
                    "run_subset": [run_id],
                    "metric": "citation_recall",
                    "minimum_delta": 0.0,
                },
            }
        )
    )
    receipt = json.loads(compare(CORPUS, baseline, route))
    receipt["summary"]["baseline"]["citation_recall"] = 0.0
    receipt["summary_sha256"] = digest(receipt["summary"])
    receipt["receipt_sha256"] = digest(
        {k: v for k, v in receipt.items() if k != "receipt_sha256"}
    )
    forged = (
        json.dumps(receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()
    with pytest.raises(EvaluationError, match="receipt_or_input_mismatch"):
        candidate_sample(forged, baseline, route, context)


def test_pairing_requires_same_recorded_model(tmp_path):
    baseline, route = bundles(tmp_path)
    left = json.loads(baseline.read_text())
    right = json.loads(route.read_text())
    left["model_id"] = "model-A"
    right["model_id"] = "model-B"
    baseline.write_text(json.dumps(left))
    route.write_text(json.dumps(right))
    with pytest.raises(EvaluationError, match="model_id_mismatch"):
        compare(CORPUS, baseline, route)
    right["model_id"] = "model-A"
    route.write_text(json.dumps(right))
    assert json.loads(compare(CORPUS, baseline, route))["pairing"] == "matched"
    del right["model_id"]
    route.write_text(json.dumps(right))
    assert json.loads(compare(CORPUS, baseline, route))["pairing"] == "unavailable"
    left["model_id"] = "unavailable"
    right["model_id"] = "unavailable"
    baseline.write_text(json.dumps(left))
    route.write_text(json.dumps(right))
    with pytest.raises(EvaluationError):
        compare(CORPUS, baseline, route)


def test_read_local_rejects_symlink_swap_at_open(tmp_path, monkeypatch):
    target = tmp_path / "input.json"
    target.write_text("original")
    secret = tmp_path / "secret.json"
    secret.write_text("SECRET")
    actual_open = os.open

    def swap(path, flags, *args, **kwargs):
        if os.fspath(path) == os.fspath(target):
            target.unlink()
            target.symlink_to(secret)
        return actual_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", swap)
    with pytest.raises(EvaluationError):
        read_local(target)


def test_read_local_rejects_path_replacement_after_read(tmp_path, monkeypatch):
    target = tmp_path / "input.json"
    target.write_text("original")
    replacement = tmp_path / "replacement.json"
    replacement.write_text("changed!")
    actual_read = os.read
    changed = False

    def swap(fd, count):
        nonlocal changed
        data = actual_read(fd, count)
        if not changed:
            changed = True
            target.unlink()
            replacement.rename(target)
        return data

    monkeypatch.setattr(os, "read", swap)
    with pytest.raises(EvaluationError):
        read_local(target)


def test_reject_symlink_and_duplicate_json_keys(tmp_path):
    baseline, route = bundles(tmp_path)
    link = tmp_path / "linked.json"
    link.symlink_to(baseline)
    with pytest.raises(EvaluationError):
        compare(CORPUS, link, route)
    baseline.write_text('{"schema_version":"x","schema_version":"y"}')
    with pytest.raises(EvaluationError, match="duplicate_key"):
        compare(CORPUS, baseline, route)
    baseline.write_text(
        bundles(tmp_path)[0]
        .read_text()
        .replace('"results":', '"cost":{"usd":NaN},"results":')
    )
    with pytest.raises(EvaluationError, match="nonfinite_number"):
        compare(CORPUS, baseline, route)


def test_cli_writes_local_receipt_and_refuses_overwrite(tmp_path):
    from evals.offline import main

    baseline, route = bundles(tmp_path)
    receipt = tmp_path / "receipt.json"
    args = [
        "--baseline",
        str(baseline),
        "--arw-route",
        str(route),
        "--receipt",
        str(receipt),
    ]
    assert main(args) == 0
    assert verify_receipt(receipt.read_bytes(), CORPUS, baseline, route)
    assert main(args) == 2


def test_cli_rolls_back_first_output_when_second_install_fails(tmp_path, monkeypatch):
    from evals.offline import main

    baseline, route = bundles(tmp_path)
    run_id = "run-00000000-0000-4000-8000-000000000038"
    for path in (baseline, route):
        body = json.loads(path.read_text())
        body["run_id"] = run_id
        path.write_text(json.dumps(body))
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "heuristic_id": "heuristic.eval",
                "proposed_action": "Check citations",
                "actual_action": "Checked IDs",
                "policy": {
                    "schema_version": "arw.learning-policy.v1",
                    "policy_id": "policy.eval",
                    "version": "1",
                    "mode": "benchmark",
                    "run_subset": [run_id],
                    "metric": "citation_recall",
                    "minimum_delta": 0.0,
                },
            }
        )
    )
    receipt = tmp_path / "receipt.json"
    candidate = tmp_path / "candidate.json"
    actual_link = os.link
    calls = 0

    def fail_second(source, destination, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated second install failure")
        return actual_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", fail_second)
    args = [
        "--baseline",
        str(baseline),
        "--arw-route",
        str(route),
        "--receipt",
        str(receipt),
        "--candidate-context",
        str(context),
        "--candidate-out",
        str(candidate),
    ]
    assert main(args) == 2
    assert not receipt.exists() and not candidate.exists()
    assert not list(tmp_path.glob(".arw-eval-*"))
    monkeypatch.setattr(os, "link", actual_link)
    candidate.write_text("existing user result")
    assert main(args) == 2
    assert candidate.read_text() == "existing user result"
    assert not receipt.exists()
    candidate.unlink()
    assert main(args) == 0
    assert verify_receipt(receipt.read_bytes(), CORPUS, baseline, route)
    assert json.loads(candidate.read_bytes())["mode"] == "benchmark"


def test_cli_cleans_staging_if_first_output_was_replaced_during_rollback(
    tmp_path, monkeypatch
):
    from evals.offline import main

    baseline, route = bundles(tmp_path)
    run_id = "run-00000000-0000-4000-8000-000000000038"
    for path in (baseline, route):
        body = json.loads(path.read_text())
        body["run_id"] = run_id
        path.write_text(json.dumps(body))
    context = tmp_path / "context.json"
    context.write_text(
        json.dumps(
            {
                "heuristic_id": "heuristic.eval",
                "proposed_action": "Check citations",
                "actual_action": "Checked IDs",
                "policy": {
                    "schema_version": "arw.learning-policy.v1",
                    "policy_id": "policy.eval",
                    "version": "1",
                    "mode": "benchmark",
                    "run_subset": [run_id],
                    "metric": "citation_recall",
                    "minimum_delta": 0.0,
                },
            }
        )
    )
    receipt = tmp_path / "receipt.json"
    candidate = tmp_path / "candidate.json"
    actual_link = os.link
    calls = 0

    def replace_then_fail(source, destination, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            receipt.unlink()
            receipt.write_text("another writer")
            raise OSError("second install failed")
        return actual_link(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "link", replace_then_fail)
    assert (
        main(
            [
                "--baseline",
                str(baseline),
                "--arw-route",
                str(route),
                "--receipt",
                str(receipt),
                "--candidate-context",
                str(context),
                "--candidate-out",
                str(candidate),
            ]
        )
        == 2
    )
    assert receipt.read_text() == "another writer"
    assert not candidate.exists()
    assert not list(tmp_path.glob(".arw-eval-*"))


def test_no_network_or_credential_access(tmp_path, monkeypatch):
    baseline, route = bundles(tmp_path)

    def denied(*args, **kwargs):
        raise AssertionError("unexpected network or credential access")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr("os.getenv", denied)
    compare(CORPUS, baseline, route)
