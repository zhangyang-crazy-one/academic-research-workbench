from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


RUN_ID = "run-00000000-0000-4000-8000-000000000081"


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _initialize(root: Path):
    from arw.kernel.ledger.journal import initialize_run
    from arw.kernel.state.models import InitRunRequest
    from arw.kernel.ledger.workflows import CORE_WORKFLOW

    source = root / "input/source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("explicit recovery\n", encoding="utf-8")
    return initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "occurred_at": "2026-07-13T07:00:00Z",
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
                "event_id": "evt-00000000-0000-4000-8000-000000000081",
                "command_id": "cmd-00000000-0000-4000-8000-000000000081",
                "actor_id": "parent.runtime",
            }
        ),
    )


def _damage(root: Path) -> tuple[bytes, object]:
    from arw.kernel.ledger.journal import replay_run

    segment = root / "journal/segments/00000001.jsonl"
    segment.write_bytes(segment.read_bytes() + b'{"event_type":"lifecycle')
    damaged = segment.read_bytes()
    return damaged, replay_run(root)


def _request(state, *, number: int = 82):
    from arw.kernel.state.models import RecoveryRequest

    segment = state.segments[-1]
    return RecoveryRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "event_id": f"evt-00000000-0000-4000-8000-{number:012x}",
            "command_id": f"cmd-00000000-0000-4000-8000-{number:012x}",
            "expected_revision": state.revision,
            "expected_head_sha256": state.last_event_sha256,
            "occurred_at": "2026-07-13T07:10:00Z",
            "actor_id": "operator.user",
            "actor_role": "operator",
            "recovery_id": "recovery.tail-001",
            "original_segment_sha256": segment.sha256,
            "reason_code": "process-terminated",
            "reason_text": "process terminated during a canonical append",
        }
    )


def test_explicit_recovery_preserves_and_binds_exact_tail(tmp_path: Path) -> None:
    from arw.kernel.core.canonical import sha256_hex, strict_json_loads
    from arw.kernel.ledger.journal import replay_run
    from arw.kernel.ledger.recovery import load_recovery_receipt
    from arw.runtime import RuntimeCommandService
    from arw.kernel.policy.schema_registry import validate_instance

    root = tmp_path / "run"
    initialized = _initialize(root)
    damaged, degraded = _damage(root)
    assert degraded.recovery_health == "recoverable_tail"
    request = _request(degraded)
    validate_instance(
        "recovery-request.schema.json",
        request.model_dump(mode="json"),
    )

    outcome = RuntimeCommandService(root).recover(request)

    assert outcome.accepted
    assert outcome.event.event_type == "recovery.completed"
    assert outcome.state.recovery_health == "healthy"
    assert outcome.state.accepted_revision == initialized.revision + 1
    original = root / "journal/segments/00000001.jsonl"
    raw = root / "quarantine/recovery.tail-001/segment.raw"
    assert original.read_bytes() == raw.read_bytes() == damaged
    receipt = load_recovery_receipt(root, "recovery.tail-001")
    validate_instance(
        "recovery-receipt.schema.json",
        receipt.model_dump(mode="json"),
    )
    assert receipt.original_segment_sha256 == sha256_hex(damaged)
    assert receipt.quarantine_raw_sha256 == sha256_hex(raw.read_bytes())
    assert receipt.fault_offset == degraded.segments[-1].fault_offset
    second = root / "journal/segments/00000002.jsonl"
    event = strict_json_loads(second.read_bytes())
    validate_instance("event.schema.json", event)
    assert event["event_type"] == "recovery.completed"
    assert event["prev_event_sha256"] == initialized.last_event_sha256
    assert event["payload"]["quarantine_receipt_sha256"] == sha256_hex(
        (root / "quarantine/recovery.tail-001/receipt.json").read_bytes()
    )
    replayed = replay_run(root)
    assert replayed.recovery_health == "healthy"
    assert replayed.revision == 2

    before_retry = _tree(root)
    duplicate = RuntimeCommandService(root).recover(request)
    assert duplicate.accepted
    assert _tree(root) == before_retry


def test_conflicting_orphan_evidence_rejects_without_writing_raw_copy(
    tmp_path: Path,
) -> None:
    from arw.runtime import RuntimeCommandService

    root = tmp_path / "orphan-conflict"
    _initialize(root)
    _, degraded = _damage(root)
    bundle = root / "quarantine/recovery.tail-001"
    bundle.mkdir(parents=True)
    (bundle / "receipt.json").write_bytes(b"conflicting receipt\n")
    before = _tree(root)

    rejected = RuntimeCommandService(root).recover(_request(degraded))

    assert not rejected.accepted
    assert rejected.rejection.code == "recovery-failed"
    assert _tree(root) == before


def test_recovery_boundary_supports_standard_checkpoint_and_continuation(
    tmp_path: Path,
) -> None:
    from arw.kernel.state.models import CheckpointRequest, LifecycleTransitionRequest
    from arw.runtime import RuntimeCommandService

    root = tmp_path / "checkpoint"
    _initialize(root)
    _, degraded = _damage(root)
    service = RuntimeCommandService(root)
    recovered = service.recover(_request(degraded))
    assert recovered.accepted
    checkpoint = service.create_checkpoint(
        CheckpointRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "event_id": "evt-00000000-0000-4000-8000-000000000083",
                "command_id": "cmd-00000000-0000-4000-8000-000000000083",
                "expected_revision": 2,
                "occurred_at": "2026-07-13T07:11:00Z",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
                "checkpoint_kind": "recovery",
                "fresh_until": None,
            }
        )
    )
    assert checkpoint.accepted
    transitioned = service.execute_transition(
        LifecycleTransitionRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "event_id": "evt-00000000-0000-4000-8000-000000000084",
                "command_id": "cmd-00000000-0000-4000-8000-000000000084",
                "expected_revision": 3,
                "occurred_at": "2026-07-13T07:12:00Z",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
                "transition_id": "start",
                "from_stage": "initialized",
            }
        )
    )
    assert transitioned.accepted
    assert transitioned.state.accepted_revision == 4
    assert transitioned.state.stage == "intake"


@pytest.mark.parametrize("tamper", ["original", "raw", "receipt", "event"])
def test_recovered_run_blocks_changed_binding_evidence(tmp_path: Path, tamper: str) -> None:
    from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads
    from arw.kernel.ledger.journal import replay_run
    from arw.runtime import RuntimeCommandService

    root = tmp_path / tamper
    _initialize(root)
    _, degraded = _damage(root)
    assert RuntimeCommandService(root).recover(_request(degraded)).accepted
    if tamper == "original":
        path = root / "journal/segments/00000001.jsonl"
        path.write_bytes(path.read_bytes() + b"x")
    elif tamper == "raw":
        path = root / "quarantine/recovery.tail-001/segment.raw"
        path.write_bytes(path.read_bytes() + b"x")
    elif tamper == "receipt":
        path = root / "quarantine/recovery.tail-001/receipt.json"
        receipt = strict_json_loads(path.read_bytes())
        receipt["reason_text"] = "changed forensic reason"
        path.write_bytes(canonical_json_bytes(receipt))
    else:
        path = root / "journal/segments/00000002.jsonl"
        event = strict_json_loads(path.read_bytes())
        event["payload"]["fault_offset"] += 1
        path.write_bytes(canonical_json_bytes(event))

    state = replay_run(root)

    assert state.recovery_health == "blocked"
    assert state.revision == 1


def test_recoverable_and_blocked_status_are_read_only_and_exit_zero(tmp_path: Path) -> None:
    root = tmp_path / "status"
    _initialize(root)
    _, degraded = _damage(root)
    before = _tree(root)
    recoverable = subprocess.run(
        [sys.executable, "-m", "arw.cli", "status", "--json", "--run-root", str(root)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert recoverable.returncode == 0, recoverable.stderr
    payload = json.loads(recoverable.stdout)
    assert payload["recovery_health"] == "recoverable_tail"
    assert payload["accepted_revision"] == degraded.revision
    assert payload["legal_next_transitions"] == ["recover"]
    assert _tree(root) == before

    (root / "journal/segments/00000002.jsonl").write_bytes(b"unexpected\n")
    blocked_before = _tree(root)
    blocked = subprocess.run(
        [sys.executable, "-m", "arw.cli", "status", "--json", "--run-root", str(root)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert blocked.returncode == 0, blocked.stderr
    assert json.loads(blocked.stdout)["recovery_health"] == "blocked"
    assert _tree(root) == blocked_before
