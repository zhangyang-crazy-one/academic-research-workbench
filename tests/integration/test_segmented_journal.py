from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


RUN_ID = "run-00000000-0000-4000-8000-000000000021"


def _request(root: Path):
    from arw.kernel.state.models import InitRunRequest
    from arw.workflows import CORE_WORKFLOW

    source = root / "input" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("segmented run\n", encoding="utf-8")
    return InitRunRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "occurred_at": "2026-07-13T01:00:00Z",
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
            "event_id": "evt-00000000-0000-4000-8000-000000000021",
            "command_id": "cmd-00000000-0000-4000-8000-000000000021",
            "actor_id": "parent.runtime",
        }
    )


def _initialize(root: Path):
    from arw.journal import initialize_run

    return initialize_run(root, _request(root))


def test_new_run_uses_declared_segment_layout_and_replays_locations(tmp_path: Path) -> None:
    from arw.journal import replay_run

    root = tmp_path / "run"
    initialized = _initialize(root)
    segment = root / "journal" / "segments" / "00000001.jsonl"
    assert segment.is_file()
    assert not (root / "events.jsonl").exists()
    replayed = replay_run(root)
    assert replayed.revision == initialized.revision == 1
    assert [item.name for item in replayed.segments] == ["00000001.jsonl"]
    assert replayed.segments[0].byte_count == len(segment.read_bytes())
    assert replayed.segments[0].accepted_byte_end == len(segment.read_bytes())
    assert replayed.segments[0].sha256 == hashlib.sha256(segment.read_bytes()).hexdigest()


@pytest.mark.parametrize("defect", ["gap", "unexpected", "symlink"])
def test_segment_discovery_fails_closed(tmp_path: Path, defect: str) -> None:
    from arw.journal import JournalError, replay_run

    root = tmp_path / defect
    _initialize(root)
    segments = root / "journal" / "segments"
    first = segments / "00000001.jsonl"
    if defect == "gap":
        first.rename(segments / "00000002.jsonl")
    elif defect == "unexpected":
        (segments / "notes.txt").write_text("not canonical\n", encoding="utf-8")
    else:
        (segments / "00000002.jsonl").symlink_to(first)
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    with pytest.raises(JournalError):
        replay_run(root)
    after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
    assert after == before


def test_replay_continues_chain_across_ordered_segments(tmp_path: Path) -> None:
    from arw.kernel.core.canonical import canonical_json_bytes, seal_event
    from arw.journal import replay_run

    root = tmp_path / "ordered"
    first_state = _initialize(root)
    unsigned = {
        "schema_version": "1.0.0",
        "event_type": "lifecycle.transitioned",
        "event_id": "evt-00000000-0000-4000-8000-000000000022",
        "command_id": "cmd-00000000-0000-4000-8000-000000000022",
        "run_id": RUN_ID,
        "sequence": 2,
        "occurred_at": "2026-07-13T01:00:01Z",
        "expected_revision": 1,
        "resulting_revision": 2,
        "actor_id": "parent.runtime",
        "actor_role": "parent_control_plane",
        "prev_event_sha256": first_state.last_event_sha256,
        "payload": {"transition_id": "start", "from_stage": "initialized", "to_stage": "intake"},
    }
    second = root / "journal" / "segments" / "00000002.jsonl"
    second.write_bytes(canonical_json_bytes(seal_event(unsigned)))
    replayed = replay_run(root)
    assert replayed.revision == 2
    assert replayed.event_count == 2
    assert [item.name for item in replayed.segments] == [
        "00000001.jsonl",
        "00000002.jsonl",
    ]


def test_legacy_append_cannot_bypass_segmented_runtime_authority(tmp_path: Path) -> None:
    from arw.journal import JournalError, append_probe
    from arw.kernel.state.models import AppendProbeRequest

    root = tmp_path / "segmented-append"
    _initialize(root)
    before = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    request = AppendProbeRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "event_type": "baseline.probe_recorded",
            "event_id": "evt-00000000-0000-4000-8000-000000000023",
            "command_id": "cmd-00000000-0000-4000-8000-000000000023",
            "run_id": RUN_ID,
            "occurred_at": "2026-07-13T01:00:02Z",
            "expected_revision": 1,
            "actor_id": "legacy.caller",
            "payload": {
                "probe_id": "probe-segmented-bypass",
                "status": "pass",
                "summary": "must not append",
            },
        }
    )

    with pytest.raises(JournalError, match="only supports legacy"):
        append_probe(root, request)
    after = {
        path.relative_to(root): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_writer_lock_symlink_is_rejected_without_touching_target(tmp_path: Path) -> None:
    from arw.journal import JournalError, initialize_run

    root = tmp_path / "lock-symlink"
    root.mkdir()
    outside = tmp_path / "outside-lock"
    outside.write_bytes(b"outside must remain unchanged\n")
    (root / ".journal.lock").symlink_to(outside)
    request = _request(root)
    before = outside.read_bytes()

    with pytest.raises(JournalError, match="lock file is unsafe"):
        initialize_run(root, request)

    assert outside.read_bytes() == before
    assert not (root / "run-manifest.json").exists()
    assert not (root / "journal").exists()
