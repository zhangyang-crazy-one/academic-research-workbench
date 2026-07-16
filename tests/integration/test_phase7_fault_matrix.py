"""Phase 7 deterministic recovery/fault qualification matrix.

Each case owns a fresh run root and (when a process boundary is involved) a
fresh subprocess.  The matrix writes only bounded parent-side sidecars; the
run ledger remains the sole authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from arw.canonical import canonical_event_bytes, canonical_json_bytes, sha256_hex, strict_json_loads
from arw.evidence import write_fault_sidecar
from arw.faults import (
    FAULT_SPECS,
    FaultConfigurationError,
    InjectedFault,
    fault_ids,
)
from arw.journal import JournalError, replay_run
from arw.models import InitRunRequest, LifecycleTransitionRequest, RuntimeCommandRequest
from arw.runtime import RuntimeCommandService
from arw.workflows import CORE_WORKFLOW

from .test_recovery import _damage, _initialize


FIXTURE = Path(__file__).parents[1] / "fixtures" / "recovery" / "phase7_faults" / "registry.json"
RUN_ID = "run-00000000-0000-4000-8000-000000000781"


def _transition_request(run_id: str, *, event_number: int, revision: int = 1) -> LifecycleTransitionRequest:
    return LifecycleTransitionRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": run_id,
            "event_id": f"evt-00000000-0000-4000-8000-{event_number:012x}",
            "command_id": f"cmd-00000000-0000-4000-8000-{event_number:012x}",
            "expected_revision": revision,
            "occurred_at": f"2026-07-16T01:00:{event_number % 60:02d}Z",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "transition_id": "start",
            "from_stage": "initialized",
        }
    )


def _fresh_run(root: Path) -> None:
    source = root / "input" / "source.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("phase seven recovery input\n", encoding="utf-8")
    initialize = InitRunRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "occurred_at": "2026-07-16T00:00:00Z",
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
            "event_id": "evt-00000000-0000-4000-8000-000000000781",
            "command_id": "cmd-00000000-0000-4000-8000-000000000781",
            "actor_id": "parent.runtime",
        }
    )
    from arw.journal import initialize_run

    initialize_run(root, initialize)


def _redacted_snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file() and ".journal.lock" not in path.name:
            relative = path.relative_to(root).as_posix()
            result[relative] = sha256_hex(path.read_bytes())
    return result


def _event_sequence_hash(root: Path) -> str:
    replayed = replay_run(root)
    return sha256_hex(
        canonical_json_bytes(
            [canonical_event_bytes(event.model_dump(mode="json")).decode("utf-8") for event in replayed.events]
        )
    )


def _sidecar(
    evidence_root: Path,
    *,
    fault_id: str,
    boundary: str,
    run_root: Path,
    classification: str,
    reason: str,
    retries: int = 0,
    event_hash: str | None = None,
    recovery_hash: str | None = None,
    stdout: bytes | str = "",
    stderr: bytes | str = "",
) -> dict[str, Any]:
    digest = write_fault_sidecar(
        evidence_root,
        fault_id=fault_id,
        boundary=boundary,
        run_relative_root="run",
        stdout=stdout,
        stderr=stderr,
        file_snapshots=_redacted_snapshot(run_root),
        process_state={"returncode": 0, "signal": None},
        replay_classification=classification,
        reason_code=reason,
        retry_count=retries,
        event_sequence_sha256=event_hash or _event_sequence_hash(run_root),
        canonical_recovery_event_sha256=recovery_hash,
    )
    return {
        "fault_id": fault_id,
        "boundary": boundary,
        "sidecar_sha256": digest,
        "event_sequence_sha256": event_hash or _event_sequence_hash(run_root),
        "replay_classification": classification,
        "reason_code": reason,
        "retry_count": retries,
    }


def test_phase7_fault_registry_is_guarded_and_stable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    registry = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture_ids = tuple(item["fault_id"] for item in registry["faults"])
    assert set(fixture_ids) <= set(fault_ids())
    assert tuple(sorted(fixture_ids)) == tuple(sorted(fixture_ids))
    assert all(item["boundary"] == FAULT_SPECS[item["fault_id"]].boundary for item in registry["faults"])

    root = tmp_path / "guarded"
    _fresh_run(root)
    request = _transition_request(RUN_ID, event_number=782)
    monkeypatch.setenv("ARW_TEST_FAULT_ID", "phase7.canonical-write-before-commit")
    monkeypatch.delenv("ARW_TEST_MODE", raising=False)
    with pytest.raises(FaultConfigurationError, match="ARW_TEST_MODE"):
        RuntimeCommandService(root).execute_transition(request)
    monkeypatch.setenv("ARW_TEST_MODE", "1")
    with pytest.raises(InjectedFault, match="canonical-write-before-commit"):
        RuntimeCommandService(root).execute_transition(request)
    assert replay_run(root).revision == 1

    monkeypatch.setenv("ARW_TEST_FAULT_ID", "phase7.not-registered")
    with pytest.raises(FaultConfigurationError, match="unknown deterministic fault"):
        RuntimeCommandService(root).read_state()


def test_phase7_write_and_fsync_boundaries_have_distinct_replay_semantics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "boundaries"
    _fresh_run(root)
    request = _transition_request(RUN_ID, event_number=783)
    monkeypatch.setenv("ARW_TEST_MODE", "1")

    monkeypatch.setenv("ARW_TEST_FAULT_ID", "phase7.canonical-write-before-commit")
    with pytest.raises(InjectedFault):
        RuntimeCommandService(root).execute_transition(request)
    assert replay_run(root).revision == 1

    monkeypatch.setenv("ARW_TEST_FAULT_ID", "phase7.journal-fsync")
    with pytest.raises(InjectedFault):
        RuntimeCommandService(root).execute_transition(request)
    durable = replay_run(root)
    assert durable.revision == 2
    monkeypatch.delenv("ARW_TEST_FAULT_ID")
    duplicate = RuntimeCommandService(root).execute_transition(request)
    assert not duplicate.accepted
    assert duplicate.rejection is not None and duplicate.rejection.code == "duplicate-event-id"


def test_phase7_lock_faults_fail_closed_and_owner_death_releases_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "lock"
    _fresh_run(root)
    monkeypatch.setenv("ARW_TEST_MODE", "1")
    monkeypatch.setenv("ARW_TEST_FAULT_ID", "phase7.lock-acquire")
    with pytest.raises(InjectedFault):
        RuntimeCommandService(root).read_state()
    monkeypatch.delenv("ARW_TEST_FAULT_ID")
    assert RuntimeCommandService(root).read_state().accepted_revision == 1

    request = _transition_request(RUN_ID, event_number=784)
    request_path = tmp_path / "request.json"
    request_path.write_bytes(canonical_json_bytes(request.model_dump(mode="json")))
    env = os.environ.copy()
    env.update({"ARW_TEST_MODE": "1", "ARW_TEST_FAULT_ID": "phase7.lock-owner-death"})
    child = subprocess.run(
        [sys.executable, "-m", "arw.cli", "transition", "--run-root", str(root), "--request", str(request_path)],
        env=env,
        capture_output=True,
        check=False,
    )
    assert child.returncode == -signal.SIGKILL
    env.pop("ARW_TEST_FAULT_ID", None)
    resumed = subprocess.run(
        [sys.executable, "-m", "arw.cli", "transition", "--run-root", str(root), "--request", str(request_path)],
        env=env,
        capture_output=True,
        check=False,
    )
    assert resumed.returncode == 0, resumed.stderr.decode()
    assert replay_run(root).revision == 2
