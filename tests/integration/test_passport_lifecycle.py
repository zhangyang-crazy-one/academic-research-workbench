from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


RUN_ID = "run-00000000-0000-4000-8000-000000000051"


def _tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _service(tmp_path: Path):
    from arw.journal import initialize_run
    from arw.models import InitRunRequest
    from arw.runtime import RuntimeCommandService
    from arw.workflows import CORE_WORKFLOW

    root = tmp_path / "run"
    source = root / "input" / "source.txt"
    source.parent.mkdir(parents=True)
    source.write_text("passport run\n", encoding="utf-8")
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "occurred_at": "2026-07-13T03:00:00Z",
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
                "event_id": "evt-00000000-0000-4000-8000-000000000051",
                "command_id": "cmd-00000000-0000-4000-8000-000000000051",
                "actor_id": "parent.runtime",
            }
        ),
    )
    return root, RuntimeCommandService(root)


def _base(number: int, revision: int, *, role: str = "parent_control_plane"):
    return {
        "schema_version": "1.0.0",
        "run_id": RUN_ID,
        "event_id": f"evt-00000000-0000-4000-8000-{number:012x}",
        "command_id": f"cmd-00000000-0000-4000-8000-{number:012x}",
        "expected_revision": revision,
        "occurred_at": f"2026-07-13T03:{number % 60:02d}:00Z",
        "actor_id": "parent.runtime" if role == "parent_control_plane" else "operator.user",
        "actor_role": role,
    }


def test_artifact_store_is_not_authority_until_acceptance_event(tmp_path: Path) -> None:
    from arw.manifests import install_artifact_manifest
    from arw.models import ArtifactAcceptanceRequest, ArtifactManifest
    from arw.schema_registry import validate_instance

    root, service = _service(tmp_path)
    content = root / "outputs" / "figure.png"
    content.parent.mkdir()
    content.write_bytes(b"PNG fixture")
    content_hash = hashlib.sha256(content.read_bytes()).hexdigest()
    orphan = ArtifactManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "artifact_id": "artifact.orphan-001",
            "artifact_kind": "figure",
            "media_type": "image/png",
            "content_path": "outputs/figure.png",
            "content_sha256": content_hash,
            "producer_id": "parent.runtime",
            "attempt_id": None,
            "base_revision": 1,
            "consumed_sha256": [],
            "created_at": "2026-07-13T03:01:00Z",
        }
    )
    install_artifact_manifest(root, orphan)
    assert service.read_state().accepted_artifact_manifest_sha256 == []
    request = ArtifactAcceptanceRequest.model_validate(
        {
            **_base(52, 1),
            "artifact_id": "artifact.figure-001",
            "artifact_kind": "figure",
            "media_type": "image/png",
            "content_path": "outputs/figure.png",
            "content_sha256": content_hash,
            "attempt_id": None,
            "base_revision": 1,
            "consumed_sha256": [],
        }
    )
    validate_instance(
        "artifact-request.schema.json",
        request.model_dump(mode="json", exclude_none=True),
    )
    accepted = service.accept_artifact(request)
    assert accepted.accepted
    assert len(accepted.state.accepted_artifact_manifest_sha256) == 1
    assert accepted.event.event_type == "artifact.accepted"


def test_artifact_rejection_preserves_store_and_journal(tmp_path: Path) -> None:
    from arw.models import ArtifactAcceptanceRequest

    root, service = _service(tmp_path)
    content = root / "outputs" / "result.txt"
    content.parent.mkdir()
    content.write_text("result\n", encoding="utf-8")
    request = ArtifactAcceptanceRequest.model_validate(
        {
            **_base(53, 1),
            "artifact_id": "artifact.result-001",
            "artifact_kind": "result",
            "media_type": "text/plain",
            "content_path": "outputs/result.txt",
            "content_sha256": "f" * 64,
            "attempt_id": None,
            "base_revision": 1,
            "consumed_sha256": [],
        }
    )
    before = _tree(root)
    rejected = service.accept_artifact(request)
    assert rejected.rejection.code == "artifact-content-invalid"
    assert _tree(root) == before


def test_duplicate_artifact_id_rejects_before_installing_an_orphan_manifest(
    tmp_path: Path,
) -> None:
    from arw.models import ArtifactAcceptanceRequest

    root, service = _service(tmp_path)
    outputs = root / "outputs"
    outputs.mkdir()
    first_content = outputs / "first.txt"
    first_content.write_text("first\n", encoding="utf-8")
    first = ArtifactAcceptanceRequest.model_validate(
        {
            **_base(56, 1),
            "artifact_id": "artifact.stable-001",
            "artifact_kind": "result",
            "media_type": "text/plain",
            "content_path": "outputs/first.txt",
            "content_sha256": hashlib.sha256(first_content.read_bytes()).hexdigest(),
            "attempt_id": None,
            "base_revision": 1,
            "consumed_sha256": [],
        }
    )
    assert service.accept_artifact(first).accepted

    second_content = outputs / "second.txt"
    second_content.write_text("second\n", encoding="utf-8")
    second = ArtifactAcceptanceRequest.model_validate(
        {
            **_base(57, 2),
            "artifact_id": "artifact.stable-001",
            "artifact_kind": "result",
            "media_type": "text/plain",
            "content_path": "outputs/second.txt",
            "content_sha256": hashlib.sha256(second_content.read_bytes()).hexdigest(),
            "attempt_id": None,
            "base_revision": 2,
            "consumed_sha256": [],
        }
    )
    before = _tree(root)
    rejected = service.accept_artifact(second)

    assert rejected.rejection is not None
    assert rejected.rejection.code == "duplicate-artifact"
    assert _tree(root) == before


def test_replay_blocks_resealed_passport_that_does_not_bind_checkpoint_state(
    tmp_path: Path,
) -> None:
    from arw.kernel.core.canonical import canonical_json_bytes, seal_event
    from arw.models import CheckpointRequest

    root, service = _service(tmp_path)
    checkpoint = service.create_checkpoint(
        CheckpointRequest.model_validate(
            {**_base(58, 1), "checkpoint_kind": "explicit", "fresh_until": None}
        )
    )
    assert checkpoint.accepted
    original_hash = checkpoint.state.current_passport_sha256
    original_path = root / "passports/sha256" / f"{original_hash}.json"
    passport = json.loads(original_path.read_bytes())
    passport["ledger_head_sha256"] = "f" * 64
    tampered_bytes = canonical_json_bytes(passport)
    tampered_hash = hashlib.sha256(tampered_bytes).hexdigest()
    (root / "passports/sha256" / f"{tampered_hash}.json").write_bytes(tampered_bytes)

    journal = root / "journal/segments/00000001.jsonl"
    records = [json.loads(line) for line in journal.read_bytes().splitlines()]
    records[-1]["payload"]["passport_sha256"] = tampered_hash
    records[-1] = seal_event(records[-1])
    journal.write_bytes(b"".join(canonical_json_bytes(record) for record in records))
    before = _tree(root)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "status",
            "--json",
            "--run-root",
            str(root),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["accepted_revision"] == 1
    assert status["current_passport_sha256"] is None
    assert status["recovery_health"] == "blocked"
    assert _tree(root) == before


def test_status_without_at_uses_current_utc_for_passport_freshness(
    tmp_path: Path,
) -> None:
    from arw.models import CheckpointRequest

    root, service = _service(tmp_path)
    checkpoint = service.create_checkpoint(
        CheckpointRequest.model_validate(
            {
                **_base(59, 1),
                "checkpoint_kind": "explicit",
                "fresh_until": "2026-07-13T03:00:01Z",
            }
        )
    )
    assert checkpoint.accepted

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "status",
            "--json",
            "--run-root",
            str(root),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert [item["code"] for item in status["blockers"]] == ["evidence-expired"]
    assert status["legal_next_transitions"] == []


def test_checkpoint_binds_state_and_pointer_is_never_authority(tmp_path: Path) -> None:
    from arw.manifests import load_material_passport
    from arw.models import CheckpointRequest
    from arw.schema_registry import validate_instance

    root, service = _service(tmp_path)
    checkpoint = service.create_checkpoint(
        CheckpointRequest.model_validate(
            {
                **_base(54, 1),
                "checkpoint_kind": "explicit",
                "fresh_until": "2026-07-14T00:00:00Z",
            }
        )
    )
    assert checkpoint.accepted
    passport_hash = checkpoint.state.current_passport_sha256
    passport = load_material_passport(root, passport_hash)
    validate_instance(
        "material-passport.schema.json",
        passport.model_dump(mode="json", exclude_none=True),
    )
    assert passport.based_on_revision == 1
    assert passport.ledger_head_sha256 != checkpoint.state.ledger_head_sha256
    assert passport.parent_passport_sha256 is None
    assert passport.supersedes_passport_sha256 is None
    pointer = root / "passport.json"
    validate_instance("passport-pointer.schema.json", json.loads(pointer.read_bytes()))
    pointer.unlink()
    assert service.read_state().current_passport_sha256 == passport_hash
    pointer.write_text("corrupt pointer\n", encoding="utf-8")
    assert service.read_state().current_passport_sha256 == passport_hash
    rebuilt = service.rebuild_passport_pointer()
    assert rebuilt.passport_sha256 == passport_hash
    validate_instance("passport-pointer.schema.json", json.loads(pointer.read_bytes()))


def test_passport_snapshots_pending_decisions_and_active_attempts(tmp_path: Path) -> None:
    from arw.manifests import load_material_passport
    from arw.models import AttemptStartRequest, CheckpointRequest, HumanDecisionRequest

    root, service = _service(tmp_path)
    decision = service.request_decision(
        HumanDecisionRequest.model_validate(
            {
                **_base(63, 1),
                "decision_id": "decision.route",
                "blocker_code": "human-choice-required",
                "allowed_choices": ["continue", "abort"],
                "rationale_required": True,
                "source_event_ids": [],
                "unlock_transitions": ["start"],
            }
        )
    )
    attempt = service.start_attempt(
        AttemptStartRequest.model_validate(
            {
                **_base(64, 2),
                "attempt_id": "attempt.writer-001",
                "base_revision": 2,
                "consumed_sha256": [decision.state.ledger_head_sha256],
            }
        )
    )
    checkpoint = service.create_checkpoint(
        CheckpointRequest.model_validate(
            {**_base(65, 3), "checkpoint_kind": "explicit", "fresh_until": None}
        )
    )
    assert decision.accepted and attempt.accepted and checkpoint.accepted
    passport = load_material_passport(root, checkpoint.state.current_passport_sha256)
    assert [item.decision_id for item in passport.pending_human_decisions] == [
        "decision.route"
    ]
    assert [item.attempt_id for item in passport.active_attempts] == [
        "attempt.writer-001"
    ]


def test_checkpoint_kind_requires_a_coherent_boundary(tmp_path: Path) -> None:
    from arw.models import CheckpointRequest

    root, service = _service(tmp_path)
    before = _tree(root)
    rejected = service.create_checkpoint(
        CheckpointRequest.model_validate(
            {**_base(55, 1), "checkpoint_kind": "stage_handoff", "fresh_until": None}
        )
    )
    assert rejected.rejection.code == "incoherent-checkpoint"
    assert _tree(root) == before


def test_passport_supersession_and_exact_single_use_resume(tmp_path: Path) -> None:
    from arw.models import CheckpointRequest, ResumeRequest

    root, service = _service(tmp_path)
    first = service.create_checkpoint(
        CheckpointRequest.model_validate(
            {**_base(56, 1), "checkpoint_kind": "explicit", "fresh_until": None}
        )
    )
    first_hash = first.state.current_passport_sha256
    second = service.create_checkpoint(
        CheckpointRequest.model_validate(
            {**_base(57, 2), "checkpoint_kind": "explicit", "fresh_until": None}
        )
    )
    second_hash = second.state.current_passport_sha256
    assert second_hash != first_hash
    before = _tree(root)
    stale = service.resume(
        ResumeRequest.model_validate(
            {**_base(58, 3, role="operator"), "passport_sha256": first_hash}
        )
    )
    assert stale.rejection.code == "stale-passport"
    assert _tree(root) == before
    resumed = service.resume(
        ResumeRequest.model_validate(
            {**_base(59, 3, role="operator"), "passport_sha256": second_hash}
        )
    )
    assert resumed.accepted
    before_retry = _tree(root)
    duplicate = service.resume(
        ResumeRequest.model_validate(
            {**_base(60, 4, role="operator"), "passport_sha256": second_hash}
        )
    )
    assert duplicate.rejection.code == "passport-consumed"
    assert _tree(root) == before_retry


def test_freshness_blocks_resume_without_mutating_passport(tmp_path: Path) -> None:
    from arw.models import CheckpointRequest, LifecycleTransitionRequest, ResumeRequest

    root, service = _service(tmp_path)
    checkpoint = service.create_checkpoint(
        CheckpointRequest.model_validate(
            {
                **_base(61, 1),
                "checkpoint_kind": "explicit",
                "fresh_until": "2026-07-13T04:00:00Z",
            }
        )
    )
    passport_hash = checkpoint.state.current_passport_sha256
    passport_path = root / "passports" / "sha256" / f"{passport_hash}.json"
    immutable_bytes = passport_path.read_bytes()
    stale_state = service.read_state(now=datetime(2026, 7, 13, 5, tzinfo=UTC))
    assert [item.code for item in stale_state.blockers] == ["evidence-expired"]
    rejected = service.resume(
        ResumeRequest.model_validate(
            {
                **_base(62, 2, role="operator"),
                "occurred_at": "2026-07-13T05:00:00Z",
                "passport_sha256": passport_hash,
            }
        )
    )
    assert rejected.rejection.code == "evidence-expired"
    assert passport_path.read_bytes() == immutable_bytes
    before_transition = _tree(root)
    transition = service.execute_transition(
        LifecycleTransitionRequest.model_validate(
            {
                **_base(66, 2),
                "occurred_at": "2026-07-13T05:01:00Z",
                "transition_id": "start",
                "from_stage": "initialized",
            }
        )
    )
    assert transition.rejection.code == "evidence-expired"
    assert _tree(root) == before_transition


def test_passport_event_survives_sigkill_before_pointer(tmp_path: Path) -> None:
    from arw.models import CheckpointRequest

    root, service = _service(tmp_path)
    request = CheckpointRequest.model_validate(
        {**_base(67, 1), "checkpoint_kind": "explicit", "fresh_until": None}
    )
    request_path = tmp_path / "checkpoint.json"
    request_path.write_text(
        json.dumps(request.model_dump(mode="json")), encoding="utf-8"
    )
    environment = os.environ.copy()
    environment["ARW_TEST_FAILPOINT"] = "post-passport-event-pre-pointer-sigkill"
    killed = subprocess.run(
        [
            sys.executable,
            "-m",
            "arw.cli",
            "checkpoint",
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
    assert not (root / "passport.json").exists()
    replayed = service.read_state()
    assert replayed.accepted_revision == 2
    assert replayed.current_passport_sha256 is not None
