"""Offline, original four-factor response-table evaluator. No model execution."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from itertools import combinations
from pathlib import Path

import jsonschema

from evals.experiment_understanding.v1_fixture import CONFIGS, FORMULAS, reference_rows
from evals.offline import _install_outputs, read_local

ROOT = Path(__file__).resolve().parent
FIXTURE = ROOT / "v1"
SCHEMA = ROOT / "v1.schema.json"
ERRORS = ("selection_regret", "conditional_effect_mae", "pair_interaction_mae")


class ExperimentEvalError(ValueError):
    def __init__(self, code: str, message: str = ""):
        self.code = code
        super().__init__(message or code)


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ExperimentEvalError("duplicate_json_key", key)
        result[key] = value
    return result


def _parse(raw: bytes, *, allow_nonfinite: bool = False):
    try:
        return json.loads(
            raw,
            object_pairs_hook=_unique_object,
            parse_constant=(
                (lambda token: {"nonfinite_json_token": token})
                if allow_nonfinite
                else (lambda token: _reject_nonfinite(token))
            ),
        )
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ExperimentEvalError("invalid_json", str(error)) from error


def _reject_nonfinite(token):
    raise ExperimentEvalError("nonfinite_fixture_value", token)


def _validate(value, definition: str):
    schema = _parse(read_local(SCHEMA))
    validator = jsonschema.Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]}
    )
    errors = list(validator.iter_errors(value))
    if errors:
        raise ExperimentEvalError(
            f"invalid_{definition}", f"{errors[0].json_path}: {errors[0].message}"
        )


def _read(path: Path, *, allow_nonfinite: bool = False):
    raw = read_local(path)
    return raw, _parse(raw, allow_nonfinite=allow_nonfinite)


def _ids(rows):
    return [row["config"] for row in rows]


def load_public(
    taskset_path: Path = FIXTURE / "taskset.json",
    observations_path: Path = FIXTURE / "observations.json",
    manifest_path: Path = FIXTURE / "manifest.json",
):
    taskset_raw, taskset = _read(taskset_path)
    observations_raw, observations = _read(observations_path)
    _, manifest = _read(manifest_path)
    _validate(taskset, "taskset")
    _validate(observations, "observations")
    if (
        manifest.get("schema_version") != "arw.cpu-four-factor-fixture-manifest.v1"
        or sha(taskset_raw) != manifest.get("taskset_sha256")
        or sha(observations_raw) != manifest.get("observations_sha256")
        or observations["taskset_sha256"] != sha(taskset_raw)
        or observations["reference_sha256"] != manifest.get("reference_sha256")
    ):
        raise ExperimentEvalError("fixture_digest_mismatch")
    task_ids = [task["id"] for task in taskset["tasks"]]
    observation_ids = [task["task_id"] for task in observations["tasks"]]
    if (
        task_ids != list(FORMULAS)
        or observation_ids != task_ids
        or len(set(task_ids)) != 3
        or len(set(observation_ids)) != 3
    ):
        raise ExperimentEvalError("taskset_identity_mismatch")
    for item in observations["tasks"]:
        ids = _ids(item["rows"])
        if (
            len(ids) != 8
            or len(set(ids)) != 8
            or any(config not in CONFIGS for config in ids)
        ):
            raise ExperimentEvalError("invalid_observation_configuration")
        if any(
            type(row["value"]) not in (int, float) or not math.isfinite(row["value"])
            for row in item["rows"]
        ):
            raise ExperimentEvalError("invalid_observation_value")
    return {
        "taskset": taskset,
        "observations": observations,
        "taskset_sha256": sha(taskset_raw),
        "observations_sha256": sha(observations_raw),
        "reference_sha256": manifest["reference_sha256"],
    }


def load_fixtures(
    taskset_path: Path = FIXTURE / "taskset.json",
    observations_path: Path = FIXTURE / "observations.json",
    reference_path: Path = FIXTURE / "hidden-reference.json",
    manifest_path: Path = FIXTURE / "manifest.json",
):
    state = load_public(taskset_path, observations_path, manifest_path)
    reference_raw, reference = _read(reference_path)
    _validate(reference, "reference")
    if (
        sha(reference_raw) != state["reference_sha256"]
        or reference["taskset_sha256"] != state["taskset_sha256"]
        or [task["task_id"] for task in reference["tasks"]]
        != [task["id"] for task in state["taskset"]["tasks"]]
    ):
        raise ExperimentEvalError("reference_digest_mismatch")
    for item, observed in zip(reference["tasks"], state["observations"]["tasks"]):
        if (
            item["seed"] != FORMULAS[item["task_id"]]["seed"]
            or item["rows"] != reference_rows(item["task_id"])
            or _ids(item["rows"]) != list(CONFIGS)
        ):
            raise ExperimentEvalError("reference_table_mismatch")
        indexed = {row["config"]: row["value"] for row in item["rows"]}
        if any(indexed[row["config"]] != row["value"] for row in observed["rows"]):
            raise ExperimentEvalError("observation_reference_mismatch")
    state["reference"] = reference
    return state


def public_input(state, task_id: str):
    task = next(
        (task for task in state["taskset"]["tasks"] if task["id"] == task_id), None
    )
    if task is None:
        raise ExperimentEvalError("unknown_task", task_id)
    observed = next(
        item["rows"]
        for item in state["observations"]["tasks"]
        if item["task_id"] == task_id
    )
    value = {
        "schema_version": "arw.cpu-four-factor-public-input.v1",
        "taskset_version": state["taskset"]["version"],
        "task_id": task_id,
        "task_sha256": sha(canonical(task)),
        "observation_sha256": sha(canonical(observed)),
        "title": task["title"],
        "question": task["question"],
        "factors": task["factors"],
        "factor_levels": state["taskset"]["factor_levels"],
        "metric": state["taskset"]["metric"],
        "budget": state["taskset"]["budget"],
        "stopping_rules": state["taskset"]["stopping_rules"],
        "observations": observed,
    }
    _validate(value, "public_input")
    return value


def _features(config: str):
    bits = [1 if bit == "1" else -1 for bit in config]
    return [1.0, *bits, *(bits[i] * bits[j] for i, j in combinations(range(4), 2))]


def _solve(matrix, vector):
    """Partial-pivot Gaussian elimination for the fixed 11-column ridge model."""
    n = len(vector)
    work = [list(row) + [vector[i]] for i, row in enumerate(matrix)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(work[row][column]))
        if abs(work[pivot][column]) < 1e-12:
            raise ExperimentEvalError("ridge_singular")
        work[column], work[pivot] = work[pivot], work[column]
        scale = work[column][column]
        work[column] = [value / scale for value in work[column]]
        for row in range(n):
            if row == column:
                continue
            multiple = work[row][column]
            work[row] = [a - multiple * b for a, b in zip(work[row], work[column])]
    return [row[-1] for row in work]


def ridge_attempts(state):
    """Fit pair effects from the same frozen eight rows exposed to an agent."""
    plan, attempts = [], []
    for task in state["taskset"]["tasks"]:
        task_id = task["id"]
        public = public_input(state, task_id)
        rows = public["observations"]
        features = [_features(row["config"]) for row in rows]
        count = len(features[0])
        matrix = [
            [
                sum(row[i] * row[j] for row in features)
                + (1.0 if i == j and i else 0.0)
                for j in range(count)
            ]
            for i in range(count)
        ]
        vector = [
            sum(row[i] * observed["value"] for row, observed in zip(features, rows))
            for i in range(count)
        ]
        coefficients = _solve(matrix, vector)
        predicted = {
            config: round(
                sum(
                    weight * feature
                    for weight, feature in zip(coefficients, _features(config))
                ),
                6,
            )
            for config in CONFIGS
        }
        attempt_id = f"ridge.{task_id}"
        plan.append({"attempt_id": attempt_id, "task_id": task_id, "route": "ridge"})
        attempts.append(
            {
                "attempt_id": attempt_id,
                "task_id": task_id,
                "route": "ridge",
                "method": "pair-effect-ridge",
                "method_settings": {"lambda": 1.0},
                "task_sha256": public["task_sha256"],
                "observation_sha256": public["observation_sha256"],
                "observations_used": [row["config"] for row in rows],
                "selected_config": min(
                    CONFIGS, key=lambda config: (-predicted[config], config)
                ),
                "responses": [
                    {"config": config, "value": predicted[config]} for config in CONFIGS
                ],
            }
        )
    return {
        "schema_version": "arw.cpu-four-factor-attempts.v1",
        "plan": plan,
        "attempts": attempts,
    }


def _replace(config: str, changes: dict[int, str]):
    bits = list(config)
    for position, value in changes.items():
        bits[position] = value
    return "".join(bits)


def _errors(reference: dict[str, float], predicted: dict[str, float], selected: str):
    best = max(reference.values())
    selection = best - reference[selected]
    conditional = []
    for factor in range(4):
        for config in CONFIGS:
            if config[factor] != "0":
                continue
            high = _replace(config, {factor: "1"})
            conditional.append(
                abs(
                    (predicted[high] - predicted[config])
                    - (reference[high] - reference[config])
                )
            )
    interaction = []
    for first, second in combinations(range(4), 2):
        for config in CONFIGS:
            if config[first] != "0" or config[second] != "0":
                continue
            a = _replace(config, {first: "1"})
            b = _replace(config, {second: "1"})
            ab = _replace(config, {first: "1", second: "1"})
            predicted_contrast = (
                predicted[ab] - predicted[a] - predicted[b] + predicted[config]
            )
            reference_contrast = (
                reference[ab] - reference[a] - reference[b] + reference[config]
            )
            interaction.append(abs(predicted_contrast - reference_contrast))
    return {
        "selection_regret": round(selection, 6),
        "conditional_effect_mae": round(sum(conditional) / len(conditional), 6),
        "pair_interaction_mae": round(sum(interaction) / len(interaction), 6),
    }


def _cost(attempt):
    supplied = attempt.get("cost") if isinstance(attempt, dict) else None
    result = {
        "tokens": "unavailable",
        "usd": "unavailable",
        "elapsed_ms": "unavailable",
    }
    reasons = []
    if supplied is None:
        return result, reasons
    if not isinstance(supplied, dict) or set(supplied) - set(result):
        return result, ["invalid_cost"]
    for key, value in supplied.items():
        if (
            type(value) not in (int, float)
            or not math.isfinite(value)
            or value < 0
            or (key in {"tokens", "elapsed_ms"} and type(value) is not int)
        ):
            reasons.append("invalid_cost")
        else:
            result[key] = value
    return result, sorted(set(reasons))


def _score_one(attempt, public, reference):
    reasons = []
    cost, cost_reasons = _cost(attempt)
    metadata_reasons = list(cost_reasons)
    model_id = attempt.get("model_id")
    if model_id is not None and (
        not isinstance(model_id, str)
        or not model_id.strip()
        or model_id.strip().lower() == "unavailable"
    ):
        metadata_reasons.append("invalid_model_id")
    settings = attempt.get("model_settings")
    if settings is not None and (
        not isinstance(settings, dict)
        or len(settings) > 32
        or any(
            not isinstance(key, str)
            or type(value) not in (str, int, float, bool)
            or (type(value) is float and not math.isfinite(value))
            for key, value in settings.items()
        )
    ):
        metadata_reasons.append("invalid_model_settings")
    base = {
        "attempt_id": attempt.get("attempt_id"),
        "task_id": public["task_id"],
        "route": attempt.get("route"),
        "task_sha256": public["task_sha256"],
        "observation_sha256": public["observation_sha256"],
        "declared_task_sha256": attempt.get("task_sha256", "unavailable"),
        "declared_observation_sha256": attempt.get("observation_sha256", "unavailable"),
        "method": attempt.get("method", "unavailable"),
        "model_id": attempt.get("model_id", "unavailable"),
        "model_settings": attempt.get("model_settings", "unavailable"),
        "cost": cost,
        "metadata_reason_codes": sorted(set(metadata_reasons)),
    }
    if attempt.get("status") == "not_delivered":
        return {
            **base,
            "status": "not_delivered",
            "reason_codes": ["not_delivered"],
            "missing_configurations": list(CONFIGS),
            "duplicate_configurations": [],
            "delivery": 0,
            "errors": None,
            "quality": {key: 0.0 for key in ERRORS},
        }
    if attempt.get("status") not in (None, "delivered"):
        reasons.append("invalid_status")
    if attempt.get("task_sha256") != public["task_sha256"]:
        reasons.append("task_digest_mismatch")
    if attempt.get("observation_sha256") != public["observation_sha256"]:
        reasons.append("observation_digest_mismatch")
    observed_ids = [row["config"] for row in public["observations"]]
    used = attempt.get("observations_used")
    if not isinstance(used, list) or any(not isinstance(item, str) for item in used):
        reasons.append("observation_use_missing")
    else:
        if len(used) > public["budget"]["max_observations_per_task"]:
            reasons.append("budget_overrun")
        if len(set(used)) != len(used):
            reasons.append("duplicate_observation")
        if set(used) - set(observed_ids):
            reasons.append("unapproved_observation")
        if set(used) != set(observed_ids):
            reasons.append("observation_set_mismatch")
    rows = attempt.get("responses")
    predicted = {}
    seen = set()
    duplicate = []
    unknown = []
    if not isinstance(rows, list):
        reasons.append("missing_response_table")
    else:
        if len(rows) > public["budget"]["required_response_rows"]:
            reasons.append("response_budget_overrun")
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"config", "value"}:
                reasons.append("invalid_response_row")
                continue
            config = row["config"]
            if not isinstance(config, str) or config not in CONFIGS:
                unknown.append(config)
                continue
            if config in seen:
                duplicate.append(config)
                continue
            seen.add(config)
            value = row["value"]
            if isinstance(value, dict) and "nonfinite_json_token" in value:
                reasons.append("nonfinite_prediction")
                continue
            if type(value) not in (int, float):
                reasons.append("invalid_prediction")
                continue
            if not math.isfinite(value):
                reasons.append("nonfinite_prediction")
                continue
            predicted[config] = value
        if duplicate:
            reasons.append("duplicate_configurations")
        if unknown:
            reasons.append("unknown_configurations")
        missing = sorted(set(CONFIGS) - set(predicted))
        if missing:
            reasons.append("missing_configurations")
    selected = attempt.get("selected_config")
    if selected not in CONFIGS:
        reasons.append("invalid_selection")
    reasons = sorted(set(reasons))
    if reasons:
        return {
            **base,
            "status": "not_delivered" if reasons == ["not_delivered"] else "invalid",
            "reason_codes": reasons,
            "missing_configurations": missing
            if isinstance(rows, list)
            else list(CONFIGS),
            "duplicate_configurations": sorted(set(duplicate)),
            "delivery": 0,
            "errors": None,
            "quality": {key: 0.0 for key in ERRORS},
        }
    errors = _errors(reference, predicted, selected)
    scales = public["metric"]
    quality = {
        "selection_regret": round(
            max(
                0.0, 1.0 - errors["selection_regret"] / scales["selection_regret_scale"]
            ),
            6,
        ),
        "conditional_effect_mae": round(
            max(
                0.0,
                1.0
                - errors["conditional_effect_mae"]
                / scales["conditional_effect_mae_scale"],
            ),
            6,
        ),
        "pair_interaction_mae": round(
            max(
                0.0,
                1.0
                - errors["pair_interaction_mae"] / scales["pair_interaction_mae_scale"],
            ),
            6,
        ),
    }
    return {
        **base,
        "status": "scored",
        "reason_codes": [],
        "missing_configurations": [],
        "duplicate_configurations": [],
        "delivery": 1,
        "errors": errors,
        "quality": quality,
    }


def _summary(rows):
    routes = sorted({row["route"] for row in rows})
    result = {}
    for route in routes:
        selected = [row for row in rows if row["route"] == route]
        delivered = [row for row in selected if row["delivery"] == 1]
        metrics = {}
        for key in ERRORS:
            metrics[key] = {
                "all_attempt_quality": round(
                    sum(row["quality"][key] for row in selected) / len(selected), 6
                ),
                "delivered_only_error": round(
                    sum(row["errors"][key] for row in delivered) / len(delivered), 6
                )
                if delivered
                else "unavailable",
                "delivered_only_quality": round(
                    sum(row["quality"][key] for row in delivered) / len(delivered), 6
                )
                if delivered
                else "unavailable",
            }
        result[route] = {
            "attempt_count": len(selected),
            "delivered_count": len(delivered),
            "undelivered_count": len(selected) - len(delivered),
            "delivery_rate_all_attempts": round(len(delivered) / len(selected), 6),
            "metrics": metrics,
        }
    result["all_routes"] = {
        "attempt_count": len(rows),
        "delivered_count": sum(row["delivery"] for row in rows),
        "undelivered_count": len(rows) - sum(row["delivery"] for row in rows),
        "delivery_rate_all_attempts": round(
            sum(row["delivery"] for row in rows) / len(rows), 6
        ),
    }
    return result


def score(state, attempts_raw: bytes):
    attempts = _parse(attempts_raw, allow_nonfinite=True)
    _validate(attempts, "attempt_file")
    public = {
        task["id"]: public_input(state, task["id"])
        for task in state["taskset"]["tasks"]
    }
    reference = {
        item["task_id"]: {row["config"]: row["value"] for row in item["rows"]}
        for item in state["reference"]["tasks"]
    }
    plan = attempts["plan"]
    planned = {}
    routes = {}
    for slot in plan:
        attempt_id, task_id, route = slot["attempt_id"], slot["task_id"], slot["route"]
        if (
            attempt_id in planned
            or task_id not in public
            or route not in {"baseline", "arw-route", "ridge", "oracle"}
        ):
            raise ExperimentEvalError("invalid_attempt_plan")
        if task_id in routes.setdefault(route, set()):
            raise ExperimentEvalError("duplicate_task_route_slot")
        routes[route].add(task_id)
        planned[attempt_id] = slot
    if any(tasks != set(public) for tasks in routes.values()):
        raise ExperimentEvalError("incomplete_attempt_plan")
    submitted = {}
    extras = []
    for index, attempt in enumerate(attempts["attempts"]):
        if not isinstance(attempt, dict):
            attempt = {"attempt_id": f"invalid-item-{index}", "route": "unknown"}
        attempt_id = attempt.get("attempt_id")
        if (
            isinstance(attempt_id, str)
            and attempt_id in planned
            and attempt_id not in submitted
        ):
            submitted[attempt_id] = attempt
        else:
            extras.append((index, attempt))
    rows = []
    for attempt_id, slot in planned.items():
        attempt = submitted.get(attempt_id)
        if attempt is None:
            rows.append(
                {
                    "attempt_id": attempt_id,
                    "task_id": slot["task_id"],
                    "route": slot["route"],
                    "task_sha256": public[slot["task_id"]]["task_sha256"],
                    "observation_sha256": public[slot["task_id"]]["observation_sha256"],
                    "declared_task_sha256": "unavailable",
                    "declared_observation_sha256": "unavailable",
                    "method": "unavailable",
                    "model_id": "unavailable",
                    "model_settings": "unavailable",
                    "cost": {
                        "tokens": "unavailable",
                        "usd": "unavailable",
                        "elapsed_ms": "unavailable",
                    },
                    "metadata_reason_codes": [],
                    "status": "not_delivered",
                    "reason_codes": ["missing_attempt"],
                    "missing_configurations": list(CONFIGS),
                    "duplicate_configurations": [],
                    "delivery": 0,
                    "errors": None,
                    "quality": {key: 0.0 for key in ERRORS},
                }
            )
        elif (
            attempt.get("task_id") != slot["task_id"]
            or attempt.get("route") != slot["route"]
        ):
            invalid = _score_one(
                attempt, public[slot["task_id"]], reference[slot["task_id"]]
            )
            invalid.update(
                status="invalid",
                reason_codes=sorted(
                    set(invalid["reason_codes"] + ["attempt_slot_mismatch"])
                ),
                delivery=0,
                errors=None,
                quality={key: 0.0 for key in ERRORS},
                task_id=slot["task_id"],
                route=slot["route"],
            )
            rows.append(invalid)
        else:
            rows.append(
                _score_one(attempt, public[slot["task_id"]], reference[slot["task_id"]])
            )
    for index, attempt in extras:
        attempt_id = attempt.get("attempt_id")
        rows.append(
            {
                "attempt_id": attempt_id
                if isinstance(attempt_id, str)
                else f"invalid-item-{index}",
                "task_id": attempt.get("task_id", "unknown"),
                "route": attempt.get("route")
                if isinstance(attempt.get("route"), str)
                else "unknown",
                "task_sha256": "unavailable",
                "observation_sha256": "unavailable",
                "declared_task_sha256": attempt.get("task_sha256", "unavailable"),
                "declared_observation_sha256": attempt.get(
                    "observation_sha256", "unavailable"
                ),
                "method": attempt.get("method", "unavailable"),
                "model_id": attempt.get("model_id", "unavailable"),
                "model_settings": attempt.get("model_settings", "unavailable"),
                "cost": _cost(attempt)[0],
                "metadata_reason_codes": _cost(attempt)[1],
                "status": "invalid",
                "reason_codes": [
                    "duplicate_attempt_id"
                    if isinstance(attempt_id, str) and attempt_id in planned
                    else "unplanned_attempt"
                ],
                "missing_configurations": list(CONFIGS),
                "duplicate_configurations": [],
                "delivery": 0,
                "errors": None,
                "quality": {key: 0.0 for key in ERRORS},
            }
        )
    body = {
        "schema_version": "arw.cpu-four-factor-receipt.v1",
        "evaluator_version": "1",
        "taskset_sha256": state["taskset_sha256"],
        "reference_sha256": state["reference_sha256"],
        "observations_sha256": state["observations_sha256"],
        "attempts_sha256": sha(attempts_raw),
        "attempts": rows,
        "summary": _summary(rows),
        "live_comparison": {"status": "not_measured"},
    }
    receipt = {**body, "receipt_sha256": sha(canonical(body))}
    _validate(receipt, "receipt")
    return canonical(receipt)


def verify_receipt(receipt_raw: bytes, state, attempts_raw: bytes) -> bool:
    try:
        receipt = _parse(receipt_raw)
        _validate(receipt, "receipt")
        claimed = receipt["receipt_sha256"]
        body = dict(receipt)
        del body["receipt_sha256"]
        if sha(canonical(body)) != claimed or score(state, attempts_raw) != receipt_raw:
            raise ExperimentEvalError("receipt_replay_mismatch")
    except (ExperimentEvalError, jsonschema.ValidationError) as error:
        raise ExperimentEvalError("receipt_replay_mismatch") from error
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Original offline four-factor CPU evaluation"
    )
    parser.add_argument("--taskset", type=Path, default=FIXTURE / "taskset.json")
    parser.add_argument(
        "--observations", type=Path, default=FIXTURE / "observations.json"
    )
    parser.add_argument("--manifest", type=Path, default=FIXTURE / "manifest.json")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser(
        "prepare", help="Emit only public task and eight approved observations"
    )
    prepare.add_argument("--task-id", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    ridge = sub.add_parser(
        "ridge", help="Emit pair-effect ridge attempts from frozen observations"
    )
    ridge.add_argument("--output", type=Path, required=True)
    score_cmd = sub.add_parser(
        "score", help="Score predeclared attempts against hidden reference"
    )
    score_cmd.add_argument(
        "--reference", type=Path, default=FIXTURE / "hidden-reference.json"
    )
    score_cmd.add_argument("--attempts", type=Path, required=True)
    score_cmd.add_argument("--receipt", type=Path, required=True)
    verify = sub.add_parser("verify", help="Recompute one receipt from retained inputs")
    verify.add_argument(
        "--reference", type=Path, default=FIXTURE / "hidden-reference.json"
    )
    verify.add_argument("--attempts", type=Path, required=True)
    verify.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            state = load_public(args.taskset, args.observations, args.manifest)
            output = canonical(public_input(state, args.task_id))
            inputs = (args.taskset, args.observations, args.manifest)
            target = args.output
        elif args.command == "ridge":
            state = load_public(args.taskset, args.observations, args.manifest)
            output = canonical(ridge_attempts(state))
            inputs = (args.taskset, args.observations, args.manifest)
            target = args.output
        else:
            state = load_fixtures(
                args.taskset, args.observations, args.reference, args.manifest
            )
            attempts_raw = read_local(args.attempts)
            inputs = (
                args.taskset,
                args.observations,
                args.reference,
                args.manifest,
                args.attempts,
            )
            if args.command == "verify":
                verify_receipt(read_local(args.receipt), state, attempts_raw)
                return 0
            output = score(state, attempts_raw)
            target = args.receipt
        if any(target.resolve() == path.resolve() for path in inputs):
            raise ExperimentEvalError("output_overlaps_input")
        _install_outputs([(target, output)])
    except (
        ExperimentEvalError,
        OSError,
        jsonschema.ValidationError,
        ValueError,
    ) as error:
        code = (
            error.code
            if isinstance(error, ExperimentEvalError)
            else "evaluation_failed"
        )
        print(
            json.dumps(
                {"error": {"code": code, "message": str(error)}}, ensure_ascii=False
            ),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
