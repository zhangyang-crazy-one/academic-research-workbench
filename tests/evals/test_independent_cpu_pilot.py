import json
import os
from pathlib import Path

import pytest

from evals.experiment_understanding import independent as pilot
from evals.experiment_understanding import offline as evaluator


@pytest.fixture
def frozen(tmp_path):
    method = tmp_path / "candidate.py"
    method.write_text("print('{}')\n")
    raw = evaluator.canonical(pilot.freeze(method))
    freeze_path = tmp_path / "freeze.json"
    freeze_path.write_bytes(raw)
    return method, freeze_path, evaluator.sha(raw), tmp_path / "run"


def fake_execute(method, public):
    return {"status": "completed", "stdout": b"{}", "stderr": b"log", "elapsed_ms": 2}


def test_freeze_does_not_open_answers(monkeypatch, frozen):
    monkeypatch.setattr(
        evaluator, "load_fixtures", lambda: pytest.fail("opened answers")
    )
    method, path, digest, _ = frozen
    pilot.check_freeze(path.read_bytes(), digest, method)


@pytest.mark.parametrize(
    "field,value",
    [
        ("controls", []),
        ("scorer_identity", {}),
        ("public_sha256", []),
        ("isolation", "cooperative"),
    ],
)
def test_modified_freeze_rejected(frozen, field, value):
    method, path, digest, _ = frozen
    body = json.loads(path.read_bytes())
    body[field] = value
    raw = evaluator.canonical(body)
    with pytest.raises(ValueError, match="freeze_binding_mismatch"):
        pilot.check_freeze(raw, digest, method)
    with pytest.raises(ValueError, match="freeze_binding_mismatch"):
        pilot.check_freeze(raw, evaluator.sha(raw), method)


def test_method_tamper_rejected_before_execution(frozen):
    method, path, digest, _ = frozen
    method.write_text("print('PASS')")
    with pytest.raises(ValueError, match="freeze_binding_mismatch"):
        pilot.check_freeze(path.read_bytes(), digest, method)


def test_controls_and_constant_pass(monkeypatch):
    state = evaluator.load_fixtures()
    results = pilot.control_check(state)
    assert set(results) == {"oracle", "zero_table", "missing"}
    monkeypatch.setattr(
        evaluator, "score", lambda *_: evaluator.canonical(results["oracle"])
    )
    with pytest.raises(ValueError, match="scorer_controls_failed"):
        pilot.control_check(state)


def test_candidate_cannot_select_scorer_or_override_cost(frozen, monkeypatch):
    method, path, digest, output = frozen

    def execute(*_):
        return {
            **fake_execute(None, None),
            "stdout": b'{"scorer":"PASS", "cost":{"usd":0}}',
        }

    monkeypatch.setattr(pilot, "execute", execute)
    result = pilot.run(method, path, digest, output)
    assert result["status"] == "incomplete"
    receipt = json.loads((output / "receipt.json").read_bytes())
    assert len(receipt["attempts"]) == 3
    assert all(
        row["delivery"] == 0 and row["cost"]["usd"] == "unavailable"
        for row in receipt["attempts"]
    )
    assert all(row["cost"]["elapsed_ms"] == 2 for row in receipt["attempts"])


def test_answer_open_after_attempts_and_failed_slots_retained(frozen, monkeypatch):
    method, path, digest, output = frozen
    load = evaluator.load_fixtures

    def checked_load():
        assert (output / "attempts.json").exists()
        assert len(json.loads((output / "executions.json").read_bytes())) == 3
        return load()

    monkeypatch.setattr(evaluator, "load_fixtures", checked_load)
    monkeypatch.setattr(
        pilot, "execute", lambda *_: {**fake_execute(None, None), "status": "timed_out"}
    )
    report = pilot.run(method, path, digest, output)
    assert report["status"] == "incomplete"
    assert len(report["executions"]) == 3
    assert all(e["status"] == "timed_out" for e in report["executions"])
    assert all(
        (output / f"{e['task_id']}.stderr").read_bytes() == b"log"
        for e in report["executions"]
    )


def test_post_execution_method_tamper_keeps_attempts_but_no_receipt(
    frozen, monkeypatch
):
    method, path, digest, output = frozen

    def execute(*_):
        method.write_text("print('tampered')")
        return fake_execute(None, None)

    monkeypatch.setattr(pilot, "execute", execute)
    with pytest.raises(ValueError, match="freeze_binding_mismatch"):
        pilot.run(method, path, digest, output)
    assert len(json.loads((output / "attempts.json").read_bytes())["attempts"]) == 3
    assert not (output / "receipt.json").exists()


def test_scorer_identity_change_rejected(frozen, monkeypatch):
    method, path, digest, _ = frozen
    monkeypatch.setattr(pilot, "identity", lambda: {"candidate-selected": "0" * 64})
    with pytest.raises(ValueError, match="freeze_binding_mismatch"):
        pilot.check_freeze(path.read_bytes(), digest, method)


def test_no_bwrap_never_cooperative_fallback(monkeypatch):
    monkeypatch.setattr(pilot.shutil, "which", lambda _: None)
    result = pilot.execute(b"raise RuntimeError('must not execute')", b"{}")
    assert result["status"] == "isolation_unavailable"
    assert result["stdout"] == b""


def require_actual_boundary(probe):
    if probe["status"] != "completed":
        reason = "actual bubblewrap boundary unavailable: " + probe["stderr"].decode(
            errors="replace"
        )
        if os.environ.get("ARW_REQUIRE_INDEPENDENT_ISOLATION") == "1":
            pytest.fail(reason, pytrace=False)
        pytest.skip(reason)


def test_actual_namespace_blocks_answers_cwd_logs_resume_and_network(
    tmp_path, monkeypatch
):
    # This test owns its exact boundary probe rather than the broader harness
    # prerequisite marker, which could skip before required-mode checks execute.
    require_actual_boundary(pilot.execute(b"print('ready')", b"{}"))
    monkeypatch.chdir(tmp_path)
    secret = tmp_path / "hidden-reference.json"
    secret.write_text("ANSWER_CANARY")
    (tmp_path / "resume.json").write_text("ANSWER_CANARY")
    (tmp_path / "stdout.log").write_text("ANSWER_CANARY")
    monkeypatch.setenv("ANSWER_CANARY", "secret")
    source = f"""
import os, pathlib, socket
assert os.getcwd() == '/work'
assert not os.environ.get('ANSWER_CANARY')
for path in {list(map(str, [secret, tmp_path / "resume.json", tmp_path / "stdout.log", evaluator.FIXTURE / "hidden-reference.json"]))!r}:
    assert not pathlib.Path(path).exists(), path
assert not pathlib.Path('/work/resume.json').exists()
s = socket.socket()
s.settimeout(0.1)
assert s.connect_ex(('1.1.1.1', 443)) != 0
pathlib.Path('/work/resume.json').write_text('private prior attempt')
print('isolated')
""".encode()
    first = pilot.execute(source, b"{}")
    second = pilot.execute(source, b"{}")
    assert first["status"] == second["status"] == "completed"
    assert first["stdout"] == second["stdout"] == b"isolated\n"


def test_successful_execution_is_still_numerically_scored(frozen, monkeypatch):
    method, path, digest, output = frozen

    def execute(*_):
        return {
            **fake_execute(None, None),
            "stdout": evaluator.canonical(
                {
                    "selected_config": "0000",
                    "responses": [
                        {"config": config, "value": 0} for config in evaluator.CONFIGS
                    ],
                }
            ),
        }

    monkeypatch.setattr(pilot, "execute", execute)
    report = pilot.run(method, path, digest, output)
    receipt = json.loads((output / "receipt.json").read_bytes())
    assert report["status"] == "completed"
    assert all(
        row["errors"]["conditional_effect_mae"] > 0 for row in receipt["attempts"]
    )
    assert evaluator.verify_receipt(
        (output / "receipt.json").read_bytes(),
        evaluator.load_fixtures(),
        (output / "attempts.json").read_bytes(),
    )


def test_interrupted_run_keeps_full_plan_and_started_attempt(frozen, monkeypatch):
    method, path, digest, output = frozen

    def interrupted(*_):
        raise KeyboardInterrupt

    monkeypatch.setattr(pilot, "execute", interrupted)
    with pytest.raises(KeyboardInterrupt):
        pilot.run(method, path, digest, output)
    attempts = json.loads((output / "attempts.json").read_bytes())
    assert len(attempts["plan"]) == 3 and attempts["attempts"] == []
    assert (
        json.loads((output / "executions.json").read_bytes())[0]["status"] == "started"
    )
    assert not (output / "receipt.json").exists()


def test_failed_control_never_publishes_receipt(frozen, monkeypatch):
    method, path, digest, output = frozen
    monkeypatch.setattr(pilot, "execute", fake_execute)

    def failed(*_):
        raise evaluator.ExperimentEvalError("scorer_controls_failed")

    monkeypatch.setattr(pilot, "control_check", failed)
    with pytest.raises(ValueError, match="scorer_controls_failed"):
        pilot.run(method, path, digest, output)
    assert (output / "attempts.json").exists()
    assert not (output / "receipt.json").exists()


def numeric_output(value):
    return evaluator.canonical(
        {
            "selected_config": "0000",
            "responses": [
                {"config": config, "value": value} for config in evaluator.CONFIGS
            ],
        }
    )


@pytest.mark.parametrize(
    "raw",
    [
        b"[" * 2000 + b"0" + b"]" * 2000,
        b'{"selected_config":"0000","responses":'
        + b"[" * 2000
        + b"0"
        + b"]" * 2000
        + b"}",
        numeric_output(10**400),
        numeric_output(1e308),
        numeric_output(0).replace(b'"value":0', b'"value":1e999'),
        numeric_output({"nested": [0]}),
        evaluator.canonical({"selected_config": [], "responses": []}),
    ],
)
def test_malicious_output_keeps_failed_slot_and_scores_other_slots(
    frozen, monkeypatch, raw
):
    method, path, digest, output = frozen
    calls = []

    def execute(*_):
        calls.append(1)
        return {
            **fake_execute(None, None),
            "stdout": raw if len(calls) == 1 else numeric_output(0),
        }

    monkeypatch.setattr(pilot, "execute", execute)
    report = pilot.run(method, path, digest, output)
    assert len(calls) == 3
    assert report["status"] == "incomplete"
    assert [row["status"] for row in report["executions"]] == [
        "invalid_output",
        "completed",
        "completed",
    ]
    assert (output / "cpu-batch-v1.stdout").read_bytes() == raw
    attempts = json.loads((output / "attempts.json").read_bytes())
    assert len(attempts["plan"]) == len(attempts["attempts"]) == 3
    assert "responses" not in attempts["attempts"][0]
    receipt = json.loads((output / "receipt.json").read_bytes())
    assert [row["delivery"] for row in receipt["attempts"]] == [0, 1, 1]
    assert receipt["attempts"][0]["errors"] is None
    assert all(
        row["cost"]["elapsed_ms"] == 2 and row["cost"]["usd"] == "unavailable"
        for row in receipt["attempts"]
    )
    assert evaluator.verify_receipt(
        (output / "receipt.json").read_bytes(),
        evaluator.load_fixtures(),
        (output / "attempts.json").read_bytes(),
    )


def test_prediction_magnitude_bound_is_frozen_and_numerically_safe(frozen):
    _, path, _, _ = frozen
    assert json.loads(path.read_bytes())["limits"]["prediction_absolute_max"] == 1e100
    assert (
        pilot.candidate_predictions(numeric_output(1e100))["responses"][0]["value"]
        == 1e100
    )
    # The largest accepted magnitude must survive the actual scorer arithmetic.
    state = evaluator.load_fixtures()
    bundle = evaluator.ridge_attempts(state)
    for attempt in bundle["attempts"]:
        attempt.update(pilot.candidate_predictions(numeric_output(1e100)))
    receipt = json.loads(evaluator.score(state, evaluator.canonical(bundle)))
    assert all(row["delivery"] == 1 for row in receipt["attempts"])


@pytest.mark.parametrize(
    "target", ["checkout", "fixture", "answer_symlink", "fixture_symlink"]
)
def test_runtime_mount_rejects_protected_paths(tmp_path, monkeypatch, target):
    if target == "checkout":
        monkeypatch.setattr(pilot, "ROOT", Path("/usr/local/arw"))
    elif target == "fixture":
        monkeypatch.setattr(evaluator, "FIXTURE", Path("/usr/local/arw-fixture"))
    elif target == "answer_symlink":
        (tmp_path / "hidden-reference.json").symlink_to("/usr/local/answers.json")
        monkeypatch.setattr(evaluator, "FIXTURE", tmp_path)
    else:
        (tmp_path / "fixture").symlink_to("/usr/local/arw-fixture")
        monkeypatch.setattr(evaluator, "FIXTURE", tmp_path / "fixture")
    with pytest.raises(ValueError, match="runtime_mount_contains_protected_input"):
        pilot.execute(b"print('must not launch')", b"{}")


def test_python_invocation_disables_system_site_hooks(monkeypatch):
    seen = []

    def run(command, **kwargs):
        seen.append(command)
        return pilot.subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(pilot.shutil, "which", lambda _: "/usr/bin/bwrap")
    monkeypatch.setattr(pilot.subprocess, "run", run)
    assert pilot.execute(b"print('test')", b"{}")["status"] == "completed"
    command = seen[0]
    python = command.index("/usr/bin/python3")
    assert command[python + 1 : python + 4] == ["-I", "-S", "/input/method.py"]


@pytest.mark.parametrize("required", [False, True])
def test_unavailable_boundary_fails_only_in_required_mode(monkeypatch, required):
    monkeypatch.delenv("ARW_REQUIRE_INDEPENDENT_ISOLATION", raising=False)
    if required:
        monkeypatch.setenv("ARW_REQUIRE_INDEPENDENT_ISOLATION", "1")
    expected = pytest.fail.Exception if required else pytest.skip.Exception
    with pytest.raises(
        expected, match="actual bubblewrap boundary unavailable: denied"
    ):
        require_actual_boundary(
            {"status": "isolation_unavailable", "stderr": b"denied"}
        )


def test_required_boundary_accepts_successful_probe(monkeypatch):
    monkeypatch.setenv("ARW_REQUIRE_INDEPENDENT_ISOLATION", "1")
    require_actual_boundary({"status": "completed", "stderr": b""})
