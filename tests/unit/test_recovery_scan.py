from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


RUN_ID = "run-00000000-0000-4000-8000-000000000071"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/recovery/tails"


def _initialize(root: Path):
    from arw.journal import initialize_run
    from arw.models import InitRunRequest
    from arw.workflows import CORE_WORKFLOW

    source = root / "input/source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("recovery scan\n", encoding="utf-8")
    return initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "occurred_at": "2026-07-13T06:00:00Z",
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
                "event_id": "evt-00000000-0000-4000-8000-000000000071",
                "command_id": "cmd-00000000-0000-4000-8000-000000000071",
                "actor_id": "parent.runtime",
            }
        ),
    )


def _append_transition(root: Path, number: int, revision: int, transition: str, stage: str):
    from arw.models import LifecycleTransitionRequest
    from arw.runtime import RuntimeCommandService

    outcome = RuntimeCommandService(root).execute_transition(
        LifecycleTransitionRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "event_id": f"evt-00000000-0000-4000-8000-{number:012x}",
                "command_id": f"cmd-00000000-0000-4000-8000-{number:012x}",
                "expected_revision": revision,
                "occurred_at": f"2026-07-13T06:{number % 60:02d}:00Z",
                "actor_id": "parent.runtime",
                "actor_role": "parent_control_plane",
                "transition_id": transition,
                "from_stage": stage,
            }
        )
    )
    assert outcome.accepted
    return outcome


def _segment(root: Path) -> Path:
    return root / "journal/segments/00000001.jsonl"


@pytest.mark.parametrize(
    ("fixture", "expected_class"),
    [
        ("partial-json.tail", "incomplete-record"),
        ("malformed-record.tail", "malformed-record"),
        ("truncated-utf8.hex", "truncated-utf8"),
    ],
)
def test_only_terminal_unverifiable_suffix_is_recoverable(
    tmp_path: Path, fixture: str, expected_class: str
) -> None:
    from arw.journal import replay_run

    root = tmp_path / fixture
    initialized = _initialize(root)
    path = _segment(root)
    valid = path.read_bytes()
    tail = (
        bytes.fromhex((FIXTURES / fixture).read_text(encoding="ascii").strip())
        if fixture.endswith(".hex")
        else (FIXTURES / fixture).read_bytes()
    )
    path.write_bytes(valid + tail)
    before = path.read_bytes()

    state = replay_run(root)

    assert state.recovery_health == "recoverable_tail"
    assert state.revision == initialized.revision == 1
    assert state.last_event_sha256 == initialized.last_event_sha256
    assert state.segments[-1].accepted_byte_end == len(valid)
    assert state.segments[-1].fault_offset == len(valid)
    assert state.segments[-1].fault_class == expected_class
    assert state.segments[-1].raw_tail == tail
    assert path.read_bytes() == before


def test_changed_accepted_final_event_is_blocked(tmp_path: Path) -> None:
    from arw.canonical import canonical_json_bytes, strict_json_loads
    from arw.journal import replay_run

    root = tmp_path / "changed-final"
    _initialize(root)
    _append_transition(root, 72, 1, "start", "initialized")
    path = _segment(root)
    lines = path.read_bytes().splitlines(keepends=True)
    changed = strict_json_loads(lines[-1])
    changed["payload"]["to_stage"] = "review"
    path.write_bytes(lines[0] + canonical_json_bytes(changed))

    state = replay_run(root)

    assert state.recovery_health == "blocked"
    assert state.revision == 1
    assert state.segments[-1].fault_class == "event-integrity"


@pytest.mark.parametrize("defect", ["changed-middle", "deleted", "reordered", "later-valid"])
def test_middle_or_later_chain_damage_is_blocked(tmp_path: Path, defect: str) -> None:
    from arw.canonical import canonical_json_bytes, strict_json_loads
    from arw.journal import replay_run

    root = tmp_path / defect
    _initialize(root)
    _append_transition(root, 73, 1, "start", "initialized")
    _append_transition(root, 74, 2, "begin_work", "intake")
    path = _segment(root)
    lines = path.read_bytes().splitlines(keepends=True)
    if defect == "changed-middle":
        changed = strict_json_loads(lines[1])
        changed["payload"]["to_stage"] = "review"
        value = lines[0] + canonical_json_bytes(changed) + lines[2]
    elif defect == "deleted":
        value = lines[0] + lines[2]
    elif defect == "reordered":
        value = lines[0] + lines[2] + lines[1]
    else:
        value = lines[0] + (FIXTURES / "malformed-record.tail").read_bytes() + lines[1]
    path.write_bytes(value)

    state = replay_run(root)

    assert state.recovery_health == "blocked"
    assert state.revision == 1


def test_changed_run_manifest_has_no_trustworthy_prefix(tmp_path: Path) -> None:
    from arw.canonical import canonical_json_bytes, strict_json_loads
    from arw.journal import JournalError, replay_run

    root = tmp_path / "manifest"
    _initialize(root)
    manifest_path = root / "run-manifest.json"
    manifest = strict_json_loads(manifest_path.read_bytes())
    manifest["created_at"] = "2026-07-13T06:00:01Z"
    manifest_path.write_bytes(canonical_json_bytes(manifest))

    with pytest.raises(JournalError, match="trustworthy prefix|manifest"):
        replay_run(root)


def test_unbound_next_segment_after_damaged_tail_is_blocked(tmp_path: Path) -> None:
    from arw.journal import replay_run

    root = tmp_path / "unexpected-next"
    _initialize(root)
    first = _segment(root)
    first.write_bytes(first.read_bytes() + b'{"partial":')
    (first.parent / "00000002.jsonl").write_bytes(b"not-a-recovery\n")

    state = replay_run(root)

    assert state.recovery_health == "blocked"
    assert state.revision == 1

