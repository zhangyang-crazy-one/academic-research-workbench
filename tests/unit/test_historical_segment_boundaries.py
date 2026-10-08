"""Fixed prefixes ignore future paths but retain selected-segment safety."""

from __future__ import annotations

from dataclasses import replace

import pytest

from arw.kernel.ledger.accepted_refs import RunPrefix, resolve_ref
from arw.kernel.ledger.journal import JournalError, replay_run, replay_run_prefix
from tests.unit.test_accepted_refs import accepted_fixture


def fixture(tmp_path):
    run, context, ref, _ = accepted_fixture(tmp_path, b'{"value":1}\n')
    replay = replay_run(run)
    fixed = replace(
        context,
        run_prefixes=(
            RunPrefix(
                ref.run_id,
                replay.revision,
                replay.last_event_sha256,
                ref.run_manifest_sha256,
            ),
        ),
    )
    return run, context, ref, replay, fixed


def prefix(root, replay):
    return replay_run_prefix(
        root,
        revision=replay.revision,
        expected_head_sha256=replay.last_event_sha256,
        expected_manifest_sha256=replay.events[0].payload.manifest_sha256,
    )


@pytest.mark.parametrize(
    "kind", ["symlink", "directory", "extra_entry", "future_gap", "undeclared_legacy"]
)
def test_future_paths_do_not_poison_fixed_prefix_but_current_rejects(tmp_path, kind):
    root, current, ref, replay, fixed = fixture(tmp_path)
    storage = root / "journal/segments"
    if kind == "symlink":
        outside = tmp_path / "unrelated.jsonl"
        outside.write_bytes(b"future unrelated bytes\n")
        (storage / "00000002.jsonl").symlink_to(outside)
    elif kind == "directory":
        (storage / "00000002.jsonl").mkdir()
    elif kind == "extra_entry":
        (storage / "not-a-segment").write_bytes(b"future unrelated bytes\n")
    elif kind == "future_gap":
        (storage / "00000003.jsonl").write_bytes(b"future unrelated bytes\n")
    else:
        (root / "events.jsonl").write_bytes(b"future undeclared bytes\n")
    assert prefix(root, replay).events == replay.events
    assert resolve_ref(ref, fixed).status == "resolved"
    with pytest.raises(JournalError):
        replay_run(root)
    assert resolve_ref(ref, current).status == "unresolved"


@pytest.mark.parametrize("kind", ["symlink", "directory", "missing", "gap", "hash"])
def test_required_segment_safety_and_contiguity_remain_strict(tmp_path, kind):
    root, _, _, replay, _ = fixture(tmp_path)
    first = root / replay.segments[0].relative_path
    first_line, second_line = first.read_bytes().splitlines(keepends=True)
    first.write_bytes(first_line)
    second = first.with_name("00000002.jsonl")
    if kind == "symlink":
        outside = tmp_path / "external-selected.jsonl"
        outside.write_bytes(second_line)
        second.symlink_to(outside)
    elif kind == "directory":
        second.mkdir()
    elif kind == "missing":
        pass
    elif kind == "gap":
        first.with_name("00000003.jsonl").write_bytes(second_line)
    else:
        second.write_bytes(second_line.replace(b"parent.runtime", b"parent.invalid"))
    with pytest.raises(JournalError):
        prefix(root, replay)


def test_needed_second_segment_and_same_segment_future_tail(tmp_path):
    root, _, _, replay, _ = fixture(tmp_path)
    first = root / replay.segments[0].relative_path
    first_line, second_line = first.read_bytes().splitlines(keepends=True)
    first.write_bytes(first_line)
    first.with_name("00000002.jsonl").write_bytes(second_line + b"{torn future suffix")
    first.with_name("00000003.jsonl").mkdir()
    assert prefix(root, replay).events == replay.events


def test_prefix_retains_original_recovery_boundary_validation(tmp_path):
    from arw.kernel.execution.runtime import RuntimeCommandService
    from tests.integration.test_recovery import _damage, _initialize, _request

    root = tmp_path / "recovered"
    _initialize(root)
    _, damaged = _damage(root)
    assert RuntimeCommandService(root).recover(_request(damaged)).accepted
    recovered = replay_run(root)
    (root / "journal/segments/00000003.jsonl").mkdir()
    assert prefix(root, recovered).events == recovered.events
    # Earlier damaged bytes remain bound to the original recovery receipt.
    quarantine = root / "quarantine/recovery.tail-001/segment.raw"
    quarantine.write_bytes(quarantine.read_bytes() + b"changed")
    with pytest.raises(JournalError):
        prefix(root, recovered)
