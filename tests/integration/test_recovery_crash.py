from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest


RUN_ID = "run-00000000-0000-4000-8000-000000000091"


def _initialize(root: Path):
    from arw.journal import initialize_run
    from arw.kernel.state.models import InitRunRequest
    from arw.workflows import CORE_WORKFLOW

    source = root / "input/source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("recovery crash\n", encoding="utf-8")
    return initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "occurred_at": "2026-07-13T08:00:00Z",
                "immutable_input": {
                    "path": "input/source.txt",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                },
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "workflow_definition_id": CORE_WORKFLOW.definition_id,
                "workflow_definition_sha256": CORE_WORKFLOW.sha256,
                "journal_layout": "segmented-v1",
                "capabilities": ["canonical-journal", "forced-stop-replay"],
                "event_id": "evt-00000000-0000-4000-8000-000000000091",
                "command_id": "cmd-00000000-0000-4000-8000-000000000091",
                "actor_id": "parent.runtime",
            }
        ),
    )


def _write_request(path: Path, value: object) -> None:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.write_text(json.dumps(payload), encoding="utf-8")


def _recovery_request(state):
    from arw.kernel.state.models import RecoveryRequest

    return RecoveryRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "event_id": "evt-00000000-0000-4000-8000-000000000092",
            "command_id": "cmd-00000000-0000-4000-8000-000000000092",
            "expected_revision": state.revision,
            "expected_head_sha256": state.last_event_sha256,
            "occurred_at": "2026-07-13T08:10:00Z",
            "actor_id": "operator.user",
            "actor_role": "operator",
            "recovery_id": "recovery.crash-001",
            "original_segment_sha256": state.segments[-1].sha256,
            "reason_code": "process-terminated",
            "reason_text": "test recovery transaction interruption",
        }
    )


def test_partial_runtime_append_becomes_recoverable_tail(tmp_path: Path) -> None:
    from arw.journal import replay_run

    root = tmp_path / "partial-append"
    initialized = _initialize(root)
    request = {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "event_id": "evt-00000000-0000-4000-8000-000000000093",
        "command_id": "cmd-00000000-0000-4000-8000-000000000093",
        "expected_revision": 1,
        "occurred_at": "2026-07-13T08:01:00Z",
        "actor_id": "parent.runtime",
        "actor_role": "parent_control_plane",
        "transition_id": "start",
        "from_stage": "initialized",
    }
    request_path = tmp_path / "transition.json"
    _write_request(request_path, request)
    environment = os.environ.copy()
    environment["ARW_TEST_FAILPOINT"] = "partial-runtime-append-sigkill"

    killed = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "transition",
            "--run-root",
            str(root),
            "--request",
            str(request_path),
        ],
        env=environment,
        capture_output=True,
        check=False,
    )

    assert killed.returncode == -signal.SIGKILL
    state = replay_run(root)
    assert state.recovery_health == "recoverable_tail"
    assert state.revision == initialized.revision
    assert state.segments[-1].fault_offset == initialized.segments[-1].accepted_byte_end


@pytest.mark.parametrize(
    "failpoint",
    [
        "post-quarantine-raw-fsync-sigkill",
        "post-recovery-receipt-fsync-sigkill",
        "post-recovery-segment-publication-sigkill",
    ],
)
def test_recovery_crash_is_absent_or_fully_replayable_and_retryable(
    tmp_path: Path, failpoint: str
) -> None:
    from arw.evidence import record_command_result
    from arw.journal import replay_run

    root = tmp_path / failpoint
    _initialize(root)
    first = root / "journal/segments/00000001.jsonl"
    first.write_bytes(first.read_bytes() + b'{"partial":')
    degraded = replay_run(root)
    request_path = tmp_path / f"{failpoint}.json"
    _write_request(request_path, _recovery_request(degraded))
    argv = [
        sys.executable,
        "-m",
        "arw.cli",
        "recover",
        "--run-root",
        str(root),
        "--request",
        str(request_path),
    ]
    environment = os.environ.copy()
    environment["ARW_TEST_FAILPOINT"] = failpoint

    killed = subprocess.run(argv, env=environment, capture_output=True, check=False)
    record_command_result(
        tmp_path / "evidence" / failpoint,
        argv=argv,
        cwd=Path.cwd(),
        cwd_base=Path.cwd(),
        environment=environment,
        result=killed,
    )

    assert killed.returncode == -signal.SIGKILL
    state = replay_run(root)
    published = failpoint == "post-recovery-segment-publication-sigkill"
    assert state.recovery_health == ("healthy" if published else "recoverable_tail")
    assert (root / "journal/segments/00000002.jsonl").exists() is published
    raw = root / "quarantine/recovery.crash-001/segment.raw"
    assert raw.read_bytes() == first.read_bytes()
    receipt = root / "quarantine/recovery.crash-001/receipt.json"
    assert receipt.exists() is (failpoint != "post-quarantine-raw-fsync-sigkill")

    retry_environment = os.environ.copy()
    retry_environment.pop("ARW_TEST_FAILPOINT", None)
    retry = subprocess.run(
        argv,
        env=retry_environment,
        capture_output=True,
        check=False,
    )
    assert retry.returncode == 0, retry.stderr.decode()
    recovered = replay_run(root)
    assert recovered.recovery_health == "healthy"
    assert recovered.revision == 2
    assert sum(
        event.event_type == "recovery.completed" for event in recovered.events
    ) == 1

