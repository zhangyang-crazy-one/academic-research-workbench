from __future__ import annotations

import json
import os
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import jsonschema
import pytest

from arw.kernel.artifacts.experiment_acceptance import (
    ExperimentAcceptanceError,
    evaluate_experiment_acceptance,
    freeze_experiment_contract,
    experiment_acceptance_schema_documents,
    load_experiment_acceptance,
    load_experiment_contract,
    publish_experiment_acceptance,
    publish_experiment_contract,
    replay_experiment_acceptance,
    seal_experiment_acceptance,
    seal_experiment_contract,
)
from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex

ROOT = Path(__file__).resolve().parents[2]
CLAIM_SHA = "c" * 64
SCORES_CSV = "sample,score\ns1,0.5\ns2,0.75\ns3,1\n"


def _metric(name: str, value: int | float, unit: str) -> dict[str, object]:
    digest = sha256_hex(canonical_json_bytes({"name": name, "unit": unit, "value": value}))
    return {"name": name, "value": value, "unit": unit, "metric_sha256": digest}


def _provenance(
    root: Path,
    *,
    metrics: list[dict[str, object]] | None = None,
    files: dict[str, str] | None = None,
    declared_sha: dict[str, str] | None = None,
) -> dict[str, object]:
    files = {"artifact.scores": SCORES_CSV} if files is None else files
    artifacts = []
    for artifact_id, text in sorted(files.items()):
        relative = f"results/{artifact_id}.csv"
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        artifacts.append(
            {
                "artifact_id": artifact_id,
                "media_type": "text/csv",
                "content_sha256": (declared_sha or {}).get(artifact_id, sha256_hex(text.encode("utf-8"))),
                "manifest_sha256": "1" * 64,
                "content_path": relative,
            }
        )
    metrics = metrics if metrics is not None else [
        _metric("accuracy", 0.75, "ratio"),
        _metric("baseline_accuracy", 0.7, "ratio"),
        _metric("gpu_hours", 3, "hour"),
    ]
    return {
        "schema_version": "arw.experiment-provenance.v1",
        "provenance_id": "provenance.exp-001",
        "run_id": "run-00000000-0000-4000-8000-000000000031",
        "experiment_id": "experiment.baseline-001",
        "source_datasets": [
            {
                "uri_or_path": "https://example.invalid/datasets/iris.json",
                "content_sha256": "498b9c10429a6517400aafd3c2bbac55a4f8d5c16b607b4344493856c7b8e082",
                "access_state": "publicly_verified",
                "manifest_sha256": "b" * 64,
            }
        ],
        "model_identity": [
            {
                "name": "example-model",
                "revision": "v1.2.3",
                "source_sha256": "acfc18d91e43f67e646ca04de8580c83062e736985c420c16199f5606ff60bf1",
            }
        ],
        "configuration": [
            {
                "name": "default",
                "canonical_sha256": "1203d2d7b9daa167bef051bcc1b4f51ec83268b45d688624e83f23754878ad9f",
                "content_type": "application/json",
            }
        ],
        "metrics": sorted(metrics, key=lambda item: str(item["name"])),
        "artifacts": artifacts,
        "environment": [
            {"key": "python.version", "redacted_value_or_digest": "3.14.6", "tool_version": "3.14.6", "redacted": True}
        ],
        "runner": {
            "identity": "runner.external-001",
            "command_digest": "2" * 64,
            "host_digest": "3" * 64,
            "started_at": "2026-07-15T10:00:00Z",
            "finished_at": "2026-07-15T10:05:00Z",
        },
        "execution_claim": {"mode": "external_only", "status": "imported"},
        "qualification_receipts": [],
        "source_manifest_sha256": ["4" * 64],
        "created_at": "2026-07-15T10:05:00Z",
    }


def _reproduction(**overrides: object) -> dict[str, object]:
    check: dict[str, object] = {
        "check_id": "check.mean-score",
        "kind": "numeric_reproduction",
        "reported_metric": "accuracy",
        "unit": "ratio",
        "operator": "mean@1",
        "data": {"artifact_id": "artifact.scores", "format": "csv", "column": "score", "row_id_column": "sample"},
        "tolerance": {"absolute": "0", "relative": "0"},
    }
    check.update(overrides)
    return check


def _context(**overrides: str) -> dict[str, str]:
    context = {
        "metric_definition": "top-1 accuracy",
        "unit": "ratio",
        "dataset": "scores-v1",
        "split": "test",
        "evaluation_condition": "single pass, no augmentation",
    }
    context.update(overrides)
    return context


def _comparison(**overrides: object) -> dict[str, object]:
    check: dict[str, object] = {
        "check_id": "check.beats-baseline",
        "kind": "baseline_comparison",
        "candidate": {"label": "ours", "reported_metric": "accuracy", "context": _context()},
        "baseline": {"label": "prior", "reported_metric": "baseline_accuracy", "context": _context()},
        "direction": "higher_is_better",
        "threshold": {"mode": "absolute", "value": "0.05"},
    }
    check.update(overrides)
    return check


def _contract(*checks: dict[str, object], **overrides: object) -> dict[str, object]:
    contract: dict[str, object] = {
        "schema_version": "arw.experiment-contract.v1",
        "contract_id": "contract.claim-001",
        "contract_version": 1,
        "claim_id": "claim.accuracy-gain",
        "claim_sha256": CLAIM_SHA,
        "declared_timing": "predeclared",
        "checks": list(checks) or [_reproduction()],
    }
    contract.update(overrides)
    return contract


def _single(result) -> tuple[str, tuple[str, ...]]:
    (check,) = result.checks
    return check.status, check.reasons


# --- Deterministic replay -----------------------------------------------------


def test_same_inputs_replay_to_identical_bytes_and_digest(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path)
    contract = _contract(_reproduction(), _comparison())
    first = evaluate_experiment_acceptance(contract, provenance, tmp_path)
    second = evaluate_experiment_acceptance(contract, provenance, tmp_path)
    assert first.canonical_bytes() == second.canonical_bytes()
    assert first.result_sha256 == second.result_sha256
    assert first.overall_status == "passed"
    assert first.scope == "contract_conformance_only"
    assert replay_experiment_acceptance(first, contract, provenance, tmp_path) == first


def test_replay_rejects_a_result_that_no_longer_matches(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path)
    contract = _contract()
    result = evaluate_experiment_acceptance(contract, provenance, tmp_path)
    forged = result.model_dump(mode="json", exclude_none=True)
    forged["checks"][0]["observed"] = "0.8"
    with pytest.raises(ExperimentAcceptanceError) as error:
        replay_experiment_acceptance(forged, contract, provenance, tmp_path)
    assert error.value.code == "replay_mismatch"


def test_contract_and_result_are_write_once_content_addressed(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path)
    contract = seal_experiment_contract(_contract())
    result = evaluate_experiment_acceptance(contract, provenance, tmp_path)
    contract_path = publish_experiment_contract(tmp_path, contract)
    result_path = publish_experiment_acceptance(tmp_path, result)
    assert contract_path.name == f"{contract.contract_sha256}.json"
    assert result_path.name == f"{result.result_sha256}.json"
    assert load_experiment_contract(tmp_path, contract.contract_sha256) == contract
    assert load_experiment_acceptance(tmp_path, result.result_sha256) == result
    result_path.chmod(0o644)
    result_path.write_bytes(result_path.read_bytes().replace(b'"passed"', b'"failed"', 1))
    with pytest.raises(ExperimentAcceptanceError) as error:
        load_experiment_acceptance(tmp_path, result.result_sha256)
    assert error.value.code == "digest_mismatch"


def test_checked_in_schemas_match_models_and_validate_results(tmp_path: Path) -> None:
    documents = experiment_acceptance_schema_documents()
    for name, document in documents.items():
        checked = json.loads((ROOT / "schemas/v1" / name).read_text(encoding="utf-8"))
        assert checked == document
    result = evaluate_experiment_acceptance(_contract(_reproduction(), _comparison()), _provenance(tmp_path), tmp_path)
    jsonschema.Draft202012Validator(documents["experiment-acceptance.schema.json"]).validate(
        result.model_dump(mode="json", exclude_none=True)
    )
    jsonschema.Draft202012Validator(documents["experiment-contract.schema.json"]).validate(
        seal_experiment_contract(_contract(_reproduction(), _comparison())).model_dump(mode="json", exclude_none=True)
    )


# --- Numeric reproduction and baseline comparison -------------------------------


@pytest.mark.parametrize(
    ("operator", "expected"),
    [("mean@1", "0.75"), ("sum@1", "2.25"), ("min@1", "0.5"), ("max@1", "1"), ("median@1", "0.75"), ("count@1", "3")],
)
def test_whitelisted_operators_recompute_exact_decimals(tmp_path: Path, operator: str, expected: str) -> None:
    metric_value = {"mean@1": 0.75, "sum@1": 2.25, "min@1": 0.5, "max@1": 1, "median@1": 0.75, "count@1": 3}[operator]
    provenance = _provenance(tmp_path, metrics=[_metric("accuracy", metric_value, "ratio")])
    result = evaluate_experiment_acceptance(_contract(_reproduction(operator=operator)), provenance, tmp_path)
    (check,) = result.checks
    assert (check.status, check.observed, check.sample_count) == ("passed", expected, 3)


@pytest.mark.parametrize("scores", ["1e50\n1\n-1e50", "-1e50\n1e50\n1", "1\n-1e50\n1e50"])
@pytest.mark.parametrize("reported,status", [(0, "failed"), (1, "passed")])
def test_exact_sum_survives_cancellation_and_row_order(
    tmp_path: Path, scores: str, reported: int, status: str
) -> None:
    csv = "sample,score\n" + "".join(f"s{i},{value}\n" for i, value in enumerate(scores.splitlines()))
    provenance = _provenance(tmp_path, metrics=[_metric("accuracy", reported, "ratio")], files={"artifact.scores": csv})
    contract = _contract(_reproduction(operator="sum@1"))
    result = evaluate_experiment_acceptance(contract, provenance, tmp_path)
    assert result.evaluator_version == "1.2.0"
    assert (result.checks[0].status, result.checks[0].observed) == (status, "1")
    assert replay_experiment_acceptance(result, contract, provenance, tmp_path).result_sha256 == result.result_sha256


def test_old_receipt_replays_with_old_arithmetic_and_digest(tmp_path: Path) -> None:
    csv = "sample,score\ns1,1e50\ns2,1\ns3,-1e50\n"
    provenance = _provenance(tmp_path, metrics=[_metric("accuracy", 0, "ratio")], files={"artifact.scores": csv})
    contract = _contract(_reproduction(operator="sum@1"))
    fixture_bytes = (ROOT / "tests/fixtures/experiment_acceptance_1_0_0.json").read_bytes()
    old = seal_experiment_acceptance(json.loads(fixture_bytes))
    assert (old.evaluator_version, old.checks[0].status, old.checks[0].observed) == ("1.0.0", "passed", "0")
    assert old.canonical_bytes() == fixture_bytes
    digest = old.result_sha256
    assert digest == "ddc7628cf747ccdc9a0bf86e0a20fb1bc7efa5ebd3955599064317605deed4cc"
    publish_experiment_acceptance(tmp_path, old)
    loaded = load_experiment_acceptance(tmp_path, digest)
    assert replay_experiment_acceptance(loaded, contract, provenance, tmp_path).result_sha256 == digest
    assert evaluate_experiment_acceptance(contract, provenance, tmp_path).result_sha256 != digest


def test_historical_1_1_caller_timing_receipt_replays_as_unverified_assertion(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path)
    contract = _contract()
    raw = (ROOT / "tests/fixtures/experiment_acceptance_1_1_0_caller_timing.json").read_bytes()
    recorded = seal_experiment_acceptance(json.loads(raw))
    assert recorded.canonical_bytes() == raw
    assert recorded.result_sha256 == "6d380d6287cdc86209403ba8c2529851f7bf61a0761aa8eb08cc8d0f16bc1a50"
    assert recorded.timing_scope is None
    assert recorded.predeclaration == "verified_predeclared"
    assert replay_experiment_acceptance(
        recorded, contract, provenance, tmp_path,
        timing={"contract_sequence": 2, "provenance_sequence": 3},
    ) == recorded


@pytest.mark.parametrize("score", ["1e-100", "1e100"])
def test_scientific_values_produce_bounded_replayable_results(tmp_path: Path, score: str) -> None:
    provenance = _provenance(tmp_path, metrics=[_metric("accuracy", 0, "ratio")], files={"artifact.scores": f"sample,score\ns1,{score}\n"})
    contract = _contract(_reproduction(operator="sum@1"))
    result = evaluate_experiment_acceptance(contract, provenance, tmp_path)
    assert result.checks[0].status == "failed"
    assert result.checks[0].observed == score
    assert len(result.checks[0].observed) <= 64
    assert replay_experiment_acceptance(result, contract, provenance, tmp_path) == result


@pytest.mark.parametrize("score", ["1e1000000", "1e1001", "1e-1001", "1." + "1" * 65])
def test_unsupported_numeric_domain_blocks_with_typed_result(tmp_path: Path, score: str) -> None:
    provenance = _provenance(tmp_path, files={"artifact.scores": f"sample,score\ns1,{score}\n"})
    result = evaluate_experiment_acceptance(_contract(), provenance, tmp_path)
    assert _single(result) == ("invalid_artifact", ("value_out_of_supported_range",))


def test_unsupported_contract_numeric_domain_blocks_with_typed_result(tmp_path: Path) -> None:
    contract = _contract(_reproduction(tolerance={"absolute": "1e1000000", "relative": "0"}))
    result = evaluate_experiment_acceptance(contract, _provenance(tmp_path), tmp_path)
    assert _single(result) == ("invalid_contract", ("value_out_of_supported_range",))


def test_exact_sum_reports_scientifically_when_combined_value_is_long(tmp_path: Path) -> None:
    csv = "sample,score\ns1,1e1000\ns2,1e-1000\n"
    provenance = _provenance(tmp_path, files={"artifact.scores": csv})
    result = evaluate_experiment_acceptance(_contract(_reproduction(operator="sum@1")), provenance, tmp_path)
    assert result.checks[0].status == "failed"
    assert result.checks[0].observed == "1e1000"


def test_exact_range_boundary_is_inclusive(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path, files={"artifact.scores": "sample,score\ns1,1e-100\n"})
    at_boundary = evaluate_experiment_acceptance(
        _contract(_reproduction(valid_range={"minimum": "1e-100", "maximum": "1e-100"})),
        provenance, tmp_path,
    )
    assert at_boundary.checks[0].status == "failed"  # range passes; reported 0.75 differs
    assert at_boundary.checks[0].reasons == ("reproduction_outside_tolerance",)
    below = evaluate_experiment_acceptance(
        _contract(_reproduction(valid_range={"minimum": "1.000000000000000000000000000001e-100"})),
        provenance, tmp_path,
    )
    assert _single(below) == ("invalid_artifact", ("value_out_of_range",))


def test_exact_mean_and_tolerance_boundaries_after_cancellation(tmp_path: Path) -> None:
    csv = "sample,score\ns1,1e50\ns2,1\ns3,-1e50\n"
    provenance = _provenance(tmp_path, metrics=[_metric("accuracy", 0, "ratio")], files={"artifact.scores": csv})
    at_boundary = evaluate_experiment_acceptance(
        _contract(_reproduction(operator="mean@1", tolerance={"absolute": "0." + "3" * 60, "relative": "0"})),
        provenance, tmp_path,
    )
    assert at_boundary.checks[0].status == "failed"  # finite decimal is strictly below 1/3
    inclusive = evaluate_experiment_acceptance(
        _contract(_reproduction(operator="mean@1", tolerance={"absolute": "0.5", "relative": "0"})),
        provenance, tmp_path,
    )
    assert inclusive.checks[0].status == "passed"


def test_exact_baseline_threshold_does_not_round_cancellation(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path, metrics=[_metric("accuracy", 10**50 - 1, "ratio"), _metric("baseline_accuracy", 0, "ratio")])
    result = evaluate_experiment_acceptance(
        _contract(_comparison(threshold={"mode": "absolute", "value": "1e50"})), provenance, tmp_path
    )
    assert _single(result) == ("failed", ("improvement_below_threshold",))


def test_relative_threshold_does_not_round_repeating_ratio_into_pass(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path, metrics=[_metric("accuracy", 5, "ratio"), _metric("baseline_accuracy", 3, "ratio")])
    threshold = "0." + "6" * 49 + "7"
    contract = _contract(_comparison(threshold={"mode": "relative", "value": threshold}))
    exact = evaluate_experiment_acceptance(contract, provenance, tmp_path)
    legacy = evaluate_experiment_acceptance(contract, provenance, tmp_path, evaluator_version="1.0.0")
    assert _single(exact) == ("failed", ("improvement_below_threshold",))
    assert legacy.checks[0].status == "passed"


def test_budget_limit_outside_supported_domain_is_typed(tmp_path: Path) -> None:
    contract = _contract(budget={"usage_metric": "gpu_hours", "unit": "hour", "limit": "1e1000000"})
    result = evaluate_experiment_acceptance(contract, _provenance(tmp_path), tmp_path)
    assert result.overall_status == "passed"
    assert result.budget_status == "invalid_contract"


def test_reproduction_outside_tolerance_fails(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path, metrics=[_metric("accuracy", 0.8, "ratio")])
    result = evaluate_experiment_acceptance(_contract(), provenance, tmp_path)
    assert _single(result) == ("failed", ("reproduction_outside_tolerance",))
    assert result.overall_status == "failed"


@pytest.mark.parametrize(
    ("tolerance", "status"),
    [
        ({"absolute": "0.05", "relative": "0"}, "passed"),  # |0.75-0.8| == 0.05: boundary is inclusive
        ({"absolute": "0.0499", "relative": "0"}, "failed"),
        ({"absolute": "0", "relative": "0.0625"}, "passed"),  # 0.0625 * 0.8 == 0.05
        ({"absolute": "0", "relative": "0.0624"}, "failed"),
    ],
)
def test_absolute_and_relative_tolerance_boundaries(tmp_path: Path, tolerance: dict[str, str], status: str) -> None:
    provenance = _provenance(tmp_path, metrics=[_metric("accuracy", 0.8, "ratio")])
    result = evaluate_experiment_acceptance(_contract(_reproduction(tolerance=tolerance)), provenance, tmp_path)
    assert result.checks[0].status == status


@pytest.mark.parametrize(
    ("direction", "threshold", "status"),
    [
        ("higher_is_better", {"mode": "absolute", "value": "0.05"}, "passed"),  # equality passes
        ("higher_is_better", {"mode": "absolute", "value": "0.0501"}, "failed"),
        ("lower_is_better", {"mode": "absolute", "value": "0"}, "failed"),  # direction reversed
        ("higher_is_better", {"mode": "relative", "value": "0.05"}, "passed"),  # 0.05/0.7 = 0.0714
        ("higher_is_better", {"mode": "relative", "value": "0.08"}, "failed"),
    ],
)
def test_baseline_comparison_direction_and_threshold(
    tmp_path: Path, direction: str, threshold: dict[str, str], status: str
) -> None:
    result = evaluate_experiment_acceptance(
        _contract(_comparison(direction=direction, threshold=threshold)), _provenance(tmp_path), tmp_path
    )
    assert result.checks[0].status == status


def test_lower_is_better_passes_when_candidate_is_smaller(tmp_path: Path) -> None:
    provenance = _provenance(
        tmp_path, metrics=[_metric("accuracy", 0.1, "ratio"), _metric("baseline_accuracy", 0.3, "ratio")]
    )
    result = evaluate_experiment_acceptance(
        _contract(_comparison(direction="lower_is_better", threshold={"mode": "absolute", "value": "0.2"})),
        provenance,
        tmp_path,
    )
    assert _single(result) == ("passed", ())


def test_relative_threshold_with_zero_baseline_is_an_invalid_contract(tmp_path: Path) -> None:
    provenance = _provenance(
        tmp_path, metrics=[_metric("accuracy", 0.1, "ratio"), _metric("baseline_accuracy", 0, "ratio")]
    )
    result = evaluate_experiment_acceptance(
        _contract(_comparison(threshold={"mode": "relative", "value": "0.1"})), provenance, tmp_path
    )
    assert _single(result) == ("invalid_contract", ("relative_threshold_zero_baseline",))


def test_unit_conflict_is_never_converted(tmp_path: Path) -> None:
    provenance = _provenance(
        tmp_path, metrics=[_metric("accuracy", 75, "percent"), _metric("baseline_accuracy", 0.7, "ratio")]
    )
    result = evaluate_experiment_acceptance(_contract(_comparison()), provenance, tmp_path)
    assert _single(result) == ("invalid_contract", ("unit_mismatch",))
    reproduction = evaluate_experiment_acceptance(_contract(), provenance, tmp_path)
    assert _single(reproduction) == ("invalid_contract", ("unit_mismatch",))


@pytest.mark.parametrize("field", ["metric_definition", "unit", "dataset", "split", "evaluation_condition"])
def test_incomparable_contexts_are_refused(tmp_path: Path, field: str) -> None:
    baseline = {"label": "prior", "reported_metric": "baseline_accuracy", "context": _context(**{field: "other"})}
    result = evaluate_experiment_acceptance(_contract(_comparison(baseline=baseline)), _provenance(tmp_path), tmp_path)
    assert _single(result) == ("invalid_contract", ("incomparable_context", f"context_{field}_mismatch"))


# --- Invalid data never counts as a pass -------------------------------------


@pytest.mark.parametrize(
    ("csv_text", "reason"),
    [
        ("sample,score\ns1,0.5\ns2,NaN\n", "non_finite_value"),
        ("sample,score\ns1,0.5\ns2,-Infinity\n", "non_finite_value"),
        ("sample,score\ns1,0.5\ns2,abc\n", "non_numeric_value"),
        ("sample,score\ns1,0.5\ns2,\n", "missing_value"),
        ("sample,score\ns1,0.5\ns1,0.7\n", "duplicate_sample_id"),
        ("sample,score\n,0.5\n", "missing_sample_id"),
        ("sample,value\ns1,0.5\n", "column_missing"),
        ("sample,score\ns1,0.5,9\n", "csv_malformed"),
        ("sample,score\n", "no_samples"),
    ],
)
def test_invalid_values_block_acceptance(tmp_path: Path, csv_text: str, reason: str) -> None:
    provenance = _provenance(tmp_path, files={"artifact.scores": csv_text})
    result = evaluate_experiment_acceptance(_contract(), provenance, tmp_path)
    assert _single(result) == ("invalid_artifact", (reason,))
    assert result.overall_status == "invalid_artifact"


def test_missing_values_may_be_excluded_only_when_declared(tmp_path: Path) -> None:
    provenance = _provenance(
        tmp_path,
        files={"artifact.scores": "sample,score\ns1,0.5\ns2,\ns3,1\n"},
    )
    selector = {"artifact_id": "artifact.scores", "format": "csv", "column": "score", "missing_values": "exclude"}
    result = evaluate_experiment_acceptance(_contract(_reproduction(data=selector)), provenance, tmp_path)
    (check,) = result.checks
    assert (check.status, check.sample_count, check.excluded_missing) == ("passed", 2, 1)


def test_values_outside_the_declared_range_block(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path, files={"artifact.scores": "sample,score\ns1,0.5\ns2,1.5\n"})
    check = _reproduction(valid_range={"minimum": "0", "maximum": "1"})
    result = evaluate_experiment_acceptance(_contract(check), provenance, tmp_path)
    assert _single(result) == ("invalid_artifact", ("value_out_of_range",))
    comparison = _comparison(valid_range={"maximum": "0.72"})
    assert _single(evaluate_experiment_acceptance(_contract(comparison), _provenance(tmp_path), tmp_path)) == (
        "invalid_artifact",
        ("value_out_of_range",),
    )


def test_missing_raw_output_differs_from_a_tampered_one(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path)
    (tmp_path / "results/artifact.scores.csv").unlink()
    assert _single(evaluate_experiment_acceptance(_contract(), provenance, tmp_path)) == (
        "evidence_missing",
        ("raw_output_missing",),
    )
    tampered = _provenance(tmp_path, declared_sha={"artifact.scores": "e" * 64})
    assert _single(evaluate_experiment_acceptance(_contract(), tampered, tmp_path)) == (
        "invalid_artifact",
        ("artifact_digest_mismatch",),
    )


def test_missing_reported_metric_is_evidence_missing(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path, metrics=[_metric("loss", 0.1, "nat")])
    assert _single(evaluate_experiment_acceptance(_contract(), provenance, tmp_path)) == (
        "evidence_missing",
        ("reported_metric_missing",),
    )


def test_artifact_unknown_to_provenance_is_an_invalid_contract(tmp_path: Path) -> None:
    selector = {"artifact_id": "artifact.other", "format": "csv", "column": "score"}
    result = evaluate_experiment_acceptance(_contract(_reproduction(data=selector)), _provenance(tmp_path), tmp_path)
    assert _single(result) == ("invalid_contract", ("unknown_artifact",))


# --- Confinement ----------------------------------------------------------------


def test_symlinked_artifact_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside.csv"
    outside.write_text(SCORES_CSV, encoding="utf-8")
    root = tmp_path / "run"
    root.mkdir()
    provenance = _provenance(root)
    target = root / "results/artifact.scores.csv"
    target.unlink()
    target.symlink_to(outside)
    assert _single(evaluate_experiment_acceptance(_contract(), provenance, root)) == (
        "invalid_artifact",
        ("artifact_path_unsafe",),
    )


def test_symlinked_parent_directory_is_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    (outside / "artifact.scores.csv").write_text(SCORES_CSV, encoding="utf-8")
    root = tmp_path / "run"
    root.mkdir()
    provenance = _provenance(root)
    (root / "results/artifact.scores.csv").unlink()
    (root / "results").rmdir()
    (root / "results").symlink_to(outside, target_is_directory=True)
    assert _single(evaluate_experiment_acceptance(_contract(), provenance, root)) == (
        "invalid_artifact",
        ("artifact_path_unsafe",),
    )


def test_traversal_and_absolute_paths_cannot_enter_provenance(tmp_path: Path) -> None:
    from arw.kernel.artifacts.experiment_provenance import ProvenanceError, seal_experiment_provenance

    for bad in ("../secret.csv", "/etc/passwd"):
        payload = _provenance(tmp_path)
        payload["artifacts"][0]["content_path"] = bad  # type: ignore[index]
        with pytest.raises(ProvenanceError):
            seal_experiment_provenance(payload)


def test_symlinked_artifact_root_is_refused(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(ExperimentAcceptanceError) as error:
        evaluate_experiment_acceptance(_contract(), _provenance(real), link)
    assert error.value.code == "unsafe_artifact_root"


# --- Versioning, predeclaration, unsupported claims, budgets ----------------------


def test_changed_threshold_is_a_new_version_and_old_result_still_replays(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path)
    original = seal_experiment_contract(_contract(_comparison(threshold={"mode": "absolute", "value": "0.1"})))
    failed = evaluate_experiment_acceptance(original, provenance, tmp_path, timing={"contract_sequence": 3, "provenance_sequence": 9}, evaluator_version="1.0.0")
    assert (failed.overall_status, failed.predeclaration) == ("failed", "verified_predeclared")

    revised = seal_experiment_contract(
        _contract(
            _comparison(threshold={"mode": "absolute", "value": "0.05"}),
            contract_version=2,
            supersedes_contract_sha256=original.contract_sha256,
        )
    )
    # The revision was recorded after the results existed, so it cannot be
    # treated as fixed in advance even though it still says "predeclared".
    passed = evaluate_experiment_acceptance(revised, provenance, tmp_path, timing={"contract_sequence": 12, "provenance_sequence": 9}, evaluator_version="1.0.0")
    assert revised.contract_sha256 != original.contract_sha256
    assert (passed.overall_status, passed.predeclaration) == ("passed", "predeclaration_contradicted")
    assert replay_experiment_acceptance(
        failed, original, provenance, tmp_path, timing={"contract_sequence": 3, "provenance_sequence": 9}
    ) == failed


def test_predeclaration_needs_ledger_order_not_self_report(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path)
    assert evaluate_experiment_acceptance(_contract(), provenance, tmp_path).predeclaration == "predeclaration_unverified"
    exploratory = _contract(declared_timing="exploratory")
    assert (
        evaluate_experiment_acceptance(exploratory, provenance, tmp_path, timing={"contract_sequence": 1, "provenance_sequence": 2}).predeclaration
        == "exploratory"
    )


def test_contract_versions_must_chain(tmp_path: Path) -> None:
    with pytest.raises(ExperimentAcceptanceError):
        seal_experiment_contract(_contract(contract_version=2))
    with pytest.raises(ExperimentAcceptanceError):
        seal_experiment_contract(_contract(supersedes_contract_sha256="f" * 64))


@pytest.mark.parametrize(
    "kind",
    ["statistical_significance", "conditional_effect", "interaction_effect", "causal_effect", "leaderboard_rank"],
)
def test_unsupported_claim_types_never_degrade_into_a_pass(tmp_path: Path, kind: str) -> None:
    unsupported = {"check_id": "check.extra", "kind": kind, "description": "claim the MVP cannot assess"}
    result = evaluate_experiment_acceptance(_contract(_reproduction(), unsupported), _provenance(tmp_path), tmp_path)
    statuses = {check.check_id: check.status for check in result.checks}
    assert statuses == {"check.mean-score": "passed", "check.extra": "unsupported"}
    assert result.overall_status == "unsupported"


def test_overall_status_follows_fixed_severity(tmp_path: Path) -> None:
    provenance = _provenance(tmp_path, metrics=[_metric("accuracy", 0.8, "ratio"), _metric("baseline_accuracy", 0.7, "ratio")])
    failing = _reproduction()
    missing = _reproduction(check_id="check.missing", reported_metric="absent")
    result = evaluate_experiment_acceptance(_contract(failing, missing), provenance, tmp_path)
    assert [check.status for check in result.checks] == ["failed", "evidence_missing"]
    assert result.overall_status == "evidence_missing"
    forged = result.model_dump(mode="json", exclude_none=True)
    forged["overall_status"] = "failed"
    from arw.kernel.artifacts.experiment_acceptance import seal_experiment_acceptance

    with pytest.raises(ExperimentAcceptanceError):
        seal_experiment_acceptance(forged)


@pytest.mark.parametrize(
    ("budget", "metrics", "status"),
    [
        (None, None, "not_declared"),
        ({"usage_metric": "gpu_hours", "unit": "hour", "limit": "3"}, None, "within_budget"),
        ({"usage_metric": "gpu_hours", "unit": "hour", "limit": "2"}, None, "exceeded"),
        ({"usage_metric": "gpu_hours", "unit": "hour", "limit": "2"}, [_metric("accuracy", 0.75, "ratio")], "unverifiable"),
        ({"usage_metric": "gpu_hours", "unit": "second", "limit": "2"}, None, "invalid_contract"),
    ],
)
def test_budget_is_reported_separately_from_effect(
    tmp_path: Path, budget: dict[str, str] | None, metrics: list[dict[str, object]] | None, status: str
) -> None:
    contract = _contract() if budget is None else _contract(budget=budget)
    result = evaluate_experiment_acceptance(contract, _provenance(tmp_path, metrics=metrics), tmp_path)
    assert result.budget_status == status
    assert result.checks[0].status == "passed"


# --- No execution, network, model, or credentials ------------------------------


def test_script_payloads_are_data_and_nothing_is_executed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = 'sample,score\ns1,"=cmd|\' /C calc\'!A0"\ns2,__import__("os").system("touch pwned")\n'
    provenance = _provenance(tmp_path, files={"artifact.scores": payload})

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("the evaluator must not execute or connect")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    result = evaluate_experiment_acceptance(_contract(), provenance, tmp_path)
    assert _single(result) == ("invalid_artifact", ("non_numeric_value",))
    assert not (tmp_path / "pwned").exists()


def test_acceptance_does_not_unlock_the_reproduced_claim_capability(tmp_path: Path) -> None:
    from arw.kernel.artifacts.experiment_provenance import evaluate_controlled_execution_policy, seal_experiment_provenance

    provenance = seal_experiment_provenance(_provenance(tmp_path))
    result = evaluate_experiment_acceptance(_contract(), provenance, tmp_path)
    assert result.overall_status == "passed"
    decision = evaluate_controlled_execution_policy(provenance, now="2026-07-16T00:00:00Z")
    assert decision.status == "BLOCKED"


# --- CLI ------------------------------------------------------------------------


def test_cli_accepts_publishes_and_replays(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from arw.cli import main
    from arw.kernel.artifacts.experiment_provenance import publish_experiment_provenance, seal_experiment_provenance

    provenance = seal_experiment_provenance(_provenance(tmp_path))
    publish_experiment_provenance(tmp_path, provenance)
    contract_file = tmp_path / "contract.json"
    contract_file.write_text(json.dumps(_contract(_reproduction(), _comparison())), encoding="utf-8")

    assert main(
        [
            "experiment", "accept", "--run-root", str(tmp_path), "--contract", str(contract_file),
            "--provenance-sha256", provenance.provenance_sha256, "--publish",
        ]
    ) == 0
    accepted = json.loads(capsys.readouterr().out)
    assert accepted["result"]["overall_status"] == "passed"
    assert accepted["result"]["predeclaration"] == "predeclaration_unverified"
    assert accepted["result_path"] == f"experiment/acceptance/sha256/{accepted['result_sha256']}.json"

    assert main(["experiment", "replay", "--run-root", str(tmp_path), "--result-sha256", accepted["result_sha256"]]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "status": "replayed",
        "result_sha256": accepted["result_sha256"],
        "overall_status": "passed",
    }

    (tmp_path / "results/artifact.scores.csv").write_text("sample,score\ns1,0.9\n", encoding="utf-8")
    assert main(["experiment", "replay", "--run-root", str(tmp_path), "--result-sha256", accepted["result_sha256"]]) == 65
    assert json.loads(capsys.readouterr().out)["code"] == "replay_mismatch"


def test_cli_rejects_an_invalid_contract(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from arw.cli import main
    from arw.kernel.artifacts.experiment_provenance import publish_experiment_provenance, seal_experiment_provenance

    provenance = seal_experiment_provenance(_provenance(tmp_path))
    publish_experiment_provenance(tmp_path, provenance)
    contract_file = tmp_path / "contract.json"
    contract_file.write_text(json.dumps(_contract(contract_version=2)), encoding="utf-8")
    assert main(
        [
            "experiment", "accept", "--run-root", str(tmp_path), "--contract", str(contract_file),
            "--provenance-sha256", provenance.provenance_sha256,
        ]
    ) == 65
    assert json.loads(capsys.readouterr().out)["code"] == "invalid_contract"


# --- Parent journal contract admission -------------------------------------------


def _journal_run(tmp_path: Path) -> Path:
    from arw.kernel.ledger.journal import initialize_run
    from arw.kernel.ledger.workflows import CORE_WORKFLOW
    from arw.kernel.state.models import InitRunRequest

    root = tmp_path / "run"
    source = root / "input/source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("external experiment source\n", encoding="utf-8")
    initialize_run(root, InitRunRequest.model_validate({
        "schema_version": "1.0.0",
        "run_id": "run-00000000-0000-4000-8000-000000000031",
        "occurred_at": "2026-07-15T10:00:00Z",
        "immutable_input": {"path": "input/source.txt", "sha256": sha256_hex(source.read_bytes())},
        "workflow_family": "academic-pipeline",
        "workflow_mode": "inline-role-prompts",
        "workflow_definition_id": CORE_WORKFLOW.definition_id,
        "workflow_definition_sha256": CORE_WORKFLOW.sha256,
        "journal_layout": "segmented-v1",
        "capabilities": ["canonical-journal"],
        "event_id": "evt-00000000-0000-4000-8000-000000000031",
        "command_id": "cmd-00000000-0000-4000-8000-000000000031",
        "actor_id": "parent.runtime",
    }))
    return root


def _journal_request(revision: int, identity: int, *, occurred_at: str = "2026-07-15T10:05:00Z"):
    from arw.kernel.state.models import RuntimeCommandRequest

    return RuntimeCommandRequest.model_validate({
        "schema_version": "1.0.0",
        "run_id": "run-00000000-0000-4000-8000-000000000031",
        "event_id": f"evt-00000000-0000-4000-8000-{identity:012x}",
        "command_id": f"cmd-00000000-0000-4000-8000-{identity:012x}",
        "expected_revision": revision,
        "occurred_at": occurred_at,
        "actor_id": "parent.runtime",
        "actor_role": "parent_control_plane",
    })


def _admit_provenance(root: Path, revision: int, identity: int):
    from arw.kernel.artifacts.experiment_provenance import ProvenanceAuthorityEnvelope, ingest_experiment_provenance
    from arw.kernel.execution.runtime import RuntimeCommandService

    provenance = _provenance(root)
    return ingest_experiment_provenance(
        provenance, root, ProvenanceAuthorityEnvelope(
            RuntimeCommandService(root), _journal_request(revision, identity, occurred_at="2020-01-01T00:00:00Z")
        ),
    ).provenance


def test_parent_freeze_uses_journal_order_and_ignores_fake_timing(tmp_path: Path) -> None:
    from arw.kernel.execution.runtime import RuntimeCommandService

    root = _journal_run(tmp_path)
    contract = seal_experiment_contract(_contract(_comparison()))
    checked, path, outcome = freeze_experiment_contract(
        contract, root, RuntimeCommandService(root), _journal_request(1, 32, occurred_at="2030-01-01T00:00:00Z")
    )
    assert (checked.contract_sha256, outcome.event.sequence, outcome.event.schema_version) == (
        contract.contract_sha256, 2, "1.5.0"
    )
    assert path.is_file()
    event_schema = json.loads((ROOT / "schemas/v1/event.schema.json").read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(event_schema).validate(outcome.event.model_dump(mode="json"))
    old_version = outcome.event.model_dump(mode="json")
    old_version["schema_version"] = "1.0.0"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(event_schema).validate(old_version)
    provenance = _admit_provenance(root, 2, 33)
    result = evaluate_experiment_acceptance(
        contract, provenance, root, timing={"contract_sequence": 99, "provenance_sequence": 1}
    )
    assert result.predeclaration == "verified_predeclared"
    assert result.timing_scope == "parent_acceptance_order_only"
    assert replay_experiment_acceptance(result, contract, provenance, root) == result


def test_reverse_and_missing_admission_remain_scoped(tmp_path: Path) -> None:
    from arw.kernel.artifacts.experiment_provenance import publish_experiment_provenance, seal_experiment_provenance
    from arw.kernel.execution.runtime import RuntimeCommandService

    root = _journal_run(tmp_path)
    contract = seal_experiment_contract(_contract(_comparison()))
    provenance = seal_experiment_provenance(_provenance(root))
    publish_experiment_provenance(root, provenance)
    assert evaluate_experiment_acceptance(contract, provenance, root, timing={"contract_sequence": 1, "provenance_sequence": 2}).predeclaration == "predeclaration_unverified"
    _admit_provenance(root, 1, 32)
    freeze_experiment_contract(contract, root, RuntimeCommandService(root), _journal_request(2, 33))
    result = evaluate_experiment_acceptance(contract, provenance, root, timing={"contract_sequence": 1, "provenance_sequence": 2})
    assert (result.predeclaration, result.timing_scope) == ("predeclaration_contradicted", "parent_acceptance_order_only")


def test_successor_is_independent_and_prior_failed_receipt_replays(tmp_path: Path) -> None:
    from arw.kernel.execution.runtime import RuntimeCommandService

    root = _journal_run(tmp_path)
    original = seal_experiment_contract(_contract(_comparison(threshold={"mode": "absolute", "value": "0.1"})))
    freeze_experiment_contract(original, root, RuntimeCommandService(root), _journal_request(1, 32))
    provenance = _admit_provenance(root, 2, 33)
    failed = evaluate_experiment_acceptance(original, provenance, root)
    revised = seal_experiment_contract(_contract(
        _comparison(threshold={"mode": "absolute", "value": "0.05"}),
        contract_version=2, supersedes_contract_sha256=original.contract_sha256,
    ))
    freeze_experiment_contract(revised, root, RuntimeCommandService(root), _journal_request(3, 34))
    passed = evaluate_experiment_acceptance(revised, provenance, root)
    assert (failed.overall_status, failed.predeclaration) == ("failed", "verified_predeclared")
    assert (passed.overall_status, passed.predeclaration) == ("passed", "predeclaration_contradicted")
    assert replay_experiment_acceptance(failed, original, provenance, root) == failed
    assert replay_experiment_acceptance(passed, revised, provenance, root) == passed


def test_unverified_result_stays_byte_replayable_after_later_admissions(tmp_path: Path) -> None:
    from arw.kernel.execution.runtime import RuntimeCommandService

    root = _journal_run(tmp_path)
    contract = seal_experiment_contract(_contract(_comparison()))
    provenance = _provenance(root)
    earlier = evaluate_experiment_acceptance(contract, provenance, root)
    assert earlier.predeclaration == "predeclaration_unverified"
    assert earlier.timing_scope is None
    freeze_experiment_contract(contract, root, RuntimeCommandService(root), _journal_request(1, 32))
    _admit_provenance(root, 2, 33)
    assert replay_experiment_acceptance(earlier, contract, provenance, root).result_sha256 == earlier.result_sha256
    assert evaluate_experiment_acceptance(contract, provenance, root).predeclaration == "verified_predeclared"


def test_freeze_rejects_duplicate_command_stale_revision_and_bad_successors(tmp_path: Path) -> None:
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.ledger.journal import replay_run

    root = _journal_run(tmp_path)
    runtime = RuntimeCommandService(root)
    first = seal_experiment_contract(_contract(_comparison()))
    freeze_experiment_contract(first, root, runtime, _journal_request(1, 32))
    retry = _journal_request(1, 32).model_copy(update={
        "event_id": "evt-00000000-0000-4000-8000-000000000039"
    })
    with pytest.raises(ExperimentAcceptanceError, match="duplicate-command-id"):
        freeze_experiment_contract(first, root, runtime, retry)
    with pytest.raises(ExperimentAcceptanceError, match="stale-revision"):
        freeze_experiment_contract(first, root, runtime, _journal_request(1, 33))
    missing = _contract(_comparison(), contract_version=2, supersedes_contract_sha256="f" * 64)
    with pytest.raises(ExperimentAcceptanceError, match="predecessor_missing"):
        freeze_experiment_contract(missing, root, runtime, _journal_request(2, 34))
    unaccepted = seal_experiment_contract(_contract(_comparison(), contract_id="contract.imported"))
    publish_experiment_contract(root, unaccepted)
    imported_successor = _contract(
        _comparison(), contract_id="contract.imported", contract_version=2,
        supersedes_contract_sha256=unaccepted.contract_sha256,
    )
    with pytest.raises(ExperimentAcceptanceError, match="predecessor_missing"):
        freeze_experiment_contract(imported_successor, root, runtime, _journal_request(2, 40))
    wrong_claim = _contract(
        _comparison(), contract_version=2, supersedes_contract_sha256=first.contract_sha256,
        claim_sha256="d" * 64,
    )
    with pytest.raises(ExperimentAcceptanceError, match="predecessor_claim_mismatch"):
        freeze_experiment_contract(wrong_claim, root, runtime, _journal_request(2, 35))
    wrong_version = _contract(_comparison(), contract_version=3, supersedes_contract_sha256=first.contract_sha256)
    with pytest.raises(ExperimentAcceptanceError, match="contract_version_gap"):
        freeze_experiment_contract(wrong_version, root, runtime, _journal_request(2, 36))
    second = seal_experiment_contract(_contract(
        _comparison(threshold={"mode": "absolute", "value": "0.04"}),
        contract_version=2, supersedes_contract_sha256=first.contract_sha256,
    ))
    freeze_experiment_contract(second, root, runtime, _journal_request(2, 37))
    fork = _contract(
        _comparison(threshold={"mode": "absolute", "value": "0.03"}),
        contract_version=2, supersedes_contract_sha256=first.contract_sha256,
    )
    with pytest.raises(ExperimentAcceptanceError, match="contract_chain_fork"):
        freeze_experiment_contract(fork, root, runtime, _journal_request(3, 38))
    assert [event.event_type for event in replay_run(root).events].count("experiment.contract.accepted") == 2


def test_concurrent_freeze_at_one_revision_accepts_once(tmp_path: Path) -> None:
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.ledger.journal import replay_run

    root = _journal_run(tmp_path)
    contract = seal_experiment_contract(_contract())

    def attempt(identity: int) -> str:
        try:
            freeze_experiment_contract(contract, root, RuntimeCommandService(root, lock_timeout=2), _journal_request(1, identity))
            return "accepted"
        except ExperimentAcceptanceError as error:
            return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (32, 33)))
    assert sorted(outcomes) == ["accepted", "stale-revision"]
    assert [event.event_type for event in replay_run(root).events].count("experiment.contract.accepted") == 1


def test_tampered_journal_or_accepted_contract_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from arw.cli import main
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.ledger.journal import JournalError
    from arw.kernel.ledger.manifests import ManifestError

    root = _journal_run(tmp_path)
    contract = seal_experiment_contract(_contract())
    freeze_experiment_contract(contract, root, RuntimeCommandService(root), _journal_request(1, 32))
    provenance = _admit_provenance(root, 2, 33)
    assert evaluate_experiment_acceptance(contract, provenance, root).timing_scope == "parent_acceptance_order_only"
    contract_file = root / f"experiment/contracts/sha256/{contract.contract_sha256}.json"
    original = contract_file.read_bytes()
    contract_file.write_bytes(original.replace(b'"predeclared"', b'"exploratory"'))
    with pytest.raises((ExperimentAcceptanceError, ManifestError, JournalError)):
        evaluate_experiment_acceptance(contract, provenance, root)
    contract_file.write_bytes(original)
    segment = root / "journal/segments/00000001.jsonl"
    data = segment.read_bytes()
    segment.write_bytes(data.replace(b'"experiment.contract.accepted"', b'"experiment.contract.rejected"', 1))
    with pytest.raises((JournalError, ExperimentAcceptanceError)):
        evaluate_experiment_acceptance(contract, provenance, root)
    contract_input = tmp_path / "contract.json"
    contract_input.write_bytes(contract.canonical_bytes())
    assert main([
        "experiment", "accept", "--run-root", str(root), "--contract", str(contract_input),
        "--provenance-sha256", provenance.provenance_sha256,
    ]) == 65
    assert json.loads(capsys.readouterr().out)["code"] in {"journal_invalid", "journal_unhealthy"}


def test_cli_freeze_accept_and_replay_use_parent_admission(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from arw.cli import main

    root = _journal_run(tmp_path)
    contract_file = tmp_path / "contract.json"
    contract_file.write_text(json.dumps(_contract(_comparison())), encoding="utf-8")
    request_file = tmp_path / "request.json"
    request_file.write_text(json.dumps(_journal_request(1, 32).model_dump(mode="json")), encoding="utf-8")
    assert main(["experiment", "freeze", "--run-root", str(root), "--contract", str(contract_file), "--request", str(request_file)]) == 0
    frozen = json.loads(capsys.readouterr().out)
    assert (frozen["status"], frozen["accepted_revision"], frozen["sequence"]) == ("frozen", 2, 2)
    provenance = _admit_provenance(root, 2, 33)
    assert main([
        "experiment", "accept", "--run-root", str(root), "--contract", str(contract_file),
        "--provenance-sha256", provenance.provenance_sha256, "--publish",
    ]) == 0
    accepted = json.loads(capsys.readouterr().out)
    assert (accepted["result"]["evaluator_version"], accepted["result"]["predeclaration"]) == (
        "1.2.0", "verified_predeclared"
    )
    assert accepted["result"]["timing_scope"] == "parent_acceptance_order_only"
    assert main(["experiment", "replay", "--run-root", str(root), "--result-sha256", accepted["result_sha256"]]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "replayed"


def test_replay_loads_each_contract_once_and_skips_unrelated_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Contract succession on replay must not rescan the whole journal."""
    from arw.kernel.artifacts import experiment_acceptance as acceptance
    from arw.kernel.execution.runtime import RuntimeCommandService
    from arw.kernel.ledger import journal, manifests

    root = _journal_run(tmp_path)
    previous = None
    for version in range(1, 6):
        contract = seal_experiment_contract(_contract(
            _comparison(threshold={"mode": "absolute", "value": f"0.0{version}"}),
            contract_version=version,
            supersedes_contract_sha256=None if previous is None else previous.contract_sha256,
        ))
        freeze_experiment_contract(
            contract, root, RuntimeCommandService(root), _journal_request(version, 40 + version)
        )
        previous = contract

    loads: list[str] = []
    original_load = acceptance.load_experiment_contract
    monkeypatch.setattr(
        acceptance,
        "load_experiment_contract",
        lambda run_root, digest: loads.append(digest) or original_load(run_root, digest),
    )
    batch_sizes: list[int] = []
    original_validate = journal.validate_accepted_event_manifests
    monkeypatch.setattr(
        journal,
        "validate_accepted_event_manifests",
        lambda run_root, events: batch_sizes.append(len(events)) or original_validate(run_root, events),
    )
    replayed = journal.replay_run(root)
    contracts = [e for e in replayed.events if e.event_type == "experiment.contract.accepted"]
    assert len(contracts) == 5
    assert sorted(loads) == sorted(e.payload.contract_sha256 for e in contracts)
    assert all(size == 1 for size in batch_sizes)
    # The standalone validator keeps the same verdict with one load per contract.
    loads.clear()
    manifests.validate_accepted_event_manifests(root, replayed.events)
    assert len(loads) == 5
