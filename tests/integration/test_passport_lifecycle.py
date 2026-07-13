from __future__ import annotations

import hashlib
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


def test_checkpoint_binds_state_and_pointer_is_never_authority(tmp_path: Path) -> None:
    from arw.manifests import load_material_passport
    from arw.models import CheckpointRequest

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
    assert passport.based_on_revision == 1
    assert passport.ledger_head_sha256 != checkpoint.state.ledger_head_sha256
    assert passport.parent_passport_sha256 is None
    assert passport.supersedes_passport_sha256 is None
    pointer = root / "passport.json"
    pointer.unlink()
    assert service.read_state().current_passport_sha256 == passport_hash
    pointer.write_text("corrupt pointer\n", encoding="utf-8")
    assert service.read_state().current_passport_sha256 == passport_hash


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
    from arw.models import CheckpointRequest, ResumeRequest

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
            {**_base(62, 2, role="operator"), "passport_sha256": passport_hash}
        )
    )
    assert rejected.rejection.code == "evidence-expired"
    assert passport_path.read_bytes() == immutable_bytes
