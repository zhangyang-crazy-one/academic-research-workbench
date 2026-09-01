from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_NAME = "academic-research-workbench"
RUN_ID = "run-00000000-0000-4000-8000-000000000201"


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _inventory(root: Path) -> dict[str, dict[str, object]]:
    return {
        path.relative_to(root).as_posix(): {
            "sha256": _sha256(path.read_bytes()),
            "size": path.stat().st_size,
        }
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class StagedHarness:
    def __init__(self, tmp_path: Path) -> None:
        configured_stage = os.environ.get("ARW_PHASE2_STAGE_ROOT")
        self.stage_root = (
            Path(configured_stage).resolve()
            if configured_stage
            else tmp_path / "stage" / PLUGIN_NAME
        )
        configured_evidence = os.environ.get("ARW_PHASE2_EVIDENCE_ROOT")
        self.evidence_root = (
            Path(configured_evidence).resolve()
            if configured_evidence
            else tmp_path / "evidence"
        )
        self.requests = tmp_path / "requests"
        self.cwd = tmp_path / "outside-checkout"
        self.cwd.mkdir(parents=True)
        self.primary_codex = tmp_path / "codex-primary"
        self.fresh_codex = tmp_path / "codex-fresh-replay"
        if not configured_stage:
            staged = subprocess.run(
                [
                    str(REPOSITORY_ROOT / "scripts/stage-plugin"),
                    "--clean",
                    "--stage-root",
                    str(self.stage_root),
                ],
                cwd=self.cwd,
                env=self.environment(),
                text=True,
                capture_output=True,
                check=False,
            )
            assert staged.returncode == 0, staged.stderr
        assert (self.stage_root / "bin/arw").is_file()
        self.command_number = 0

    def environment(
        self,
        *,
        fresh: bool = False,
        failpoint: str | None = None,
    ) -> dict[str, str]:
        value = {
            "HOME": str(self.cwd / "home"),
            "CODEX_HOME": str(self.fresh_codex if fresh else self.primary_codex),
            "PATH": os.environ["PATH"],
            "PYTHONNOUSERSITE": "1",
            "PIP_NO_INDEX": "1",
            "UV_OFFLINE": "1",
        }
        if failpoint is not None:
            value["ARW_TEST_FAILPOINT"] = failpoint
        return value

    def run(
        self,
        label: str,
        *arguments: str,
        expected: int = 0,
        fresh: bool = False,
        failpoint: str | None = None,
    ) -> tuple[subprocess.CompletedProcess[str], object | None]:
        self.command_number += 1
        argv = [str(self.stage_root / "bin/arw"), *arguments]
        environment = self.environment(fresh=fresh, failpoint=failpoint)
        result = subprocess.run(
            argv,
            cwd=self.cwd,
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        record = self.evidence_root / "commands" / f"{self.command_number:02d}-{label}"
        _write_json(
            record / "command.json",
            {
                "argv": argv,
                "cwd": str(self.cwd),
                "environment": {
                    key: environment[key]
                    for key in (
                        "ARW_TEST_FAILPOINT",
                        "CODEX_HOME",
                        "PIP_NO_INDEX",
                        "PYTHONNOUSERSITE",
                        "UV_OFFLINE",
                    )
                    if key in environment
                },
            },
        )
        (record / "stdout.log").write_text(result.stdout, encoding="utf-8")
        (record / "stderr.log").write_text(result.stderr, encoding="utf-8")
        _write_json(record / "exit.json", {"returncode": result.returncode})
        assert result.returncode == expected, (label, result.stdout, result.stderr)
        payload: object | None = None
        if result.stdout.strip():
            payload = json.loads(result.stdout)
            if isinstance(payload, dict) and "accepted" in payload:
                from arw.kernel.policy.schema_registry import validate_instance

                validate_instance("command-outcome.schema.json", payload)
        return result, payload

    def request(self, label: str, value: object) -> Path:
        path = self.requests / f"{label}.json"
        _write_json(path, value)
        return path

    def snapshot(self, label: str, root: Path) -> dict[str, dict[str, object]]:
        value = _inventory(root)
        _write_json(self.evidence_root / "trees" / f"{label}.json", value)
        return value


def _base(
    number: int,
    revision: int,
    occurred_at: str,
    *,
    role: str = "parent_control_plane",
) -> dict[str, object]:
    return {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "event_id": f"evt-00000000-0000-4000-8000-{number:012x}",
        "command_id": f"cmd-00000000-0000-4000-8000-{number:012x}",
        "expected_revision": revision,
        "occurred_at": occurred_at,
        "actor_id": "operator.user" if role == "operator" else "parent.runtime",
        "actor_role": role,
    }


def _assert_rejection_unchanged(
    harness: StagedHarness,
    run_root: Path,
    label: str,
    command: str,
    request: dict[str, object],
    expected_code: str,
) -> None:
    before = harness.snapshot(f"{label}-before", run_root)
    _, payload = harness.run(
        label,
        command,
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request(label, request)),
        expected=65,
    )
    assert payload["accepted"] is False
    assert payload["rejection"]["code"] == expected_code
    assert harness.snapshot(f"{label}-after", run_root) == before


def test_staged_projection_free_durable_runtime_design_intent(tmp_path: Path) -> None:
    from arw.kernel.core.canonical import canonical_json_bytes, strict_json_loads
    from arw.kernel.policy.schema_registry import validate_instance
    from arw.kernel.ledger.workflows import CORE_WORKFLOW

    harness = StagedHarness(tmp_path)
    run_root = tmp_path / "run"
    source = run_root / "input/source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("domain-neutral research input\n", encoding="utf-8")
    init_request = {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "occurred_at": "2026-07-13T09:00:00Z",
        "immutable_input": {
            "path": "input/source.txt",
            "sha256": _sha256(source.read_bytes()),
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
    harness.run(
        "init",
        "init",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("init", init_request)),
    )

    illegal = {
        **_base(202, 1, "2026-07-13T09:01:00Z", role="worker"),
        "actor_id": "worker.agent",
        "transition_id": "start",
        "from_stage": "initialized",
    }
    _assert_rejection_unchanged(
        harness, run_root, "unauthorized", "transition", illegal, "unauthorized-actor"
    )
    stale = {
        **_base(203, 0, "2026-07-13T09:02:00Z"),
        "transition_id": "start",
        "from_stage": "initialized",
    }
    _assert_rejection_unchanged(
        harness, run_root, "stale", "transition", stale, "stale-revision"
    )
    out_of_order = {
        **_base(204, 1, "2026-07-13T09:03:00Z"),
        "transition_id": "begin_work",
        "from_stage": "intake",
    }
    _assert_rejection_unchanged(
        harness, run_root, "out-of-order", "transition", out_of_order, "stale-stage"
    )

    start = {
        **_base(205, 1, "2026-07-13T09:04:00Z"),
        "transition_id": "start",
        "from_stage": "initialized",
    }
    _, started = harness.run(
        "start",
        "transition",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("start", start)),
    )
    assert started["state"]["accepted_revision"] == 2
    _assert_rejection_unchanged(
        harness, run_root, "duplicate", "transition", start, "duplicate-event-id"
    )

    decision_request = {
        **_base(206, 2, "2026-07-13T09:05:00Z"),
        "decision_id": "decision.route",
        "blocker_code": "human-choice-required",
        "allowed_choices": ["continue", "abort"],
        "rationale_required": True,
        "source_event_ids": [],
        "unlock_transitions": ["begin_work"],
    }
    _, decision = harness.run(
        "decision-request",
        "decision-request",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("decision-request", decision_request)),
    )
    decision_head = decision["state"]["ledger_head_sha256"]
    attempt_start = {
        **_base(207, 3, "2026-07-13T09:06:00Z"),
        "attempt_id": "attempt.writer-001",
        "base_revision": 3,
        "consumed_sha256": [decision_head],
    }
    harness.run(
        "attempt-start",
        "attempt-start",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("attempt-start", attempt_start)),
    )
    artifact = run_root / "outputs/result.txt"
    artifact.parent.mkdir()
    artifact.write_text("accepted result\n", encoding="utf-8")
    artifact_request = {
        **_base(208, 4, "2026-07-13T09:07:00Z"),
        "artifact_id": "artifact.result-001",
        "artifact_kind": "result",
        "media_type": "text/plain",
        "content_path": "outputs/result.txt",
        "content_sha256": _sha256(artifact.read_bytes()),
        "attempt_id": "attempt.writer-001",
        "base_revision": 3,
        "consumed_sha256": [decision_head],
    }
    harness.run(
        "artifact-accept",
        "artifact-accept",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("artifact-accept", artifact_request)),
    )
    attempt_close = {
        **_base(209, 5, "2026-07-13T09:08:00Z"),
        "attempt_id": "attempt.writer-001",
        "outcome": "completed",
        "proposal_sha256": _sha256(artifact.read_bytes()),
    }
    harness.run(
        "attempt-close",
        "attempt-close",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("attempt-close", attempt_close)),
    )
    decision_resolve = {
        **_base(210, 6, "2026-07-13T09:09:00Z"),
        "decision_id": "decision.route",
        "choice": "continue",
        "rationale": "continue with accepted evidence",
    }
    harness.run(
        "decision-resolve",
        "decision-resolve",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("decision-resolve", decision_resolve)),
    )

    checkpoint_one = {
        **_base(211, 7, "2026-07-13T09:10:00Z"),
        "checkpoint_kind": "human_decision",
        "fresh_until": "2026-07-13T09:30:00Z",
    }
    _, first_checkpoint = harness.run(
        "checkpoint-one",
        "checkpoint",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("checkpoint-one", checkpoint_one)),
    )
    passport_one = first_checkpoint["state"]["current_passport_sha256"]
    resume_one = {
        **_base(212, 8, "2026-07-13T09:20:00Z", role="operator"),
        "passport_sha256": passport_one,
    }
    harness.run(
        "resume-one",
        "resume",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("resume-one", resume_one)),
    )
    checkpoint_two = {
        **_base(213, 9, "2026-07-13T09:21:00Z"),
        "checkpoint_kind": "explicit",
        "fresh_until": "2026-07-13T09:40:00Z",
    }
    _, second_checkpoint = harness.run(
        "checkpoint-two",
        "checkpoint",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("checkpoint-two", checkpoint_two)),
    )
    passport_two = second_checkpoint["state"]["current_passport_sha256"]
    assert passport_two != passport_one
    resume_two = {
        **_base(214, 10, "2026-07-13T09:22:00Z", role="operator"),
        "passport_sha256": passport_two,
    }
    harness.run(
        "resume-two",
        "resume",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("resume-two", resume_two)),
    )
    duplicate_resume = {
        **_base(215, 11, "2026-07-13T09:23:00Z", role="operator"),
        "passport_sha256": passport_two,
    }
    _assert_rejection_unchanged(
        harness,
        run_root,
        "duplicate-resume",
        "resume",
        duplicate_resume,
        "passport-consumed",
    )

    expiring_checkpoint = {
        **_base(216, 11, "2026-07-13T09:24:00Z"),
        "checkpoint_kind": "explicit",
        "fresh_until": "2026-07-13T09:25:00Z",
    }
    harness.run(
        "checkpoint-expiring",
        "checkpoint",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("checkpoint-expiring", expiring_checkpoint)),
    )
    before_expired_status = harness.snapshot("expired-status-before", run_root)
    _, expired = harness.run(
        "status-expired",
        "status",
        "--json",
        "--at",
        "2026-07-13T09:26:00Z",
        "--run-root",
        str(run_root),
    )
    validate_instance("status.schema.json", expired)
    assert expired["blockers"] == [
        {"code": "evidence-expired", "source_event_id": None}
    ]
    assert harness.snapshot("expired-status-after", run_root) == before_expired_status
    blocked_transition = {
        **_base(217, 12, "2026-07-13T09:26:00Z"),
        "transition_id": "begin_work",
        "from_stage": "intake",
    }
    _assert_rejection_unchanged(
        harness,
        run_root,
        "expired-transition",
        "transition",
        blocked_transition,
        "evidence-expired",
    )
    fresh_checkpoint = {
        **_base(218, 12, "2026-07-13T09:27:00Z"),
        "checkpoint_kind": "explicit",
        "fresh_until": None,
    }
    _, refreshed = harness.run(
        "checkpoint-refresh",
        "checkpoint",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("checkpoint-refresh", fresh_checkpoint)),
    )
    current_passport = refreshed["state"]["current_passport_sha256"]
    begin_work = {
        **_base(219, 13, "2026-07-13T09:28:00Z"),
        "transition_id": "begin_work",
        "from_stage": "intake",
    }
    harness.run(
        "begin-work",
        "transition",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("begin-work", begin_work)),
    )

    torn_request = {
        **_base(220, 14, "2026-07-13T09:29:00Z"),
        "transition_id": "request_review",
        "from_stage": "work",
    }
    harness.run(
        "torn-append",
        "transition",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("torn-append", torn_request)),
        expected=-9,
        failpoint="partial-runtime-append-sigkill",
    )
    damaged_segment = run_root / "journal/segments/00000001.jsonl"
    original_damaged = damaged_segment.read_bytes()
    _, recovery_required = harness.run(
        "status-recovery-required",
        "status",
        "--json",
        "--run-root",
        str(run_root),
    )
    validate_instance("status.schema.json", recovery_required)
    assert recovery_required["accepted_revision"] == 14
    assert recovery_required["recovery_health"] == "recoverable_tail"
    assert recovery_required["legal_next_transitions"] == ["recover"]
    recovery_request = {
        **_base(221, 14, "2026-07-13T09:30:00Z", role="operator"),
        "expected_head_sha256": recovery_required["ledger_head_sha256"],
        "recovery_id": "recovery.e2e-001",
        "original_segment_sha256": _sha256(original_damaged),
        "reason_code": "process-terminated",
        "reason_text": "injected hard termination during runtime append",
    }
    _, recovered = harness.run(
        "recover",
        "recover",
        "--run-root",
        str(run_root),
        "--request",
        str(harness.request("recover", recovery_request)),
    )
    assert recovered["state"]["accepted_revision"] == 15
    assert recovered["state"]["recovery_health"] == "healthy"
    assert recovered["state"]["current_passport_sha256"] == current_passport
    raw = run_root / "quarantine/recovery.e2e-001/segment.raw"
    receipt_path = run_root / "quarantine/recovery.e2e-001/receipt.json"
    assert raw.read_bytes() == damaged_segment.read_bytes() == original_damaged
    receipt = strict_json_loads(receipt_path.read_bytes())
    validate_instance("recovery-receipt.schema.json", receipt)
    _write_json(
        harness.evidence_root / "recovery" / "binding.json",
        {
            "original_sha256": _sha256(original_damaged),
            "raw_sha256": _sha256(raw.read_bytes()),
            "receipt_sha256": _sha256(receipt_path.read_bytes()),
            "fault_offset": receipt["fault_offset"],
            "accepted_revision": recovered["state"]["accepted_revision"],
        },
    )

    _, status_before_delete = harness.run(
        "status-before-pointer-delete",
        "status",
        "--json",
        "--run-root",
        str(run_root),
    )
    (run_root / "passport.json").unlink()
    shutil.rmtree(run_root / "projections", ignore_errors=True)
    _, status_fresh_process = harness.run(
        "status-fresh-process",
        "status",
        "--json",
        "--run-root",
        str(run_root),
        fresh=True,
    )
    assert status_fresh_process == status_before_delete
    assert status_fresh_process["current_passport_sha256"] == current_passport
    _, replayed = harness.run(
        "replay-fresh-process",
        "replay",
        "--run-root",
        str(run_root),
        fresh=True,
    )
    assert replayed["revision"] == 15
    assert replayed["last_event_sha256"] == status_fresh_process["ledger_head_sha256"]

    middle_root = tmp_path / "tamper-middle"
    shutil.copytree(run_root, middle_root)
    middle_segment = middle_root / "journal/segments/00000001.jsonl"
    lines = middle_segment.read_bytes().splitlines(keepends=True)
    changed = strict_json_loads(lines[1])
    changed["payload"]["to_stage"] = "review"
    lines[1] = canonical_json_bytes(changed)
    middle_segment.write_bytes(b"".join(lines))
    middle_before = harness.snapshot("tamper-middle-before", middle_root)
    _, middle_status = harness.run(
        "tamper-middle-status",
        "status",
        "--json",
        "--run-root",
        str(middle_root),
    )
    assert middle_status["recovery_health"] == "blocked"
    assert harness.snapshot("tamper-middle-after", middle_root) == middle_before

    manifest_root = tmp_path / "tamper-manifest"
    shutil.copytree(run_root, manifest_root)
    artifact_manifest = next(
        (manifest_root / "manifests/artifacts/sha256").glob("*.json")
    )
    artifact_manifest.write_bytes(artifact_manifest.read_bytes() + b" ")
    manifest_before = harness.snapshot("tamper-manifest-before", manifest_root)
    _, manifest_status = harness.run(
        "tamper-manifest-status",
        "status",
        "--json",
        "--run-root",
        str(manifest_root),
    )
    assert manifest_status["recovery_health"] == "blocked"
    assert harness.snapshot("tamper-manifest-after", manifest_root) == manifest_before

    requirements = {name: True for name in ("RUN-03", "RUN-04", "RUN-05", "RUN-06", "RUN-07", "RUN-08")}
    decisions = {f"D-{number:02d}": True for number in range(1, 16)}
    verdict = {
        "schema_version": "1.0.0",
        "technical_qualification": "PASS",
        "release_qualification": "BLOCKED",
        "run_id": RUN_ID,
        "accepted_revision": 15,
        "ledger_head_sha256": status_fresh_process["ledger_head_sha256"],
        "current_passport_sha256": current_passport,
        "requirements": requirements,
        "decisions": decisions,
        "evidence": {
            "commands": len(list((harness.evidence_root / "commands").glob("*"))),
            "tree_snapshots": len(list((harness.evidence_root / "trees").glob("*.json"))),
            "recovery_binding_sha256": _sha256(
                (harness.evidence_root / "recovery/binding.json").read_bytes()
            ),
        },
    }
    _write_json(harness.evidence_root / "verdict.json", verdict)
    assert all(requirements.values()) and all(decisions.values())
