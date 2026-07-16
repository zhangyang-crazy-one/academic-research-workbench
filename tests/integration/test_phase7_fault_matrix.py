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
import re
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
from arw.models import InitRunRequest, LifecycleTransitionRequest, RecoveryRequest, RuntimeCommandRequest
from arw.execution import DispatchSpec, ExecutionPolicySnapshot, HostResult, RepairableEnvelopeFailure
from arw.scheduler import DeterministicScheduler
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


def _recovery_request(root: Path, *, number: int = 790) -> RecoveryRequest:
    state = replay_run(root)
    damaged = state.segments[-1]
    return RecoveryRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "event_id": f"evt-00000000-0000-4000-8000-{number:012x}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012x}",
            "expected_revision": state.revision,
            "expected_head_sha256": state.last_event_sha256,
            "occurred_at": "2026-07-16T01:10:00Z",
            "actor_id": "operator.user",
            "actor_role": "operator",
            "recovery_id": f"recovery.phase7-{number}",
            "original_segment_sha256": damaged.sha256,
            "reason_code": "process-terminated",
            "reason_text": "phase7 bounded recovery fault",
        }
    )


def _write_request(path: Path, value: object) -> None:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    path.write_bytes(canonical_json_bytes(payload))


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


def _evidence_event_hash(root: Path) -> str:
    try:
        return _event_sequence_hash(root)
    except (JournalError, OSError, ValueError):
        # A manifest or middle-chain fault has no trustworthy replay sequence;
        # bind the sidecar to the bounded raw file snapshot instead.
        payload = [
            (path.relative_to(root).as_posix(), sha256_hex(path.read_bytes()))
            for path in sorted(root.rglob("*"))
            if path.is_file()
        ]
        return sha256_hex(canonical_json_bytes(payload))


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
    def redact(value: bytes | str) -> str:
        text = value.decode("utf-8", "replace") if isinstance(value, bytes) else value
        # Keep only a bounded diagnostic stream; absolute host paths are not
        # evidence and must never cross the sidecar boundary.
        text = re.sub(r"(?:/(?:[^\s:/]+/)+[^\s:]+)", "<path>", text)
        return text[:4096]

    digest = write_fault_sidecar(
        evidence_root,
        fault_id=fault_id,
        boundary=boundary,
        run_relative_root="run",
        stdout=redact(stdout),
        stderr=redact(stderr),
        file_snapshots=_redacted_snapshot(run_root),
        process_state={"returncode": 0, "signal": None},
        replay_classification=classification,
        reason_code=reason,
        retry_count=retries,
        event_sequence_sha256=event_hash or _evidence_event_hash(run_root),
        canonical_recovery_event_sha256=recovery_hash,
    )
    return {
        "fault_id": fault_id,
        "boundary": boundary,
        "sidecar_sha256": digest,
        "event_sequence_sha256": event_hash or _evidence_event_hash(run_root),
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


def test_phase7_serial_fault_matrix_retains_parent_sidecars_and_verdicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Execute every required class in an independent root, serially."""

    matrix_root = tmp_path / "matrix"
    evidence_root = Path("build/evidence/phase-07/recovery-matrix-cases")
    evidence_root.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    def record(
        fault_id: str,
        boundary: str,
        root: Path,
        classification: str,
        reason: str,
        *,
        retries: int = 0,
        recovery_hash: str | None = None,
        stdout: bytes | str = "",
        stderr: bytes | str = "",
    ) -> None:
        records.append(
            _sidecar(
                evidence_root / fault_id.replace(".", "_"),
                fault_id=fault_id,
                boundary=boundary,
                run_root=root,
                classification=classification,
                reason=reason,
                retries=retries,
                recovery_hash=recovery_hash,
                stdout=stdout,
                stderr=stderr,
            )
        )

    # Hard termination before a canonical write: no event is accepted.
    root = matrix_root / "hard-termination"
    _fresh_run(root)
    request = _transition_request(RUN_ID, event_number=791)
    request_path = tmp_path / "hard-request.json"
    _write_request(request_path, request)
    env = os.environ.copy()
    env.update({"ARW_TEST_MODE": "1", "ARW_TEST_FAULT_ID": "phase7.hard-termination"})
    child = subprocess.run(
        [sys.executable, "-m", "arw.cli", "transition", "--run-root", str(root), "--request", str(request_path)],
        env=env,
        capture_output=True,
        check=False,
    )
    assert child.returncode == -signal.SIGKILL
    assert replay_run(root).revision == 1
    record("phase7.hard-termination", "canonical-write", root, "RECOVERABLE", "process-terminated", stderr=child.stderr)

    # Torn final write is the one repairable tail case and must be explicitly
    # quarantined before the canonical recovery event is published.
    root = matrix_root / "torn-final-write"
    _fresh_run(root)
    request = _transition_request(RUN_ID, event_number=792)
    request_path = tmp_path / "torn-request.json"
    _write_request(request_path, request)
    env["ARW_TEST_FAULT_ID"] = "phase7.torn-final-write"
    child = subprocess.run(
        [sys.executable, "-m", "arw.cli", "transition", "--run-root", str(root), "--request", str(request_path)],
        env=env,
        capture_output=True,
        check=False,
    )
    assert child.returncode == -signal.SIGKILL
    assert replay_run(root).recovery_health == "recoverable_tail"
    recovered = RuntimeCommandService(root).recover(_recovery_request(root, number=793))
    assert recovered.accepted and recovered.event is not None
    assert recovered.state.recovery_health == "healthy"
    record(
        "phase7.torn-final-write",
        "canonical-write",
        root,
        "RECOVERED_TAIL",
        "process-terminated",
        recovery_hash=recovered.event.event_sha256,
        stderr=child.stderr,
    )

    # Middle-chain, event-hash, and manifest corruption are never self-healed.
    root = matrix_root / "middle-chain"
    _fresh_run(root)
    RuntimeCommandService(root).execute_transition(_transition_request(RUN_ID, event_number=794))
    segment = root / "journal/segments/00000001.jsonl"
    raw = segment.read_bytes()
    marker = b'"event_sha256":"'
    offset = raw.index(marker) + len(marker)
    segment.write_bytes(raw[:offset] + b"0" + raw[offset + 1 :])
    try:
        state = replay_run(root)
        assert state.recovery_health == "blocked"
    except JournalError:
        pass
    record("phase7.middle-chain", "canonical-write", root, "BLOCKED", "middle-chain-corruption")

    root = matrix_root / "event-hash"
    _fresh_run(root)
    segment = root / "journal/segments/00000001.jsonl"
    raw = segment.read_bytes()
    marker = b'"event_sha256":"'
    offset = raw.index(marker) + len(marker)
    segment.write_bytes(raw[:offset] + b"0" + raw[offset + 1 :])
    try:
        state = replay_run(root)
        assert state.recovery_health == "blocked"
    except JournalError:
        pass
    record("phase7.event-hash", "journal-fsync", root, "BLOCKED", "hash-mismatch")

    root = matrix_root / "manifest"
    _fresh_run(root)
    manifest = root / "run-manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b"\n")
    with pytest.raises(JournalError):
        replay_run(root)
    record("phase7.manifest", "canonical-write", root, "BLOCKED", "manifest-mismatch")

    # I/O and space failures are parent-visible process errors, never a
    # cancellation result.  Both occur before bytes are written.
    for number, fault_id, reason in (
        (795, "phase7.io-failure", "io-failure"),
        (796, "phase7.disk-exhaustion", "disk-exhaustion"),
    ):
        root = matrix_root / reason
        _fresh_run(root)
        request = _transition_request(RUN_ID, event_number=number)
        request_path = tmp_path / f"{reason}.json"
        _write_request(request_path, request)
        env["ARW_TEST_FAULT_ID"] = fault_id
        child = subprocess.run(
            [sys.executable, "-m", "arw.cli", "transition", "--run-root", str(root), "--request", str(request_path)],
            env=env,
            capture_output=True,
            check=False,
        )
        assert child.returncode != 0
        assert replay_run(root).revision == 1
        record(fault_id, "journal-fsync", root, "RETRYABLE", reason, retries=1, stderr=child.stderr)

    # Duplicate command delivery and stale completion are rejected by the
    # parent revision/identity gate.
    root = matrix_root / "duplicate-delivery"
    _fresh_run(root)
    request = _transition_request(RUN_ID, event_number=797)
    assert RuntimeCommandService(root).execute_transition(request).accepted
    duplicate = RuntimeCommandService(root).execute_transition(request)
    assert not duplicate.accepted and duplicate.rejection is not None
    assert duplicate.rejection.code == "duplicate-event-id"
    record("phase7.duplicate-delivery", "result-acceptance", root, "REJECTED", duplicate.rejection.code)

    root = matrix_root / "stale-worker-completion"
    _fresh_run(root)
    accepted = RuntimeCommandService(root).execute_transition(_transition_request(RUN_ID, event_number=798))
    stale = RuntimeCommandService(root).execute_transition(
        _transition_request(RUN_ID, event_number=799, revision=1)
    )
    assert accepted.accepted and not stale.accepted
    assert stale.rejection is not None and stale.rejection.code == "stale-revision"
    record("phase7.stale-worker-completion", "result-acceptance", root, "REJECTED", stale.rejection.code)

    class _NeverAdapter:
        async def dispatch(self, _spec: DispatchSpec) -> HostResult:
            await asyncio.Event().wait()
            raise AssertionError("unreachable")

        async def request_cancel(self, _spec: DispatchSpec) -> None:
            return None

        async def force_terminate(self, _spec: DispatchSpec) -> None:
            return None

    root = matrix_root / "timeout"
    _fresh_run(root)
    spec = DispatchSpec(
        assignment_id="assignment.phase7-timeout",
        attempt_id="attempt.phase7-timeout.001",
        acceptance_key=(0, 0),
        assignment_path=root / "assignment.json",
        attempt_root=root / "attempt",
        policy_snapshot=ExecutionPolicySnapshot(
            max_concurrency=1, attempt_timeout_s=0.001, cancel_grace_s=0.001
        ),
    )
    outcome = asyncio.run(DeterministicScheduler(_NeverAdapter()).run((spec,)))[0]
    assert outcome.status in {"force_terminated", "interrupted"}
    assert outcome.retry_eligible
    record("phase7.timeout", "host-dispatch", root, "RETRYABLE", "timeout", retries=1)

    class _ResultAdapter:
        async def dispatch(self, spec: DispatchSpec) -> HostResult:
            return HostResult(
                attempt_id=spec.attempt_id,
                host_agent_id="host.phase7",
                proposal_path=spec.attempt_root / "result" / "proposal.json",
            )

        async def request_cancel(self, _spec: DispatchSpec) -> None:
            return None

        async def force_terminate(self, _spec: DispatchSpec) -> None:
            return None

    for suffix, fault_id in (("repairable", "phase7.repairable-proposal"), ("malformed", "phase7.malformed-proposal")):
        root = matrix_root / suffix
        _fresh_run(root)
        spec = DispatchSpec(
            assignment_id=f"assignment.phase7-{suffix}",
            attempt_id=f"attempt.phase7-{suffix}.001",
            acceptance_key=(0, 0),
            assignment_path=root / "assignment.json",
            attempt_root=root / "attempt",
            policy_snapshot=ExecutionPolicySnapshot(max_concurrency=1),
        )

        async def validate(_spec: DispatchSpec, _result: HostResult) -> None:
            raise RepairableEnvelopeFailure(fault_id)

        outcome = asyncio.run(
            DeterministicScheduler(_ResultAdapter(), result_validator=validate).run((spec,))
        )[0]
        assert outcome.status == "failed" and outcome.retry_eligible
        record(fault_id, "result-acceptance", root, "RETRYABLE", "repairable_envelope", retries=1)

    # Restore the parent environment before publishing the aggregate receipt.
    monkeypatch.delenv("ARW_TEST_FAULT_ID", raising=False)
    aggregate = {
        "schema_version": "arw.phase7-recovery-matrix.v1",
        "technical_verdict": "PASS",
        "release_verdict": "BLOCKED_LEGAL_GATE",
        "serial": True,
        "scenario_ids": [item["fault_id"] for item in records],
        "scenarios": records,
    }
    aggregate_path = Path("build/evidence/phase-07/recovery-matrix.json")
    aggregate_path.parent.mkdir(parents=True, exist_ok=True)
    aggregate_path.write_bytes(canonical_json_bytes(aggregate))
    loaded = strict_json_loads(aggregate_path.read_bytes())
    assert loaded["scenario_ids"] == aggregate["scenario_ids"]
    assert len(records) >= 12
    for path in sorted(evidence_root.glob("*/sidecar.json")):
        digest_path = path.with_name("sidecar.sha256")
        assert digest_path.read_text(encoding="ascii").strip() == sha256_hex(path.read_bytes())
        payload = path.read_text(encoding="utf-8")
        assert "/home/" not in payload and "\\\\Users\\\\" not in payload
        assert "api_key" not in payload.lower() and "authorization" not in payload.lower()


@pytest.mark.parametrize(
    ("fault_id", "expected_after_fault", "expected_retry_code"),
    [
        ("phase7.canonical-write-before-commit", 1, 0),
        ("phase7.journal-fsync", 2, 65),
    ],
)
def test_phase7_crash_resume_uses_manifest_ledger_and_rejects_stale_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fault_id: str,
    expected_after_fault: int,
    expected_retry_code: int,
) -> None:
    """Fresh parent processes resume only from canonical manifest + ledger."""

    root = tmp_path / fault_id.rsplit(".", 1)[-1]
    _fresh_run(root)
    request = _transition_request(RUN_ID, event_number=820)
    request_path = tmp_path / "resume-request.json"
    _write_request(request_path, request)
    env = os.environ.copy()
    env.update({"ARW_TEST_MODE": "1", "ARW_TEST_FAULT_ID": fault_id})
    first = subprocess.run(
        [sys.executable, "-m", "arw.cli", "transition", "--run-root", str(root), "--request", str(request_path)],
        env=env,
        capture_output=True,
        check=False,
    )
    assert first.returncode != 0
    assert replay_run(root).revision == expected_after_fault

    # Projections are disposable and cannot make an incomplete command look
    # accepted.  Delete them before the fresh parent resumes.
    projection = root / "projection" / "status.json"
    projection.parent.mkdir()
    projection.write_text('{"status":"tampered"}\n', encoding="utf-8")
    projection.unlink()
    env.pop("ARW_TEST_FAULT_ID", None)
    resumed = subprocess.run(
        [sys.executable, "-m", "arw.cli", "transition", "--run-root", str(root), "--request", str(request_path)],
        env=env,
        capture_output=True,
        check=False,
    )
    assert resumed.returncode == expected_retry_code, resumed.stderr.decode()
    assert replay_run(root).revision == 2

    # A changed revision, duplicate command, or stale worker completion is not
    # admitted after the canonical tip moved.
    stale_request = _transition_request(RUN_ID, event_number=821, revision=1)
    stale_path = tmp_path / "stale-request.json"
    _write_request(stale_path, stale_request)
    stale = subprocess.run(
        [sys.executable, "-m", "arw.cli", "transition", "--run-root", str(root), "--request", str(stale_path)],
        env=env,
        capture_output=True,
        check=False,
    )
    assert stale.returncode == 65  # stale request is a pure rejected outcome
    body = strict_json_loads(stale.stdout)
    assert body["accepted"] is False
    assert body["rejection"]["code"] == "stale-revision"
    assert replay_run(root).revision == 2
    chain_hash = _event_sequence_hash(root)
    assert chain_hash == _event_sequence_hash(root)
