from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


RUN_ID = "run-00000000-0000-4000-8000-000000000401"
HASH_A = "a" * 64
HASH_B = "b" * 64
HASH_C = "c" * 64
HASH_D = "d" * 64
HASH_E = "e" * 64


def _assignment_and_attempt():
    from arw.orchestration_models import AttemptDescriptor, ImmutableAssignment

    assignment = ImmutableAssignment.model_validate(
        {
            "schema_version": "arw.assignment.v1",
            "protocol_version": "1.0.0",
            "assignment_id": "assignment.manifest-001",
            "supersedes_assignment_id": None,
            "run_id": RUN_ID,
            "stage_id": "proposal-stage",
            "task_id": "proposal-task-001",
            "role_id": "research_architect",
            "worker_identity_id": "worker.architect-001",
            "execution_mode": "assignment_injected_subagent",
            "execution_provenance": "assignment_injected_subagent",
            "independence_eligible": False,
            "base_revision": 1,
            "input_sha256": [HASH_A],
            "capability_ids": ["files.read"],
            "allowed_read_root_ids": ["research-root"],
            "scratch_path_template": "attempts/{attempt_id}/scratch",
            "result_path_template": "attempts/{attempt_id}/result",
            "output_policy": {
                "schema_id": "arw.worker-proposal.v1",
                "schema_sha256": HASH_B,
                "max_bytes": 4096,
                "max_artifacts": 1,
            },
            "policy_sha256": HASH_C,
            "context_manifest_sha256": HASH_D,
            "blind_review": {
                "required": False,
                "subject_sha256": None,
                "rubric_sha256": None,
                "forbidden_peer_role_ids": [],
            },
            "deadline_at": "2026-07-15T12:00:00Z",
            "completion_contract": {
                "requires_completed_proposal": True,
                "required_artifact_kinds": ["proposal"],
                "requires_human_gate": False,
            },
            "acceptance_key": {
                "topological_layer": 0,
                "task_ordinal": 0,
                "assignment_id": "assignment.manifest-001",
            },
        }
    )
    attempt = AttemptDescriptor.model_validate(
        {
            "schema_version": "arw.attempt-descriptor.v1",
            "assignment_id": assignment.assignment_id,
            "attempt_id": "attempt.manifest-001",
            "attempt_number": 1,
            "proposal_nonce": "nonce.manifest-001",
            "status": "active",
            "retry_reason": None,
            "retry_eligible": False,
            "continuation_count": 0,
            "host_agent_id": "host-agent-001",
            "cancellation_deadline_at": None,
        }
    )
    return assignment, attempt


def _proposal_bytes(assignment, attempt, *, assignment_id: str | None = None) -> bytes:
    from arw.canonical import canonical_json_bytes
    from arw.orchestration_models import ProposedArtifact, WorkerProposal

    proposal = WorkerProposal.model_validate(
        {
            "schema_version": "arw.worker-proposal.v1",
            "protocol_version": "1.0.0",
            "run_id": RUN_ID,
            "assignment_id": assignment_id or assignment.assignment_id,
            "attempt_id": attempt.attempt_id,
            "role_id": assignment.role_id,
            "worker_identity_id": assignment.worker_identity_id,
            "host_agent_id": attempt.host_agent_id,
            "execution_mode": assignment.execution_mode,
            "execution_provenance": assignment.execution_provenance,
            "independence_eligible": assignment.independence_eligible,
            "assignment_sha256": assignment.canonical_sha256(),
            "context_manifest_sha256": assignment.context_manifest_sha256,
            "policy_sha256": assignment.policy_sha256,
            "base_revision": assignment.base_revision,
            "input_sha256": assignment.input_sha256,
            "proposal_nonce": attempt.proposal_nonce,
            "status": "completed",
            "result_provenance_mode": "executed",
            "requested_next_action": "accept",
            "artifacts": [
                {
                    "relative_path": "proposal.json",
                    "sha256": HASH_E,
                    "media_type": "application/json",
                    "schema_id": "arw.worker-proposal.v1",
                    "byte_count": 128,
                }
            ],
            "evidence_sha256": [HASH_E],
            "summary": "A bounded raw proposal.",
            "unresolved": [],
        }
    )
    return canonical_json_bytes(proposal.model_dump(mode="json"))


def test_artifact_manifest_has_canonical_content_address(tmp_path: Path) -> None:
    from arw.manifests import install_artifact_manifest, manifest_bytes_and_sha256
    from arw.models import ArtifactManifest
    from arw.schema_registry import validate_instance

    root = tmp_path / "run"
    root.mkdir()
    manifest = ArtifactManifest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": "run-00000000-0000-4000-8000-000000000051",
            "artifact_id": "artifact.figure-001",
            "artifact_kind": "figure",
            "media_type": "image/png",
            "content_path": "outputs/figure.png",
            "content_sha256": "a" * 64,
            "producer_id": "parent.runtime",
            "attempt_id": None,
            "base_revision": 1,
            "consumed_sha256": ["b" * 64],
            "created_at": "2026-07-13T03:00:00Z",
        }
    )
    canonical, digest = manifest_bytes_and_sha256(manifest)
    validate_instance(
        "artifact-manifest.schema.json",
        manifest.model_dump(mode="json", exclude_none=True),
    )
    installed = install_artifact_manifest(root, manifest)
    assert installed == root / "manifests" / "artifacts" / "sha256" / f"{digest}.json"
    assert installed.read_bytes() == canonical
    assert hashlib.sha256(installed.read_bytes()).hexdigest() == digest
    assert install_artifact_manifest(root, manifest) == installed


@pytest.mark.parametrize("path", ["../outside.txt", "/tmp/outside.txt", "a/../outside.txt"])
def test_content_validation_rejects_non_normalized_paths(tmp_path: Path, path: str) -> None:
    from arw.manifests import ManifestError, validate_content_file

    root = tmp_path / "run"
    root.mkdir()
    with pytest.raises(ManifestError):
        validate_content_file(root, path, "0" * 64)


def test_content_validation_rejects_symlink_and_digest_drift(tmp_path: Path) -> None:
    from arw.manifests import ManifestError, validate_content_file

    root = tmp_path / "run"
    content = root / "outputs" / "result.txt"
    content.parent.mkdir(parents=True)
    content.write_text("accepted bytes\n", encoding="utf-8")
    expected = hashlib.sha256(content.read_bytes()).hexdigest()
    assert validate_content_file(root, "outputs/result.txt", expected) == content
    with pytest.raises(ManifestError, match="digest"):
        validate_content_file(root, "outputs/result.txt", "f" * 64)
    link = root / "outputs" / "linked.txt"
    link.symlink_to(content)
    with pytest.raises(ManifestError, match="symlink"):
        validate_content_file(root, "outputs/linked.txt", expected)


def test_assignment_attempt_tree_is_write_once_and_rejects_replacement_or_symlink(
    tmp_path: Path,
) -> None:
    from arw.manifests import (
        ManifestError,
        install_assignment_manifest,
        materialize_attempt_tree,
    )

    root = tmp_path / "run"
    root.mkdir()
    assignment, attempt = _assignment_and_attempt()
    installed = install_assignment_manifest(root, assignment)
    assert installed == root / "assignments" / f"{assignment.assignment_id}.json"
    attempt_assignment = materialize_attempt_tree(root, assignment, attempt)
    assert attempt_assignment == root / "attempts" / attempt.attempt_id / "assignment.json"
    assert attempt_assignment.read_bytes() == installed.read_bytes()
    assert materialize_attempt_tree(root, assignment, attempt) == attempt_assignment

    changed = assignment.model_copy(update={"policy_sha256": "f" * 64})
    with pytest.raises(ManifestError, match="immutable|replacement|content"):
        install_assignment_manifest(root, changed)

    outside = tmp_path / "outside-assignment.json"
    outside.write_bytes(installed.read_bytes())
    installed.unlink()
    installed.symlink_to(outside)
    with pytest.raises(ManifestError, match="symlink"):
        install_assignment_manifest(root, assignment)


@pytest.mark.parametrize("assignment_id", ["../outside", "nested/assignment", "/absolute"])
def test_assignment_loader_rejects_path_traversal_ids(tmp_path: Path, assignment_id: str) -> None:
    from arw.manifests import ManifestError, load_assignment_manifest

    root = tmp_path / "run"
    root.mkdir()
    with pytest.raises(ManifestError, match="safe runtime identifier"):
        load_assignment_manifest(root, assignment_id)


def test_raw_proposal_admission_is_bounded_direct_and_content_addressed(tmp_path: Path) -> None:
    from arw.manifests import ManifestError, admit_raw_proposal, materialize_attempt_tree

    root = tmp_path / "run"
    root.mkdir()
    assignment, attempt = _assignment_and_attempt()
    materialize_attempt_tree(root, assignment, attempt)
    proposal_path = root / "attempts" / attempt.attempt_id / "result" / "proposal.json"
    raw = _proposal_bytes(assignment, attempt)
    proposal_path.write_bytes(raw)

    evidence = admit_raw_proposal(root, assignment=assignment, attempt=attempt)
    assert evidence.attempt_id == attempt.attempt_id
    assert evidence.raw_bytes == raw
    assert evidence.sha256 == hashlib.sha256(raw).hexdigest()
    assert evidence.evidence_path.is_file()
    proposal_path.unlink()
    assert evidence.evidence_path.read_bytes() == raw

    with pytest.raises(ManifestError, match="proposal"):
        admit_raw_proposal(root, assignment=assignment, attempt=attempt)


@pytest.mark.parametrize("kind", ["symlink", "oversized", "echo-mismatch", "replaced"])
def test_raw_proposal_admission_rejects_untrusted_file_variants(tmp_path: Path, kind: str) -> None:
    from arw.manifests import ManifestError, admit_raw_proposal, materialize_attempt_tree

    root = tmp_path / "run"
    root.mkdir()
    assignment, attempt = _assignment_and_attempt()
    materialize_attempt_tree(root, assignment, attempt)
    result_root = root / "attempts" / attempt.attempt_id / "result"
    proposal_path = result_root / "proposal.json"
    raw = _proposal_bytes(assignment, attempt)
    if kind == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_bytes(raw)
        proposal_path.symlink_to(outside)
    elif kind == "oversized":
        proposal_path.write_bytes(raw + (b"x" * 128))
    elif kind == "echo-mismatch":
        proposal_path.write_bytes(_proposal_bytes(assignment, attempt, assignment_id="assignment.other-001"))
    else:
        proposal_path.write_bytes(raw)
        first = admit_raw_proposal(root, assignment=assignment, attempt=attempt)
        proposal_path.write_bytes(raw + b"\n")
        with pytest.raises(ManifestError, match="digest|replaced|canonical"):
            admit_raw_proposal(root, assignment=assignment, attempt=attempt, expected_sha256=first.sha256)
        return

    with pytest.raises(ManifestError):
        admit_raw_proposal(root, assignment=assignment, attempt=attempt, max_bytes=64)
