from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest


RUN_ID = "run-00000000-0000-4000-8000-000000000031"


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _service(tmp_path: Path):
    from arw.journal import initialize_run
    from arw.kernel.state.models import InitRunRequest
    from arw.runtime import RuntimeCommandService
    from arw.workflows import CORE_WORKFLOW

    root = tmp_path / "run"
    source = root / "input" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("transition run\n", encoding="utf-8")
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "occurred_at": "2026-07-13T02:00:00Z",
                "immutable_input": {
                    "path": "input/source.txt",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                },
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "workflow_definition_id": CORE_WORKFLOW.definition_id,
                "workflow_definition_sha256": CORE_WORKFLOW.sha256,
                "journal_layout": "segmented-v1",
                "capabilities": ["canonical-journal"],
                "event_id": "evt-00000000-0000-4000-8000-000000000031",
                "command_id": "cmd-00000000-0000-4000-8000-000000000031",
                "actor_id": "parent.runtime",
            }
        ),
    )
    return root, RuntimeCommandService(root)


def _transition(**overrides):
    from arw.kernel.state.models import LifecycleTransitionRequest

    payload = {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "event_id": "evt-00000000-0000-4000-8000-000000000032",
        "command_id": "cmd-00000000-0000-4000-8000-000000000032",
        "expected_revision": 1,
        "occurred_at": "2026-07-13T02:00:01Z",
        "actor_id": "parent.runtime",
        "actor_role": "parent_control_plane",
        "transition_id": "start",
        "from_stage": "initialized",
    }
    payload.update(overrides)
    return LifecycleTransitionRequest.model_validate(payload)


def test_valid_transition_appends_once_and_replays_same_state(tmp_path: Path) -> None:
    from arw.reducer import reduce_events
    from arw.journal import replay_run

    root, service = _service(tmp_path)
    outcome = service.execute_transition(_transition())
    assert outcome.accepted is True
    assert outcome.event is not None
    assert outcome.state.stage == "intake"
    replayed = replay_run(root)
    rebuilt = reduce_events(replayed.workflow_definition_id, replayed.events)
    assert rebuilt == outcome.state
    assert replayed.revision == 2


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"transition_id": "invented"}, "invalid-transition"),
        ({"from_stage": "work"}, "stale-stage"),
        ({"expected_revision": 0}, "stale-revision"),
        ({"actor_role": "operator", "actor_id": "operator.user"}, "unauthorized-actor"),
        ({"actor_role": "worker", "actor_id": "worker.agent"}, "unauthorized-actor"),
        ({"actor_role": "hook", "actor_id": "hook.runtime"}, "unauthorized-actor"),
    ],
)
def test_transition_rejection_matrix_is_byte_side_effect_free(
    tmp_path: Path, overrides: dict[str, object], code: str
) -> None:
    root, service = _service(tmp_path)
    before = _tree(root)
    outcome = service.execute_transition(_transition(**overrides))
    assert outcome.accepted is False
    assert outcome.event is None
    assert outcome.rejection is not None
    assert outcome.rejection.code == code
    assert outcome.rejection.accepted_revision == 1
    assert outcome.rejection.legal_next_transitions == ["start", "abort"]
    assert _tree(root) == before


@pytest.mark.parametrize("identity", ["event", "command"])
def test_duplicate_identity_rejects_without_second_append(tmp_path: Path, identity: str) -> None:
    root, service = _service(tmp_path)
    accepted = service.execute_transition(_transition())
    assert accepted.accepted
    before = _tree(root)
    overrides = {
        "event_id": (
            "evt-00000000-0000-4000-8000-000000000032"
            if identity == "event"
            else "evt-00000000-0000-4000-8000-000000000033"
        ),
        "command_id": (
            "cmd-00000000-0000-4000-8000-000000000033"
            if identity == "event"
            else "cmd-00000000-0000-4000-8000-000000000032"
        ),
        "expected_revision": 2,
        "transition_id": "begin_work",
        "from_stage": "intake",
    }
    rejected = service.execute_transition(_transition(**overrides))
    assert rejected.rejection is not None
    assert rejected.rejection.code == f"duplicate-{identity}-id"
    assert _tree(root) == before


def test_phase2_transaction_rejects_legacy_journal_before_append(tmp_path: Path) -> None:
    from arw.journal import initialize_run
    from arw.kernel.state.models import InitRunRequest
    from arw.runtime import RuntimeCommandService

    root = tmp_path / "legacy"
    source = root / "input" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("legacy run\n", encoding="utf-8")
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "occurred_at": "2026-07-13T02:00:00Z",
                "immutable_input": {
                    "path": "input/source.txt",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                },
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "capabilities": ["canonical-journal"],
                "event_id": "evt-00000000-0000-4000-8000-000000000031",
                "command_id": "cmd-00000000-0000-4000-8000-000000000031",
                "actor_id": "parent.runtime",
            }
        ),
    )
    before = _tree(root)
    rejected = RuntimeCommandService(root).execute_transition(_transition())
    assert rejected.rejection is not None
    assert rejected.rejection.code == "legacy-run-read-only"
    assert _tree(root) == before


def test_transition_cli_routes_only_through_runtime_service(tmp_path: Path) -> None:
    root, _service_instance = _service(tmp_path)
    request_path = tmp_path / "transition.json"
    request_path.write_text(
        json.dumps(_transition().model_dump(mode="json")), encoding="utf-8"
    )
    result = subprocess.run(
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
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["accepted"] is True
    assert payload["state"]["stage"] == "intake"


def test_replay_cli_rejects_resealed_event_that_violates_runtime_authority(
    tmp_path: Path,
) -> None:
    from arw.kernel.core.canonical import canonical_json_bytes, seal_event

    root, service = _service(tmp_path)
    accepted = service.execute_transition(_transition())
    assert accepted.accepted is True

    journal = root / "journal/segments/00000001.jsonl"
    records = [json.loads(line) for line in journal.read_bytes().splitlines()]
    records[-1]["actor_id"] = "worker.agent"
    records[-1]["actor_role"] = "worker"
    records[-1] = seal_event(records[-1])
    journal.write_bytes(b"".join(canonical_json_bytes(record) for record in records))
    before = _tree(root)

    for command in ("replay", "status"):
        arguments = [command, "--run-root", str(root)]
        if command == "status":
            arguments.append("--json")
        result = subprocess.run(
            [sys.executable, "-m", "arw.cli", *arguments],
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        if command == "replay":
            assert payload["revision"] == 1
        else:
            assert payload["accepted_revision"] == 1
            assert payload["recovery_health"] == "blocked"
            assert payload["legal_next_transitions"] == []
        assert _tree(root) == before
