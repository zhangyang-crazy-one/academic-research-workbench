from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import signal
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEED = REPOSITORY_ROOT / "tests/fixtures/recovery/seed"
EVIDENCE_ROOT = REPOSITORY_ROOT / "build/evidence/phase-01/runtime/seed"


def _relative(path: Path) -> str:
    return path.relative_to(REPOSITORY_ROOT).as_posix()


def _run(
    arguments: list[str],
    environment: dict[str, str],
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        arguments,
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        check=False,
    )


def _command(command: str, run_root: Path, request: Path | None = None) -> list[str]:
    arguments = [
        ".venv/bin/python",
        "-m",
        "arw.cli",
        command,
        "--run-root",
        _relative(run_root),
    ]
    if request is not None:
        arguments.extend(["--request", _relative(request)])
    return arguments


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def test_post_fsync_sigkill_replays_once_without_changing_journal() -> None:
    shutil.rmtree(EVIDENCE_ROOT, ignore_errors=True)
    workspace = EVIDENCE_ROOT / "workspace"
    seed_copy = workspace / "seed"
    run_root = workspace / "run"
    shutil.copytree(SEED, seed_copy)
    (run_root / "input").mkdir(parents=True)
    shutil.copyfile(seed_copy / "input/source.txt", run_root / "input/source.txt")

    environment = os.environ.copy()
    environment.update({"PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1"})
    environment.pop("ARW_TEST_FAILPOINT", None)

    init_command = _command("init", run_root, seed_copy / "init-request.json")
    initialized = _run(init_command, environment)
    assert initialized.returncode == 0, initialized.stderr.decode(errors="replace")
    journal = run_root / "events.jsonl"
    before_kill = journal.read_bytes()
    assert len(before_kill.splitlines()) == 1

    killed_environment = environment | {
        "ARW_TEST_FAILPOINT": "post-journal-fsync-sigkill"
    }
    append_command = _command("append", run_root, seed_copy / "append-request.json")
    killed = _run(append_command, killed_environment)
    assert killed.returncode == -signal.SIGKILL, (
        "expected RED: append was not killed at the post-fsync boundary; "
        f"returncode={killed.returncode}, stdout={killed.stdout!r}, stderr={killed.stderr!r}"
    )
    assert killed.stdout == b""
    after_kill = journal.read_bytes()
    events = [json.loads(line) for line in after_kill.splitlines()]
    assert len(events) == 2
    assert sum(event["event_type"] == "baseline.probe_recorded" for event in events) == 1

    assert importlib.util.find_spec("arw.evidence") is not None, (
        "expected RED: allowlisted recovery evidence capture is not implemented"
    )
    from arw.kernel.artifacts.evidence import record_command_result, write_evidence_bytes, write_evidence_json

    commands_root = EVIDENCE_ROOT / "commands"
    record_command_result(
        commands_root / "init",
        argv=init_command,
        cwd=REPOSITORY_ROOT,
        cwd_base=REPOSITORY_ROOT,
        environment=environment,
        result=initialized,
    )
    record_command_result(
        commands_root / "append-forced-stop",
        argv=append_command,
        cwd=REPOSITORY_ROOT,
        cwd_base=REPOSITORY_ROOT,
        environment=killed_environment,
        result=killed,
    )
    write_evidence_bytes(EVIDENCE_ROOT / "journal/before-kill.jsonl", before_kill)
    write_evidence_bytes(EVIDENCE_ROOT / "journal/after-kill.jsonl", after_kill)

    replay_command = _command("replay", run_root)
    replayed = _run(replay_command, environment)
    record_command_result(
        commands_root / "replay-fresh-process",
        argv=replay_command,
        cwd=REPOSITORY_ROOT,
        cwd_base=REPOSITORY_ROOT,
        environment=environment,
        result=replayed,
    )
    assert replayed.returncode == 0, replayed.stderr.decode(errors="replace")
    replay = json.loads(replayed.stdout)
    after_replay = journal.read_bytes()
    assert after_replay == after_kill
    assert replay == {
        "event_count": 2,
        "last_event_sha256": events[-1]["event_sha256"],
        "revision": 2,
        "run_id": "run-00000000-0000-4000-8000-000000000001",
    }

    duplicate_command = _command("append", run_root, seed_copy / "append-request.json")
    duplicate = _run(duplicate_command, environment)
    record_command_result(
        commands_root / "duplicate-retry",
        argv=duplicate_command,
        cwd=REPOSITORY_ROOT,
        cwd_base=REPOSITORY_ROOT,
        environment=environment,
        result=duplicate,
    )
    assert duplicate.returncode != 0
    after_duplicate = journal.read_bytes()
    assert after_duplicate == after_kill

    write_evidence_bytes(EVIDENCE_ROOT / "journal/after-replay.jsonl", after_replay)
    write_evidence_json(EVIDENCE_ROOT / "replay.json", replay)
    write_evidence_json(
        EVIDENCE_ROOT / "journal/hashes.json",
        {
            "after_duplicate_sha256": _sha256(after_duplicate),
            "after_kill_sha256": _sha256(after_kill),
            "after_replay_sha256": _sha256(after_replay),
            "before_kill_sha256": _sha256(before_kill),
        },
    )
    write_evidence_json(
        EVIDENCE_ROOT / "verdict.json",
        {
            "duplicate_retry_rejected": True,
            "durable_baseline_event_count": 1,
            "forced_stop_signal": "SIGKILL",
            "journal_unchanged_by_replay": True,
            "last_event_sha256": replay["last_event_sha256"],
            "last_revision": replay["revision"],
            "technical_qualification": "PASS",
        },
    )

    assert (commands_root / "append-forced-stop/exit.json").is_file()
    exit_record = json.loads(
        (commands_root / "append-forced-stop/exit.json").read_text(encoding="utf-8")
    )
    assert exit_record == {"returncode": -9, "signal": "SIGKILL"}
    command_record = json.loads(
        (commands_root / "append-forced-stop/command.json").read_text(encoding="utf-8")
    )
    assert command_record["cwd"] == "."
    assert command_record["environment"] == {
        "ARW_TEST_FAILPOINT": "post-journal-fsync-sigkill",
        "PYTHONNOUSERSITE": "1",
        "UV_OFFLINE": "1",
    }
    assert set(command_record) == {"argv", "cwd", "environment"}


def test_phase4_canonical_event_bytes_replay_to_identical_parent_state() -> None:
    from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads
    from arw.kernel.state.models import CanonicalEvent
    from arw.kernel.ledger.reducer import reduce_events

    event = CanonicalEvent.model_validate(
        {
            "schema_version": "1.0.0",
            "event_type": "execution.mode_selected",
            "event_id": "evt-00000000-0000-4000-8000-000000000601",
            "command_id": "cmd-00000000-0000-4000-8000-000000000601",
            "run_id": "run-00000000-0000-4000-8000-000000000001",
            "sequence": 2,
            "occurred_at": "2026-07-15T00:00:01Z",
            "expected_revision": 1,
            "resulting_revision": 2,
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "prev_event_sha256": "0" * 64,
            "payload": {
                "execution_mode": "assignment_injected_subagent",
                "execution_provenance": "assignment_injected_subagent",
                "role_catalog_sha256": "a" * 64,
                "policy_sha256": "b" * 64,
                "dag_sha256": "c" * 64,
            },
            "event_sha256": "2" * 64,
        }
    )
    raw = canonical_json_bytes(event.model_dump(mode="json"))
    replayed = CanonicalEvent.model_validate(strict_json_loads(raw))
    # A synthetic initialized prefix makes the reducer's phase-independent
    # state shape explicit while the event bytes remain the only input.
    initialized = CanonicalEvent.model_validate(
        {
            "schema_version": "1.0.0",
            "event_type": "run.initialized",
            "event_id": "evt-00000000-0000-4000-8000-000000000600",
            "command_id": "cmd-00000000-0000-4000-8000-000000000600",
            "run_id": event.run_id,
            "sequence": 1,
            "occurred_at": "2026-07-15T00:00:00Z",
            "expected_revision": 0,
            "resulting_revision": 1,
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "prev_event_sha256": "0" * 64,
            "payload": {"manifest_sha256": "d" * 64},
            "event_sha256": "1" * 64,
        }
    )
    first = reduce_events("core-research.v1", [initialized, event])
    second = reduce_events("core-research.v1", [initialized, replayed])
    assert first == second
    assert first.execution_mode == "assignment_injected_subagent"
