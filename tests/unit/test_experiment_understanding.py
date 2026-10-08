"""Original CPU response-table evaluation and frozen replay contracts."""

from __future__ import annotations

import json
from copy import deepcopy

import jsonschema
import pytest

from evals.experiment_understanding.offline import (
    FIXTURE,
    SCHEMA,
    ExperimentEvalError,
    canonical,
    load_fixtures,
    load_public,
    main,
    public_input,
    ridge_attempts,
    score,
    sha,
    verify_receipt,
)


def _oracle(state):
    plan, attempts = [], []
    for item in state["reference"]["tasks"]:
        task_id = item["task_id"]
        visible = public_input(state, task_id)
        rows = item["rows"]
        attempt_id = f"oracle.{task_id}"
        plan.append({"attempt_id": attempt_id, "task_id": task_id, "route": "oracle"})
        attempts.append(
            {
                "attempt_id": attempt_id,
                "task_id": task_id,
                "route": "oracle",
                "task_sha256": visible["task_sha256"],
                "observation_sha256": visible["observation_sha256"],
                "observations_used": [row["config"] for row in visible["observations"]],
                "selected_config": min(
                    rows, key=lambda row: (-row["value"], row["config"])
                )["config"],
                "responses": rows,
            }
        )
    return {
        "schema_version": "arw.cpu-four-factor-attempts.v1",
        "plan": plan,
        "attempts": attempts,
    }


def _receipt(state, attempts):
    return json.loads(score(state, canonical(attempts)))


def test_frozen_three_task_fixture_and_public_projection():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    state = load_fixtures()
    assert len(state["taskset"]["tasks"]) == 3
    assert state["taskset"]["budget"] == {
        "max_observations_per_task": 8,
        "required_response_rows": 16,
        "max_model_calls_per_task_route": 1,
    }
    for task in state["taskset"]["tasks"]:
        visible = public_input(load_public(), task["id"])
        assert len(visible["observations"]) == 8
        assert "seed" not in visible and "reference" not in visible
        assert len({row["config"] for row in visible["observations"]}) == 8
        assert visible["task_sha256"] == sha(canonical(task))
        assert visible["observation_sha256"] == sha(canonical(visible["observations"]))
    assert (
        len(
            json.loads((FIXTURE / "hidden-reference.json").read_text())["tasks"][0][
                "rows"
            ]
        )
        == 16
    )


def test_oracle_scores_four_dimensions_separately():
    state = load_fixtures()
    receipt = _receipt(state, _oracle(state))
    assert receipt["live_comparison"] == {"status": "not_measured"}
    assert receipt["summary"]["oracle"]["attempt_count"] == 3
    assert receipt["summary"]["oracle"]["delivery_rate_all_attempts"] == 1
    for item in receipt["attempts"]:
        assert item["status"] == "scored" and item["delivery"] == 1
        assert item["errors"] == {
            "selection_regret": 0.0,
            "conditional_effect_mae": 0.0,
            "pair_interaction_mae": 0.0,
        }
        assert set(item["quality"].values()) == {1.0}
        assert item["cost"] == {
            "tokens": "unavailable",
            "usd": "unavailable",
            "elapsed_ms": "unavailable",
        }


def test_correct_best_configuration_can_have_wrong_effects():
    state = load_fixtures()
    attempts = _oracle(state)
    first = attempts["attempts"][0]
    selected = first["selected_config"]
    first["responses"] = [
        {
            "config": row["config"],
            "value": row["value"] if row["config"] == selected else 0,
        }
        for row in first["responses"]
    ]
    outcome = _receipt(state, attempts)["attempts"][0]
    assert outcome["status"] == "scored"
    assert outcome["errors"]["selection_regret"] == 0
    assert outcome["errors"]["conditional_effect_mae"] > 0
    assert outcome["errors"]["pair_interaction_mae"] > 0


def test_pair_effect_ridge_uses_exact_same_observations_and_replays():
    state = load_fixtures()
    attempts = ridge_attempts(load_public())
    for attempt in attempts["attempts"]:
        visible = public_input(state, attempt["task_id"])
        assert attempt["observations_used"] == [
            row["config"] for row in visible["observations"]
        ]
        assert attempt["observation_sha256"] == visible["observation_sha256"]
        assert len(attempt["responses"]) == 16
    raw = canonical(attempts)
    receipt = score(state, raw)
    assert verify_receipt(receipt, state, raw)
    assert receipt == score(state, raw)
    parsed = json.loads(receipt)
    assert parsed["summary"]["ridge"]["delivered_count"] == 3
    assert any(
        item["errors"]["pair_interaction_mae"] > 0 for item in parsed["attempts"]
    )
    altered = canonical({**attempts, "attempts": attempts["attempts"][:-1]})
    with pytest.raises(ExperimentEvalError, match="receipt_replay_mismatch"):
        verify_receipt(receipt, state, altered)


def test_missing_slot_and_duplicate_submission_remain_in_all_attempt_denominator():
    state = load_fixtures()
    attempts = _oracle(state)
    attempts["attempts"].pop()
    missing = _receipt(state, attempts)
    assert missing["summary"]["oracle"]["attempt_count"] == 3
    assert missing["summary"]["oracle"]["delivered_count"] == 2
    assert missing["summary"]["oracle"]["undelivered_count"] == 1
    assert missing["summary"]["oracle"]["delivery_rate_all_attempts"] == round(2 / 3, 6)
    assert missing["attempts"][-1]["reason_codes"] == ["missing_attempt"]
    assert missing["attempts"][-1]["errors"] is None
    assert missing["attempts"][-1]["quality"]["selection_regret"] == 0
    assert (
        missing["summary"]["oracle"]["metrics"]["selection_regret"][
            "delivered_only_error"
        ]
        == 0
    )

    attempts = _oracle(state)
    attempts["attempts"].append(deepcopy(attempts["attempts"][0]))
    duplicate = _receipt(state, attempts)
    assert duplicate["summary"]["oracle"]["attempt_count"] == 4
    assert duplicate["summary"]["oracle"]["delivered_count"] == 3
    assert duplicate["attempts"][-1]["reason_codes"] == ["duplicate_attempt_id"]


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing", "missing_configurations"),
        ("duplicate", "duplicate_configurations"),
        ("unknown", "unknown_configurations"),
        ("budget", "budget_overrun"),
        ("unknown_observation", "unapproved_observation"),
        ("digest", "observation_digest_mismatch"),
        ("nan", "nonfinite_prediction"),
        ("infinite_exponent", "nonfinite_prediction"),
    ],
)
def test_invalid_delivery_is_typed_and_zero_quality(mutation, code):
    state = load_fixtures()
    attempts = _oracle(state)
    first = attempts["attempts"][0]
    if mutation == "missing":
        first["responses"].pop()
    elif mutation == "duplicate":
        first["responses"].append(deepcopy(first["responses"][0]))
    elif mutation == "unknown":
        first["responses"][0]["config"] = "2222"
    elif mutation == "budget":
        first["observations_used"].append("0001")
    elif mutation == "unknown_observation":
        first["observations_used"][0] = "0001"
    elif mutation == "digest":
        first["observation_sha256"] = "0" * 64
    elif mutation == "nan":
        first["responses"][0]["value"] = float("nan")
    else:
        first["responses"][0]["value"] = float("inf")
    raw = (
        json.dumps(attempts, allow_nan=True).encode()
        if mutation in {"nan", "infinite_exponent"}
        else canonical(attempts)
    )
    outcome = json.loads(score(state, raw))["attempts"][0]
    assert outcome["status"] == "invalid"
    assert code in outcome["reason_codes"]
    assert outcome["delivery"] == 0 and outcome["errors"] is None
    assert set(outcome["quality"].values()) == {0.0}


def test_cost_absence_and_partial_recording_are_not_zero():
    state = load_fixtures()
    attempts = _oracle(state)
    attempts["attempts"][0]["cost"] = {"tokens": 123, "usd": 0.0}
    attempts["attempts"][1]["cost"] = {"usd": -1}
    receipt = _receipt(state, attempts)
    first, second, third = receipt["attempts"]
    assert first["cost"] == {"tokens": 123, "usd": 0.0, "elapsed_ms": "unavailable"}
    assert second["cost"]["usd"] == "unavailable"
    assert second["metadata_reason_codes"] == ["invalid_cost"]
    assert second["delivery"] == 1
    assert set(third["cost"].values()) == {"unavailable"}
    assert receipt["live_comparison"]["status"] == "not_measured"


def test_cli_prepare_ridge_score_verify_and_no_overwrite(tmp_path):
    public = tmp_path / "public.json"
    ridge = tmp_path / "ridge.json"
    receipt = tmp_path / "receipt.json"
    assert main(["prepare", "--task-id", "cpu-batch-v1", "--output", str(public)]) == 0
    visible = json.loads(public.read_text())
    assert len(visible["observations"]) == 8
    assert "reference" not in visible and "seed" not in visible
    assert main(["ridge", "--output", str(ridge)]) == 0
    assert main(["score", "--attempts", str(ridge), "--receipt", str(receipt)]) == 0
    assert main(["verify", "--attempts", str(ridge), "--receipt", str(receipt)]) == 0
    assert main(["ridge", "--output", str(ridge)]) == 2


def test_tampered_reference_manifest_and_observation_budget_fail(tmp_path):
    for name in (
        "taskset.json",
        "hidden-reference.json",
        "observations.json",
        "manifest.json",
    ):
        (tmp_path / name).write_bytes((FIXTURE / name).read_bytes())
    reference = tmp_path / "hidden-reference.json"
    reference.write_bytes(reference.read_bytes() + b" ")
    with pytest.raises(ExperimentEvalError, match="reference_digest_mismatch"):
        load_fixtures(
            tmp_path / "taskset.json",
            tmp_path / "observations.json",
            reference,
            tmp_path / "manifest.json",
        )
    reference.write_bytes((FIXTURE / "hidden-reference.json").read_bytes())
    observations = tmp_path / "observations.json"
    value = json.loads(observations.read_text())
    value["tasks"][0]["rows"].append(value["tasks"][0]["rows"][0])
    observations.write_bytes(canonical(value))
    with pytest.raises(ExperimentEvalError):
        load_public(tmp_path / "taskset.json", observations, tmp_path / "manifest.json")
