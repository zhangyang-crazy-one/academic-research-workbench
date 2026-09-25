"""Bounded, deterministic comparison of already retained local research results."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import sys
import tempfile

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/v1/eval-run.schema.json"
MAX_BYTES = 1_048_576
CHECKERS = {"citation", "quote_locator", "gate", "route", "leakage"}
GATE_OUTCOMES = ("pass", "block", "human_review")
BENCHMARK_RATE_METRICS = frozenset(
    {
        "citation_precision",
        "citation_recall",
        "citation_status_accuracy",
        "quote_locator_digest_accuracy",
        "route_accuracy",
    }
)
ANSWER_KEYS = {
    "citation": {"citations"},
    "quote_locator": {"locator", "quote", "quote_sha256"},
    "gate": {"gate"},
    "route": {"route"},
    "leakage": {"text"},
}


class EvaluationError(ValueError):
    """Invalid or incomplete local evaluation evidence."""


def canonical(value):
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise EvaluationError(f"duplicate_key:{key}")
        result[key] = value
    return result


def _reject_constant(value):
    raise EvaluationError(f"nonfinite_number:{value}")


def _finite_float(value):
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise EvaluationError(f"invalid_float:{value}") from exc
    if not math.isfinite(number):
        raise EvaluationError("nonfinite_number")
    return number


def _parse_json(data):
    try:
        return json.loads(
            data,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"invalid_json:{exc}") from exc


def read_local(path):
    path = Path(path)
    if "://" in str(path):
        raise EvaluationError("non_local_path")
    if not hasattr(os, "O_NOFOLLOW"):
        raise EvaluationError("nofollow_unavailable")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as exc:
        raise EvaluationError(f"input_unavailable:{path}") from exc
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
            raise EvaluationError("invalid_file_type_or_size")
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, min(65536, MAX_BYTES + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > MAX_BYTES:
                raise EvaluationError("input_size_exceeded")
        after = os.fstat(fd)
        at_path = path.stat(follow_symlinks=False)
        def _ident(item):
            return (item.st_dev, item.st_ino, item.st_size)
        if (
            not stat.S_ISREG(at_path.st_mode)
            or _ident(before) != _ident(after)
            or _ident(after) != _ident(at_path)
            or total != after.st_size
        ):
            raise EvaluationError("input_changed_during_read")
        return b"".join(chunks)
    except OSError as exc:
        raise EvaluationError(f"input_unavailable:{path}") from exc
    finally:
        os.close(fd)


def load_json(path):
    try:
        return _parse_json(read_local(path))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError("invalid_json") from exc


def _schema():
    try:
        return json.loads(SCHEMA.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"invalid_eval_schema:{exc}") from exc


def _validate(instance, definition):
    schema = _schema()
    validator = jsonschema.Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]}
    )
    errors = list(validator.iter_errors(instance))
    if errors:
        raise EvaluationError(
            f"invalid_{definition}:{errors[0].json_path}:{errors[0].message}"
        )


def validate_corpus(corpus):
    _validate(corpus, "corpus")
    ids = [case["id"] for case in corpus["cases"]]
    if len(ids) != len(set(ids)):
        raise EvaluationError("duplicate_case_id")
    if {case["language"] for case in corpus["cases"]} != {"en", "zh"}:
        raise EvaluationError("bilingual_coverage_missing")
    if sum(case["adversarial"] for case in corpus["cases"]) < 10:
        raise EvaluationError("adversarial_coverage_missing")
    if {case["checker"] for case in corpus["cases"]} != CHECKERS:
        raise EvaluationError("checker_coverage_missing")
    for case in corpus["cases"]:
        checker = case["checker"]
        if checker not in CHECKERS or set(case["expected"]) != ANSWER_KEYS[checker]:
            raise EvaluationError(f"invalid_expected:{case['id']}")
        if checker == "leakage" and (
            "sentinel" not in case or case["sentinel"] in case["expected"]["text"]
        ):
            raise EvaluationError(f"invalid_sentinel:{case['id']}")
        if checker != "leakage" and "sentinel" in case:
            raise EvaluationError(f"unexpected_sentinel:{case['id']}")
        if checker == "citation":
            citation_ids = [item["id"] for item in case["expected"]["citations"]]
            if len(citation_ids) != len(set(citation_ids)):
                raise EvaluationError(f"duplicate_expected_citation:{case['id']}")
        if (
            checker == "quote_locator"
            and hashlib.sha256(case["expected"]["quote"].encode()).hexdigest()
            != case["expected"]["quote_sha256"]
        ):
            raise EvaluationError(f"invalid_reference_digest:{case['id']}")
    if not any(
        case["checker"] == "citation" and case["expected"]["citations"]
        for case in corpus["cases"]
    ):
        raise EvaluationError("citation_reference_coverage_missing")


def _bundle(bundle, route, corpus):
    _validate(bundle, "bundle")
    if bundle["route"] != route or bundle["corpus_version"] != corpus["version"]:
        raise EvaluationError("route_or_corpus_mismatch")
    case_map = {case["id"]: case for case in corpus["cases"]}
    results = {}
    for result in bundle["results"]:
        task_id = result["task_id"]
        if task_id in results:
            raise EvaluationError(f"duplicate_result:{task_id}")
        if task_id not in case_map:
            raise EvaluationError(f"unknown_result:{task_id}")
        if set(result["answer"]) != ANSWER_KEYS[case_map[task_id]["checker"]]:
            raise EvaluationError(f"checker_contract_mismatch:{task_id}")
        citations = result["answer"].get("citations", [])
        if len({citation["id"] for citation in citations}) != len(citations):
            raise EvaluationError(f"duplicate_citation:{task_id}")
        results[task_id] = result["answer"]
    if set(results) != set(case_map):
        raise EvaluationError("missing_result")
    return results


def _score(case, answer):
    expected = case["expected"]
    checker = case["checker"]
    if checker == "citation":
        wanted = {item["id"]: item["status"] for item in expected["citations"]}
        actual = {item["id"]: item["status"] for item in answer["citations"]}
        common = wanted.keys() & actual.keys()
        return {
            "correct_ids": len(common),
            "expected_ids": len(wanted),
            "actual_ids": len(actual),
            "correct_status": sum(wanted[key] == actual[key] for key in common),
        }
    if checker == "quote_locator":
        actual_digest = hashlib.sha256(answer["quote"].encode()).hexdigest()
        return {
            "exact_locator_quote_digest_match": answer["locator"] == expected["locator"]
            and actual_digest == answer["quote_sha256"] == expected["quote_sha256"]
        }
    if checker == "gate":
        return {
            "expected_gate": expected["gate"],
            "actual_gate": answer["gate"],
        }
    if checker == "route":
        return {"exact_route_match": expected["route"] == answer["route"]}
    return {"sentinel_hit": case["sentinel"] in answer["text"]}


def _summary(rows, route):
    scores = [(row["checker"], row[route]) for row in rows]
    citations = [value for kind, value in scores if kind == "citation"]
    correct = sum(value["correct_ids"] for value in citations)
    expected = sum(value["expected_ids"] for value in citations)
    actual = sum(value["actual_ids"] for value in citations)
    gates = [value for kind, value in scores if kind == "gate"]
    gate_confusion = {
        f"gate_{expected_gate}_as_{actual_gate}": sum(
            value["expected_gate"] == expected_gate
            and value["actual_gate"] == actual_gate
            for value in gates
        )
        for expected_gate in GATE_OUTCOMES
        for actual_gate in GATE_OUTCOMES
    }
    quotes = [value for kind, value in scores if kind == "quote_locator"]
    routes = [value for kind, value in scores if kind == "route"]
    leaks = [value for kind, value in scores if kind == "leakage"]

    def ratio(numerator, denominator):
        if denominator <= 0:
            raise EvaluationError("metric_denominator_zero")
        return numerator / denominator

    return {
        "citation_precision": ratio(correct, actual) if actual else 0.0,
        "citation_recall": ratio(correct, expected),
        "citation_status_accuracy": ratio(
            sum(v["correct_status"] for v in citations), expected
        ),
        "quote_locator_digest_accuracy": ratio(
            sum(v["exact_locator_quote_digest_match"] for v in quotes), len(quotes)
        ),
        "gate_tp": sum(
            v["expected_gate"] == "block" and v["actual_gate"] == "block" for v in gates
        ),
        "gate_fp": sum(
            v["expected_gate"] != "block" and v["actual_gate"] == "block" for v in gates
        ),
        "gate_tn": sum(
            v["expected_gate"] != "block" and v["actual_gate"] != "block" for v in gates
        ),
        "gate_fn": sum(
            v["expected_gate"] == "block" and v["actual_gate"] != "block" for v in gates
        ),
        **gate_confusion,
        "route_accuracy": ratio(
            sum(v["exact_route_match"] for v in routes), len(routes)
        ),
        "leakage_hits": sum(v["sentinel_hit"] for v in leaks),
        "leakage_cases": len(leaks),
    }


def compare(corpus_path, baseline_path, route_path):
    paths = [Path(p) for p in (corpus_path, baseline_path, route_path)]
    if len({path.resolve() for path in paths}) != 3:
        raise EvaluationError("input_paths_overlap")
    corpus_bytes, baseline_bytes, route_bytes = (read_local(path) for path in paths)
    corpus, baseline, route = (
        _parse_json(raw) for raw in (corpus_bytes, baseline_bytes, route_bytes)
    )
    validate_corpus(corpus)
    inputs = {"baseline": baseline, "arw-route": route}
    answers = {name: _bundle(bundle, name, corpus) for name, bundle in inputs.items()}
    if any(
        bundle.get("model_id", "").strip().lower() == "unavailable"
        for bundle in inputs.values()
    ):
        raise EvaluationError("invalid_recorded_model_id")
    baseline_model = baseline.get("model_id")
    route_model = route.get("model_id")
    if (
        baseline_model is not None
        and route_model is not None
        and baseline_model != route_model
    ):
        raise EvaluationError("model_id_mismatch")
    pairing = (
        "matched"
        if baseline_model is not None and route_model is not None
        else "unavailable"
    )
    rows = []
    for case in sorted(corpus["cases"], key=lambda item: item["id"]):
        row = {"task_id": case["id"], "checker": case["checker"]}
        for name in inputs:
            row[name] = _score(case, answers[name][case["id"]])
        row["sha256"] = digest(row)
        rows.append(row)
    summary = {name: _summary(rows, name) for name in inputs}
    summary["delta"] = {
        key: summary["arw-route"][key] - summary["baseline"][key]
        for key in summary["baseline"]
    }
    receipt = {
        "schema_version": "arw.eval-run.v1",
        "evaluator_version": "2",
        "pairing": pairing,
        "corpus_version": corpus["version"],
        "corpus_sha256": hashlib.sha256(corpus_bytes).hexdigest(),
        "input_sha256": {
            "baseline": hashlib.sha256(baseline_bytes).hexdigest(),
            "arw-route": hashlib.sha256(route_bytes).hexdigest(),
        },
        "cases": rows,
        "cases_sha256": digest(rows),
        "summary": summary,
        "summary_sha256": digest(summary),
        "cost": {
            name: {
                key: inputs[name].get("cost", {}).get(key, "unavailable")
                for key in ("tokens", "usd", "elapsed_ms")
            }
            for name in inputs
        },
        "model_id": {
            name: inputs[name].get("model_id", "unavailable") for name in inputs
        },
        "build_identity_sha256": {
            name: inputs[name].get("build_identity_sha256", "unavailable")
            for name in inputs
        },
    }
    receipt["receipt_sha256"] = digest(receipt)
    jsonschema.Draft202012Validator(_schema()).validate(receipt)
    return canonical(receipt)


def verify_receipt(receipt_bytes, corpus_path, baseline_path, route_path):
    """Verify canonical bytes, all bindings, scores, and input contents by replay."""
    try:
        recorded = _parse_json(receipt_bytes)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError("invalid_receipt_json") from exc
    jsonschema.Draft202012Validator(_schema()).validate(recorded)
    if canonical(recorded) != receipt_bytes:
        raise EvaluationError("noncanonical_receipt")
    if recorded["receipt_sha256"] != digest(
        {key: value for key, value in recorded.items() if key != "receipt_sha256"}
    ):
        raise EvaluationError("receipt_digest_mismatch")
    if compare(corpus_path, baseline_path, route_path) != receipt_bytes:
        raise EvaluationError("receipt_or_input_mismatch")
    return True


def candidate_sample(
    receipt_bytes,
    baseline_path,
    route_path,
    context_path,
    corpus_path=ROOT / "evals/corpus/v1.json",
):
    """Produce an unadmitted, per-run benchmark candidate only with recorded identity."""
    verify_receipt(receipt_bytes, corpus_path, baseline_path, route_path)
    receipt = _parse_json(receipt_bytes)
    baseline, route, context = (
        load_json(path) for path in (baseline_path, route_path, context_path)
    )
    for name, path in (("baseline", baseline_path), ("arw-route", route_path)):
        if (
            receipt["input_sha256"][name]
            != hashlib.sha256(read_local(path)).hexdigest()
        ):
            raise EvaluationError("candidate_input_digest_mismatch")
    _validate(context, "candidate_context")
    policy = context["policy"]
    try:
        learning_policy = json.loads(
            (ROOT / "schemas/v1/research-learning-policy.schema.json").read_bytes()
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"invalid_policy_schema:{exc}") from exc
    jsonschema.Draft202012Validator(learning_policy).validate(policy)
    run_id = baseline.get("run_id")
    metric = policy["metric"]
    if (
        not run_id
        or route.get("run_id") != run_id
        or run_id not in policy["run_subset"]
        or policy["mode"] != "benchmark"
        or metric not in receipt["summary"]["baseline"]
    ):
        raise EvaluationError("candidate_identity_or_metric_mismatch")
    if metric not in BENCHMARK_RATE_METRICS:
        raise EvaluationError("candidate_metric_requires_bounded_rate")
    sample = {
        "schema_version": "arw.learning-sample.v1",
        "heuristic_id": context["heuristic_id"],
        "policy_id": policy["policy_id"],
        "policy_version": policy["version"],
        "run_id": run_id,
        "mode": "benchmark",
        "metric": metric,
        "baseline": receipt["summary"]["baseline"][metric],
        "outcome": receipt["summary"]["arw-route"][metric],
        "proposed_action": context["proposed_action"],
        "actual_action": context["actual_action"],
    }
    try:
        sample_schema = json.loads(
            (ROOT / "schemas/v1/research-learning-sample.schema.json").read_bytes()
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"invalid_sample_schema:{exc}") from exc
    jsonschema.Draft202012Validator(sample_schema).validate(sample)
    return canonical(sample)


def _install_outputs(outputs):
    """Stage all bytes, then install exclusive links; roll back owned links on error."""
    staged = []
    installed = []
    try:
        for target, content in outputs:
            fd, name = tempfile.mkstemp(prefix=".arw-eval-", dir=target.parent)
            stage = Path(name)
            staged.append(stage)
            with os.fdopen(fd, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
        for (target, _content), stage in zip(outputs, staged, strict=True):
            identity = os.stat(stage, follow_symlinks=False)
            os.link(stage, target)
            installed.append((target, identity.st_dev, identity.st_ino))
        for stage in staged:
            stage.unlink()
    except BaseException as failure:
        rollback_errors = []
        for target, device, inode in reversed(installed):
            try:
                current = target.stat(follow_symlinks=False)
            except FileNotFoundError:
                continue
            except OSError as exc:
                rollback_errors.append(f"output_rollback_stat_failed:{target}:{exc}")
                continue
            if (current.st_dev, current.st_ino) != (device, inode):
                rollback_errors.append(f"output_rollback_ownership_lost:{target}")
                continue
            try:
                target.unlink()
            except OSError as exc:
                rollback_errors.append(f"output_rollback_unlink_failed:{target}:{exc}")
        for stage in staged:
            try:
                stage.unlink(missing_ok=True)
            except OSError as exc:
                rollback_errors.append(f"output_stage_cleanup_failed:{stage}:{exc}")
        if rollback_errors:
            raise EvaluationError(";".join(rollback_errors)) from failure
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Compare retained local results; no models or network"
    )
    parser.add_argument("--corpus", default=str(ROOT / "evals/corpus/v1.json"))
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--arw-route", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--candidate-context")
    parser.add_argument("--candidate-out")
    args = parser.parse_args(argv)
    if bool(args.candidate_context) != bool(args.candidate_out):
        parser.error("candidate context and output must be supplied together")
    try:
        receipt = compare(args.corpus, args.baseline, args.arw_route)
        candidate = (
            candidate_sample(
                receipt,
                args.baseline,
                args.arw_route,
                args.candidate_context,
                args.corpus,
            )
            if args.candidate_context
            else None
        )
        inputs = {
            Path(p).resolve()
            for p in (
                args.corpus,
                args.baseline,
                args.arw_route,
                args.candidate_context,
            )
            if p
        }
        outputs = [Path(args.receipt)] + (
            [Path(args.candidate_out)] if candidate else []
        )
        if any(path.resolve() in inputs for path in outputs) or len(
            {path.resolve() for path in outputs}
        ) != len(outputs):
            raise EvaluationError("output_overlaps_input")
        pairs = [
            (path, content)
            for path, content in zip(outputs, (receipt, candidate), strict=False)
            if content is not None
        ]
        _install_outputs(pairs)
    except (
        EvaluationError,
        OSError,
        jsonschema.ValidationError,
        json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
