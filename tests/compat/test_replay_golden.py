"""v2 compatibility baseline: golden replay fixtures.

Pins the digest of replayed canonical state for two event streams (the
recovery seed and a full nine-event lifecycle), plus rejection payloads for
duplicate command, stale revision, and stale attempt base. The pinned digest
is the SHA-256 of the reduced state's canonical bytes — serializer cosmetics
may change in v2, canonical bytes may not.

All CLI invocations cross the public entry point (`python -m arw.cli` in a
subprocess); in-process calls would keep passing even if module execution or
exit propagation broke. Rejection fixtures are constructed so the intended
check is what actually fires: the duplicate-command request carries the
current revision and a fresh event id; the stale-revision request is
schema-valid with an outdated revision; the stale-attempt request runs on a
segmented-layout run with an outdated base revision.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from arw.kernel.core.canonical import canonical_json_bytes, sha256_hex
from arw.kernel.ledger.journal import replay_run
from arw.kernel.ledger.reducer import reduce_events
from arw.kernel.ledger.workflows import CORE_WORKFLOW

from .normalize import normalize_text, path_replacements, read_golden_json

pytestmark = pytest.mark.v2_compat

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEED = REPOSITORY_ROOT / "tests" / "fixtures" / "recovery" / "seed"
GOLDEN_DIR = Path(__file__).parent / "golden" / "replay"


def _run_cli(argv: list[str]) -> dict[str, object]:
    """Run through the public entry point: python -m arw.cli (subprocess)."""
    completed = subprocess.run(
        [sys.executable, "-m", "arw.cli", *argv],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _seed_run_root(tmp_path: Path) -> Path:
    run_root = tmp_path / "run"
    (run_root / "input").mkdir(parents=True)
    shutil.copyfile(SEED / "input" / "source.txt", run_root / "input" / "source.txt")
    return run_root


def _init_and_append(run_root: Path) -> None:
    init = _run_cli(
        ["init", "--run-root", str(run_root), "--request", str(SEED / "init-request.json")]
    )
    assert init["exit_code"] == 0, init["stderr"]
    append = _run_cli(
        ["append", "--run-root", str(run_root), "--request", str(SEED / "append-request.json")]
    )
    assert append["exit_code"] == 0, append["stderr"]


def _replay_state_digest(run_root: Path) -> str:
    replayed = replay_run(run_root)
    state = reduce_events(
        replayed.workflow_definition_id,
        replayed.events,
        recovery_health=replayed.recovery_health,
    )
    return sha256_hex(canonical_json_bytes(state.model_dump(mode="json")))


def _assert_rejection_golden(
    name: str,
    result: dict[str, object],
    tmp_path: Path,
    run_root: Path,
) -> None:
    golden = read_golden_json(GOLDEN_DIR / name)
    actual = {
        "exit_code": result["exit_code"],
        "stdout": result["stdout"],
        "stderr": normalize_text(
            str(result["stderr"]),
            replacements=path_replacements(run_root=run_root, tmp_path=tmp_path),
        ),
    }
    assert actual == golden


def test_replay_digest_matches_golden(tmp_path: Path) -> None:
    run_root = _seed_run_root(tmp_path)
    _init_and_append(run_root)

    replayed = replay_run(run_root)
    state = reduce_events(
        replayed.workflow_definition_id,
        replayed.events,
        recovery_health=replayed.recovery_health,
    )
    digest = sha256_hex(canonical_json_bytes(state.model_dump(mode="json")))
    golden = read_golden_json(GOLDEN_DIR / "replay_digest.json")
    # Compare LIVE replay metadata to the golden (not to hard-coded literals),
    # so a silently dropped or injected no-op event fails this gate.
    assert len(replayed.events) == golden["event_count"]
    assert replayed.revision == golden["revision"]
    assert replayed.run_id == golden["run_id"]
    assert digest == golden["state_sha256"], (
        "replayed state digest drifted; v2 must not change canonical reduction"
    )


def test_replay_digest_is_repeat_stable(tmp_path: Path) -> None:
    digests = set()
    for index in range(3):
        run_root = _seed_run_root(tmp_path / f"pass{index}")
        _init_and_append(run_root)
        digests.add(_replay_state_digest(run_root))
    assert len(digests) == 1


def test_duplicate_command_rejection_matches_golden(tmp_path: Path) -> None:
    run_root = _seed_run_root(tmp_path)
    _init_and_append(run_root)
    journal_before = (run_root / "events.jsonl").read_bytes()

    # Current revision is 2. Reuse the ACCEPTED command_id with a fresh
    # event_id and the correct expected_revision, so the duplicate-command
    # check is what fires — not stale revision, not duplicate event id.
    duplicate_request = dict(read_golden_json(SEED / "append-request.json"))
    duplicate_request["expected_revision"] = 2
    duplicate_request["event_id"] = "evt-00000000-0000-4000-8000-000000000099"
    request_path = tmp_path / "duplicate-request.json"
    request_path.write_bytes(canonical_json_bytes(duplicate_request) + b"\n")

    result = _run_cli(["append", "--run-root", str(run_root), "--request", str(request_path)])
    _assert_rejection_golden("duplicate_rejection.json", result, tmp_path, run_root)
    stderr = normalize_text(str(result["stderr"]))
    assert "duplicate" in stderr.lower() or "already" in stderr.lower(), (
        "rejection must name the duplicate command, not another check"
    )
    assert (run_root / "events.jsonl").read_bytes() == journal_before, (
        "rejected duplicate command must not mutate the journal"
    )


def test_stale_revision_rejection_matches_golden(tmp_path: Path) -> None:
    run_root = _seed_run_root(tmp_path)
    _init_and_append(run_root)
    journal_before = (run_root / "events.jsonl").read_bytes()

    # Schema-valid but outdated: revision 1 was current after init, but append
    # already advanced the run to revision 2.
    stale_request = dict(read_golden_json(SEED / "append-request.json"))
    stale_request["expected_revision"] = 1
    stale_request["command_id"] = "cmd-00000000-0000-4000-8000-000000000003"
    stale_request["event_id"] = "evt-00000000-0000-4000-8000-000000000003"
    request_path = tmp_path / "stale-request.json"
    request_path.write_bytes(canonical_json_bytes(stale_request) + b"\n")

    result = _run_cli(["append", "--run-root", str(run_root), "--request", str(request_path)])
    _assert_rejection_golden("stale_revision_rejection.json", result, tmp_path, run_root)
    stderr = normalize_text(str(result["stderr"]))
    assert "stale" in stderr.lower() or "revision" in stderr.lower(), (
        "rejection must name the stale revision, not another check"
    )
    assert (run_root / "events.jsonl").read_bytes() == journal_before, (
        "rejected stale-revision command must not mutate the journal"
    )


# --- Full lifecycle stream: the two-event seed stream cannot catch
# regressions in transition/checkpoint/resume reduction ---

LIFECYCLE_RUN_ID = "run-00000000-0000-4000-8000-000000000201"


def _lifecycle_base(
    number: int, revision: int, occurred_at: str, *, role: str = "parent_control_plane"
) -> dict:
    return {
        "schema_version": "1.0.0",
        "run_id": LIFECYCLE_RUN_ID,
        "event_id": f"evt-00000000-0000-4000-8000-{number:012x}",
        "command_id": f"cmd-00000000-0000-4000-8000-{number:012x}",
        "expected_revision": revision,
        "occurred_at": occurred_at,
        "actor_id": "operator.user" if role == "operator" else "parent.runtime",
        "actor_role": role,
    }


def _write_request(tmp_path: Path, label: str, payload: dict) -> Path:
    path = tmp_path / "requests" / f"{label}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(payload) + b"\n")
    return path


def _run_command(
    run_root: Path, request: Path, command: str, transcripts: dict[str, object]
) -> None:
    """Run one lifecycle command through the public CLI entry point.

    stdout and stderr are recorded under the request label so the golden
    transcript pins each command's success envelope, not just its exit code.
    """
    result = _run_cli([command, "--run-root", str(run_root), "--request", str(request)])
    assert result["exit_code"] == 0, f"{command} rejected a valid lifecycle request"
    transcripts[request.stem] = {
        "command": command,
        "stdout": result["stdout"],
        "stderr": result["stderr"],
    }


def _lifecycle_stream(tmp_path: Path, transcripts: dict[str, object]) -> Path:
    """init -> transition -> decision -> attempt -> artifact -> checkpoint ->
    resume, fully deterministic (fixed ids/timestamps)."""
    run_root = tmp_path / "lifecycle-run"
    source = run_root / "input" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("domain-neutral research input\n", encoding="utf-8")
    source_digest = sha256_hex(source.read_bytes())

    init_request = {
        "schema_version": "1.0.0",
        "run_id": LIFECYCLE_RUN_ID,
        "occurred_at": "2026-07-13T09:00:00Z",
        "immutable_input": {"path": "input/source.txt", "sha256": source_digest},
        "workflow_family": "academic-pipeline",
        "workflow_mode": "inline-role-prompts",
        "workflow_definition_id": CORE_WORKFLOW.definition_id,
        "workflow_definition_sha256": CORE_WORKFLOW.sha256,
        "journal_layout": "segmented-v1",
        "capabilities": ["canonical-journal", "forced-stop-replay"],
        "event_id": "evt-00000000-0000-4000-8000-000000000201",
        "command_id": "cmd-00000000-0000-4000-8000-000000000201",
        "actor_id": "parent.runtime",
    }
    _run_command(run_root, _write_request(tmp_path, "01-init", init_request), "init", transcripts)

    _run_command(
        run_root,
        _write_request(tmp_path, "02-start", {
            **_lifecycle_base(0x202, 1, "2026-07-13T09:04:00Z"),
            "transition_id": "start",
            "from_stage": "initialized",
        }),
        "transition",
        transcripts,
    )
    _run_command(
        run_root,
        _write_request(tmp_path, "03-decision-request", {
            **_lifecycle_base(0x203, 2, "2026-07-13T09:05:00Z"),
            "decision_id": "decision.route",
            "blocker_code": "human-choice-required",
            "allowed_choices": ["continue", "abort"],
            "rationale_required": True,
            "source_event_ids": [],
            "unlock_transitions": ["begin_work"],
        }),
        "decision-request",
        transcripts,
    )
    # attempt-start consumes the ledger head left by decision-request.
    replayed = replay_run(run_root)
    head = replayed.last_event_sha256
    _run_command(
        run_root,
        _write_request(tmp_path, "04-attempt-start", {
            **_lifecycle_base(0x204, 3, "2026-07-13T09:06:00Z"),
            "attempt_id": "attempt.writer-001",
            "base_revision": 3,
            "consumed_sha256": [head],
        }),
        "attempt-start",
        transcripts,
    )
    artifact = run_root / "outputs" / "result.txt"
    artifact.parent.mkdir()
    artifact.write_text("accepted result\n", encoding="utf-8")
    artifact_digest = sha256_hex(artifact.read_bytes())
    _run_command(
        run_root,
        _write_request(tmp_path, "05-artifact-accept", {
            **_lifecycle_base(0x205, 4, "2026-07-13T09:07:00Z"),
            "artifact_id": "artifact.result-001",
            "artifact_kind": "result",
            "media_type": "text/plain",
            "content_path": "outputs/result.txt",
            "content_sha256": artifact_digest,
            "attempt_id": "attempt.writer-001",
            "base_revision": 3,
            "consumed_sha256": [head],
        }),
        "artifact-accept",
        transcripts,
    )
    _run_command(
        run_root,
        _write_request(tmp_path, "06-attempt-close", {
            **_lifecycle_base(0x206, 5, "2026-07-13T09:08:00Z"),
            "attempt_id": "attempt.writer-001",
            "outcome": "completed",
            "proposal_sha256": artifact_digest,
        }),
        "attempt-close",
        transcripts,
    )
    _run_command(
        run_root,
        _write_request(tmp_path, "07-decision-resolve", {
            **_lifecycle_base(0x207, 6, "2026-07-13T09:09:00Z"),
            "decision_id": "decision.route",
            "choice": "continue",
            "rationale": "continue with accepted evidence",
        }),
        "decision-resolve",
        transcripts,
    )
    _run_command(
        run_root,
        _write_request(tmp_path, "08-checkpoint", {
            **_lifecycle_base(0x208, 7, "2026-07-13T09:10:00Z"),
            "checkpoint_kind": "human_decision",
            "fresh_until": "2026-07-13T09:30:00Z",
        }),
        "checkpoint",
        transcripts,
    )
    replayed = replay_run(run_root)
    passport = reduce_events(
        replayed.workflow_definition_id,
        replayed.events,
        recovery_health=replayed.recovery_health,
    ).current_passport_sha256
    assert passport is not None
    _run_command(
        run_root,
        _write_request(tmp_path, "09-resume", {
            **_lifecycle_base(0x209, 8, "2026-07-13T09:20:00Z", role="operator"),
            "passport_sha256": passport,
        }),
        "resume",
        transcripts,
    )
    return run_root


def test_full_lifecycle_replay_digest_matches_golden(tmp_path: Path) -> None:
    transcripts: dict[str, object] = {}
    run_root = _lifecycle_stream(tmp_path, transcripts)
    replayed = replay_run(run_root)
    state = reduce_events(
        replayed.workflow_definition_id,
        replayed.events,
        recovery_health=replayed.recovery_health,
    )
    digest = sha256_hex(canonical_json_bytes(state.model_dump(mode="json")))

    golden = read_golden_json(GOLDEN_DIR / "lifecycle_replay_digest.json")
    assert len(replayed.events) == golden["event_count"]
    assert state.accepted_revision == golden["accepted_revision"]
    assert state.stage == golden["stage"]
    assert digest == golden["state_sha256"], (
        "full-lifecycle replay digest drifted; v2 must not change transition, "
        "checkpoint, or resume reduction"
    )

    # Success envelopes of every lifecycle command are pinned, not just exit 0.
    # JSON output compares structurally (key order/whitespace are cosmetic);
    # non-JSON text compares exactly.
    transcript_golden = read_golden_json(GOLDEN_DIR / "lifecycle_transcripts.json")
    assert transcripts.keys() == transcript_golden.keys()
    for label, actual_entry in transcripts.items():
        expected_entry = transcript_golden[label]
        assert actual_entry["command"] == expected_entry["command"]
        for channel in ("stdout", "stderr"):
            actual_text = str(actual_entry[channel])
            expected_text = str(expected_entry[channel])
            try:
                assert json.loads(actual_text) == json.loads(expected_text), label
            except ValueError:
                assert actual_text == expected_text, label


def test_full_lifecycle_replay_is_repeat_stable(tmp_path: Path) -> None:
    digests = set()
    for index in range(2):
        run_root = _lifecycle_stream(tmp_path / f"pass{index}", {})
        digests.add(_replay_state_digest(run_root))
    assert len(digests) == 1


def test_stale_attempt_base_rejection_matches_golden(tmp_path: Path) -> None:
    """Stale-result family: attempt-start based on an outdated revision is
    rejected with the pinned stale-attempt-base envelope (I1/I2).

    Runtime-command rejections are structured JSON on stdout (exit 65); the
    run must use the segmented journal layout (legacy layouts are read-only
    for Phase 2 mutations).
    """
    run_root = tmp_path / "run"
    source = run_root / "input" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("domain-neutral research input\n", encoding="utf-8")

    init_request = {
        "schema_version": "1.0.0",
        "run_id": LIFECYCLE_RUN_ID,
        "occurred_at": "2026-07-13T09:00:00Z",
        "immutable_input": {
            "path": "input/source.txt",
            "sha256": sha256_hex(source.read_bytes()),
        },
        "workflow_family": "academic-pipeline",
        "workflow_mode": "inline-role-prompts",
        "workflow_definition_id": CORE_WORKFLOW.definition_id,
        "workflow_definition_sha256": CORE_WORKFLOW.sha256,
        "journal_layout": "segmented-v1",
        "capabilities": ["canonical-journal", "forced-stop-replay"],
        "event_id": "evt-00000000-0000-4000-8000-000000000201",
        "command_id": "cmd-00000000-0000-4000-8000-000000000201",
        "actor_id": "parent.runtime",
    }
    init_path = _write_request(tmp_path, "seg-init", init_request)
    init = _run_cli(["init", "--run-root", str(run_root), "--request", str(init_path)])
    assert init["exit_code"] == 0, init["stderr"]

    start_request = {
        **_lifecycle_base(0x202, 1, "2026-07-13T09:01:00Z"),
        "transition_id": "start",
        "from_stage": "initialized",
    }
    start_path = _write_request(tmp_path, "seg-start", start_request)
    start = _run_cli(["transition", "--run-root", str(run_root), "--request", str(start_path)])
    assert start["exit_code"] == 0, start["stderr"]
    segments_before = {
        path.name: path.read_bytes() for path in (run_root / "journal" / "segments").glob("*.jsonl")
    }

    stale_attempt = {
        **_lifecycle_base(0x203, 2, "2026-07-13T09:02:00Z"),
        "attempt_id": "attempt.stale-001",
        "base_revision": 1,  # current revision is 2: stale base
        "consumed_sha256": [],
    }
    request_path = _write_request(tmp_path, "seg-stale-attempt", stale_attempt)

    result = _run_cli(
        ["attempt-start", "--run-root", str(run_root), "--request", str(request_path)]
    )
    _assert_rejection_golden("stale_attempt_rejection.json", result, tmp_path, run_root)
    # The structured rejection envelope on stdout must name the stale base.
    assert "stale-attempt-base" in str(result["stdout"]), (
        f"rejection must name the stale attempt base: {str(result['stdout'])[:300]}"
    )
    segments_after = {
        path.name: path.read_bytes() for path in (run_root / "journal" / "segments").glob("*.jsonl")
    }
    assert segments_after == segments_before, "rejected attempt must not mutate the journal"
