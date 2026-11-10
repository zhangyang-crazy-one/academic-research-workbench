"""Bounded Linux/std-library candidate pilot; never a model-host sandbox claim."""

from __future__ import annotations

import argparse
import copy
import math
import resource
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from evals.experiment_understanding import offline as evaluator
from evals.offline import read_local

ROOT = Path(__file__).resolve().parents[2]
IDENTITY_FILES = (
    "evals/experiment_understanding/independent.py",
    "evals/experiment_understanding/offline.py",
    "evals/experiment_understanding/v1_fixture.py",
    "evals/experiment_understanding/v1.schema.json",
    "evals/offline.py",
)
LIMIT = 262_144


def identity():
    return {name: evaluator.sha(read_local(ROOT / name)) for name in IDENTITY_FILES}


def public_inputs():
    state = evaluator.load_public()
    return [
        evaluator.public_input(state, task["id"]) for task in state["taskset"]["tasks"]
    ]


def freeze(method: Path):
    """No hidden reference is opened in this phase."""
    raw = read_local(method)
    return {
        "protocol": "arw.independent-cpu-pilot.v1",
        "method_sha256": evaluator.sha(raw),
        "public_sha256": [
            evaluator.sha(evaluator.canonical(p)) for p in public_inputs()
        ],
        "scorer_identity": identity(),
        "fixture_manifest_sha256": evaluator.sha(
            read_local(evaluator.FIXTURE / "manifest.json")
        ),
        "controls": ["oracle", "zero_table", "missing"],
        "isolation": "linux-bubblewrap-required",
        "limits": {
            "wall_seconds": 10,
            "cpu_seconds": 5,
            "output_bytes": LIMIT,
            "prediction_absolute_max": 1e100,
        },
    }


def check_freeze(raw: bytes, expected_sha256: str, method: Path):
    if evaluator.sha(raw) != expected_sha256 or evaluator._parse(raw) != freeze(method):
        raise evaluator.ExperimentEvalError("freeze_binding_mismatch")


def _limits():
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_FSIZE, (LIMIT, LIMIT))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))


def runtime_mounts():
    return [Path(path) for path in ("/usr", "/lib", "/lib64") if Path(path).exists()]


def check_runtime_boundary():
    """Never expose this checkout or known answer files through runtime mounts."""
    protected = [ROOT, evaluator.FIXTURE, evaluator.FIXTURE / "hidden-reference.json"]
    for path in protected:
        resolved = path.resolve()
        if any(resolved.is_relative_to(mount.resolve()) for mount in runtime_mounts()):
            raise evaluator.ExperimentEvalError(
                "runtime_mount_contains_protected_input"
            )


def execute(method_raw: bytes, public_raw: bytes):
    """Fresh mount/pid/network namespace per attempt; no host cwd or env mounts."""
    check_runtime_boundary()
    bwrap = shutil.which("bwrap")
    if not bwrap:
        return {
            "status": "isolation_unavailable",
            "stdout": b"",
            "stderr": b"bubblewrap missing",
            "elapsed_ms": 0,
        }
    start = time.monotonic_ns()
    with tempfile.TemporaryDirectory(prefix="arw-public-") as directory:
        root = Path(directory)
        (root / "method.py").write_bytes(method_raw)
        (root / "input.json").write_bytes(public_raw)
        command = [
            bwrap,
            "--unshare-all",
            "--die-with-parent",
            "--new-session",
            "--clearenv",
        ]
        for path in runtime_mounts():
            command += ["--ro-bind", str(path), str(path)]
        command += [
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--tmpfs",
            "/work",
            "--ro-bind",
            str(root),
            "/input",
            "--chdir",
            "/work",
            "--setenv",
            "HOME",
            "/work",
            "--setenv",
            "PATH",
            "/usr/bin",
            "--setenv",
            "LANG",
            "C.UTF-8",
            "--",
            "/usr/bin/python3",
            "-I",
            "-S",
            "/input/method.py",
            "/input/input.json",
        ]
        # Logs are host-only, never mounted in a subsequent attempt. File-size
        # limits bound both channels; communicate() cannot accumulate unbounded output.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                completed = subprocess.run(
                    command,
                    stdin=subprocess.DEVNULL,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=10,
                    check=False,
                    preexec_fn=_limits,
                    close_fds=True,
                    cwd="/",
                    env={"PATH": "/usr/bin:/bin"},
                )
                status = (
                    "completed" if completed.returncode == 0 else "execution_failed"
                )
            except subprocess.TimeoutExpired:
                status = "timed_out"
            except OSError:
                status = "isolation_unavailable"
            stdout.seek(0)
            stderr.seek(0)
            out, err = stdout.read(LIMIT), stderr.read(LIMIT)
    return {
        "status": status,
        "stdout": out,
        "stderr": err,
        "elapsed_ms": (time.monotonic_ns() - start) // 1_000_000,
    }


def control_check(state):
    """Mandatory noncandidate controls; success is a numerical check, not PASS text."""
    oracle = evaluator.ridge_attempts(state)
    for attempt, reference in zip(oracle["attempts"], state["reference"]["tasks"]):
        attempt["responses"] = copy.deepcopy(reference["rows"])
        attempt["selected_config"] = max(
            reference["rows"], key=lambda row: row["value"]
        )["config"]
    zero = copy.deepcopy(oracle)
    for attempt in zero["attempts"]:
        for row in attempt["responses"]:
            row["value"] = 0
    missing = {**oracle, "attempts": []}
    results = {}
    for name, bundle in (
        ("oracle", oracle),
        ("zero_table", zero),
        ("missing", missing),
    ):
        results[name] = evaluator._parse(
            evaluator.score(state, evaluator.canonical(bundle))
        )
    try:
        valid = (
            all(
                row["delivery"] == 1
                and all(row["errors"][key] == 0 for key in evaluator.ERRORS)
                for row in results["oracle"]["attempts"]
            )
            and all(
                row["delivery"] == 1
                and row["errors"]["conditional_effect_mae"] > 0
                and row["errors"]["pair_interaction_mae"] > 0
                for row in results["zero_table"]["attempts"]
            )
            and all(
                row["delivery"] == 0 and row["errors"] is None
                for row in results["missing"]["attempts"]
            )
            and all(len(result["attempts"]) == 3 for result in results.values())
        )
        if not valid:
            raise ValueError("control result mismatch")
    except (ValueError, KeyError, TypeError) as error:
        raise evaluator.ExperimentEvalError("scorer_controls_failed") from error
    return results


def candidate_predictions(raw: bytes):
    """Admit only a flat, bounded numeric table to the host scorer.

    A byte cap alone does not bound JSON recursion or Python integer magnitude.
    The magnitude cap also keeps downstream difference/sum arithmetic finite.
    Reject the entire slot rather than repairing a hostile partial response.
    """
    value = evaluator._parse(raw)
    if not isinstance(value, dict) or set(value) != {"selected_config", "responses"}:
        raise ValueError("invalid candidate shape")
    if (
        not isinstance(value["selected_config"], str)
        or value["selected_config"] not in evaluator.CONFIGS
    ):
        raise ValueError("invalid candidate selection")
    rows = value["responses"]
    if not isinstance(rows, list) or len(rows) != len(evaluator.CONFIGS):
        raise ValueError("invalid candidate table")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"config", "value"}:
            raise ValueError("invalid candidate row")
        config, number = row["config"], row["value"]
        if (
            not isinstance(config, str)
            or config not in evaluator.CONFIGS
            or config in seen
        ):
            raise ValueError("invalid candidate configuration")
        seen.add(config)
        if type(number) not in (int, float) or abs(number) > 1e100:
            raise ValueError("candidate prediction outside numeric bound")
        if type(number) is float and not math.isfinite(number):
            raise ValueError("nonfinite candidate prediction")
    return value


def run(method: Path, freeze_path: Path, expected_sha256: str, output: Path):
    check_runtime_boundary()
    frozen = read_local(freeze_path)
    check_freeze(frozen, expected_sha256, method)
    method_raw = read_local(method)
    # Bind the exact staged bytes too, not just a previous pathname read.
    if evaluator.sha(method_raw) != evaluator._parse(frozen)["method_sha256"]:
        raise evaluator.ExperimentEvalError("freeze_binding_mismatch")
    inputs = public_inputs()
    if [evaluator.sha(evaluator.canonical(p)) for p in inputs] != evaluator._parse(
        frozen
    )["public_sha256"]:
        raise evaluator.ExperimentEvalError("freeze_binding_mismatch")
    output.mkdir(parents=False, exist_ok=False)
    (output / "freeze.json").write_bytes(frozen)
    (output / "method.py").write_bytes(method_raw)
    plan = [
        {
            "attempt_id": f"pilot.{p['task_id']}",
            "task_id": p["task_id"],
            "route": "arw-route",
        }
        for p in inputs
    ]
    attempts, executions = [], []

    def save_attempts():
        raw = evaluator.canonical(
            {
                "schema_version": "arw.cpu-four-factor-attempts.v1",
                "plan": plan,
                "attempts": attempts,
            }
        )
        (output / "attempts.json").write_bytes(raw)
        return raw

    save_attempts()
    for public, slot in zip(inputs, plan):
        task_id = public["task_id"]
        executions.append({**slot, "status": "started", "elapsed_ms": "unavailable"})
        (output / "executions.json").write_bytes(evaluator.canonical(executions))
        raw = evaluator.canonical(public)
        (output / f"{task_id}.input.json").write_bytes(raw)
        execution = execute(method_raw, raw)
        for channel in ("stdout", "stderr"):
            (output / f"{task_id}.{channel}").write_bytes(execution[channel])
        executions[-1] = {
            **slot,
            "status": execution["status"],
            "elapsed_ms": execution["elapsed_ms"],
            "stdout_sha256": evaluator.sha(execution["stdout"]),
            "stderr_sha256": evaluator.sha(execution["stderr"]),
        }
        attempt = {**slot, "cost": {"elapsed_ms": execution["elapsed_ms"]}}
        if execution["status"] == "completed":
            try:
                # Validate before admitting candidate data into scorer/serialization.
                attempt.update(candidate_predictions(execution["stdout"]))
            except (ValueError, RecursionError, OverflowError):
                executions[-1]["status"] = "invalid_output"
        attempt.update(
            method="frozen-python-pilot",
            task_sha256=public["task_sha256"],
            observation_sha256=public["observation_sha256"],
            observations_used=[row["config"] for row in public["observations"]],
        )
        attempts.append(attempt)
        # Persist inventory after each attempt, including failure and cost.
        (output / "executions.json").write_bytes(evaluator.canonical(executions))
        save_attempts()
    bundle = save_attempts()
    # No hidden table is opened until all bounded attempts have ended and sealed bytes exist.
    check_freeze(frozen, expected_sha256, method)
    state = evaluator.load_fixtures()
    controls = control_check(state)
    (output / "controls.json").write_bytes(evaluator.canonical(controls))
    receipt = evaluator.score(state, bundle)
    evaluator.verify_receipt(receipt, state, bundle)
    check_freeze(frozen, expected_sha256, method)
    (output / "receipt.json").write_bytes(receipt)
    report = {
        "protocol": "arw.independent-cpu-pilot.v1",
        "freeze_sha256": expected_sha256,
        "isolation": "enforced_for_completed_processes_only",
        "status": "completed"
        if all(e["status"] == "completed" for e in executions)
        and evaluator._parse(receipt)["summary"]["all_routes"]["delivered_count"] == 3
        else "incomplete",
        "executions": executions,
        "controls_sha256": evaluator.sha(evaluator.canonical(controls)),
        "attempts_sha256": evaluator.sha(bundle),
        "receipt_sha256": evaluator.sha(receipt),
        "claims": {"arbitrary_model_isolation": False, "scientific_quality": False},
    }
    (output / "report.json").write_bytes(evaluator.canonical(report))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("freeze", "run"):
        command = commands.add_parser(name)
        command.add_argument("--method", required=True, type=Path)
        command.add_argument("--output", required=True, type=Path)
        if name == "run":
            command.add_argument("--freeze", required=True, type=Path)
            command.add_argument("--freeze-sha256", required=True)
    args = parser.parse_args(argv)
    if args.command == "freeze":
        raw = evaluator.canonical(freeze(args.method))
        with args.output.open("xb") as stream:
            stream.write(raw)
        print(evaluator.sha(raw))
        return 0
    report = run(args.method, args.freeze, args.freeze_sha256, args.output)
    print(evaluator.canonical(report).decode(), end="")
    return 0 if report["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
