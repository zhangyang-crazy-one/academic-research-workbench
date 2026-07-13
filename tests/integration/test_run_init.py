from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import jsonschema


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEED = REPOSITORY_ROOT / "tests/fixtures/recovery/seed"
SCHEMAS = REPOSITORY_ROOT / "schemas/v1"


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({"PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1"})
    return subprocess.run(
        [sys.executable, "-m", "arw.cli", *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _seed_run(tmp_path: Path) -> Path:
    run_root = tmp_path / "run"
    (run_root / "input").mkdir(parents=True)
    shutil.copyfile(SEED / "input/source.txt", run_root / "input/source.txt")
    return run_root


def _validate(name: str, payload: dict[str, object]) -> None:
    schema = json.loads((SCHEMAS / name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    ).validate(payload)


def test_init_writes_byte_exact_manifest_and_first_event(tmp_path: Path) -> None:
    run_root = _seed_run(tmp_path)
    result = _run_cli(
        "init",
        "--run-root",
        str(run_root),
        "--request",
        str(SEED / "init-request.json"),
    )
    assert result.returncode == 0, (
        "expected RED: init command is absent or incomplete\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    manifest_bytes = (run_root / "run-manifest.json").read_bytes()
    journal_bytes = (run_root / "events.jsonl").read_bytes()
    assert manifest_bytes == (SEED / "expected-run-manifest.json").read_bytes()
    assert journal_bytes == (SEED / "expected-initial-event.jsonl").read_bytes()
    _validate("run-manifest.schema.json", json.loads(manifest_bytes))
    _validate("event.schema.json", json.loads(journal_bytes))
    assert json.loads(result.stdout) == {
        "event_sha256": "ccaeb5835eda28b6b374a2ced8200795e5f3a2dbf236687967d2db01e00c7b9f",
        "revision": 1,
        "run_id": "run-00000000-0000-4000-8000-000000000001",
    }


def test_init_requires_strict_immutable_identity_mode_and_capabilities(tmp_path: Path) -> None:
    request = json.loads((SEED / "init-request.json").read_text(encoding="utf-8"))
    invalid_values = [
        {**request, "schema_version": "2.0.0"},
        {**request, "workflow_mode": "full-lifecycle"},
        {**request, "capabilities": []},
        {**request, "unknown": True},
        {**request, "immutable_input": {"path": "../escape", "sha256": "0" * 64}},
    ]
    for index, invalid in enumerate(invalid_values):
        run_root = _seed_run(tmp_path / str(index))
        request_path = tmp_path / f"invalid-{index}.json"
        request_path.write_text(json.dumps(invalid), encoding="utf-8")
        result = _run_cli(
            "init", "--run-root", str(run_root), "--request", str(request_path)
        )
        assert result.returncode != 0
        assert not (run_root / "run-manifest.json").exists()
        assert not (run_root / "events.jsonl").exists()


def test_append_replays_chain_and_rejects_stale_or_malformed_state_without_mutation(
    tmp_path: Path,
) -> None:
    run_root = _seed_run(tmp_path)
    initialized = _run_cli(
        "init", "--run-root", str(run_root), "--request", str(SEED / "init-request.json")
    )
    assert initialized.returncode == 0, initialized.stderr
    journal = run_root / "events.jsonl"
    before = journal.read_bytes()

    request = json.loads((SEED / "append-request.json").read_text(encoding="utf-8"))
    stale_path = tmp_path / "stale.json"
    stale_path.write_text(json.dumps({**request, "expected_revision": 0}), encoding="utf-8")
    stale = _run_cli(
        "append", "--run-root", str(run_root), "--request", str(stale_path)
    )
    assert stale.returncode != 0
    assert journal.read_bytes() == before

    journal.write_bytes(before + b'{"partial":')
    malformed_before = journal.read_bytes()
    malformed = _run_cli(
        "append", "--run-root", str(run_root), "--request", str(SEED / "append-request.json")
    )
    assert malformed.returncode != 0
    assert journal.read_bytes() == malformed_before


def test_append_is_locked_hash_chained_and_duplicate_free(tmp_path: Path) -> None:
    run_root = _seed_run(tmp_path)
    initialized = _run_cli(
        "init", "--run-root", str(run_root), "--request", str(SEED / "init-request.json")
    )
    assert initialized.returncode == 0, initialized.stderr
    journal = run_root / "events.jsonl"
    initial_bytes = journal.read_bytes()

    holder_code = textwrap.dedent(
        """
        import pathlib
        import portalocker
        import sys
        import time

        lock_path = pathlib.Path(sys.argv[1])
        with portalocker.Lock(lock_path, mode="a+b", timeout=0):
            print("locked", flush=True)
            time.sleep(30)
        """
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(run_root / ".journal.lock")],
        cwd=REPOSITORY_ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        contended = _run_cli(
            "append",
            "--lock-timeout",
            "0",
            "--run-root",
            str(run_root),
            "--request",
            str(SEED / "append-request.json"),
        )
        assert contended.returncode != 0
        assert journal.read_bytes() == initial_bytes
    finally:
        holder.terminate()
        holder.wait(timeout=5)

    appended = _run_cli(
        "append", "--run-root", str(run_root), "--request", str(SEED / "append-request.json")
    )
    assert appended.returncode == 0, appended.stderr
    appended_bytes = journal.read_bytes()
    lines = appended_bytes.splitlines()
    assert len(lines) == 2
    first, second = map(json.loads, lines)
    _validate("event.schema.json", second)
    assert second["sequence"] == 2
    assert second["expected_revision"] == 1
    assert second["resulting_revision"] == 2
    assert second["prev_event_sha256"] == first["event_sha256"]

    duplicate_request = json.loads((SEED / "append-request.json").read_text(encoding="utf-8"))
    duplicate_request["expected_revision"] = 2
    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(json.dumps(duplicate_request), encoding="utf-8")
    duplicate = _run_cli(
        "append", "--run-root", str(run_root), "--request", str(duplicate_path)
    )
    assert duplicate.returncode != 0
    assert journal.read_bytes() == appended_bytes

    replayed = _run_cli("replay", "--run-root", str(run_root))
    assert replayed.returncode == 0, replayed.stderr
    replay = json.loads(replayed.stdout)
    assert replay == {
        "event_count": 2,
        "last_event_sha256": second["event_sha256"],
        "revision": 2,
        "run_id": second["run_id"],
    }
