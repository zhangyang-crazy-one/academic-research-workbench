"""Canonical bundle admission, retry, and confined filesystem behavior."""

import hashlib
import json
import os

import pytest
from arw_artifact_integrity.service import (
    ArtifactIntegrityService,
    ArtifactOperationError,
)

from arw.kernel.execution.runtime import RuntimeCommandService
from arw.kernel.ledger.journal import initialize_run, replay_run
from arw.kernel.ledger.workflows import CORE_WORKFLOW
from arw.kernel.state.models import ArtifactAcceptanceRequest, InitRunRequest

RUN_ID = "run-00000000-0000-4000-8000-000000000099"


def setup_run(tmp_path):
    root = tmp_path / "run"
    root.mkdir()
    source = root / "source.txt"
    source.write_bytes("中文\u200b x=2 [@key]\r\n👩\u200d🔬".encode())
    initialize_run(
        root,
        InitRunRequest.model_validate(
            {
                "schema_version": "1.0.0",
                "run_id": RUN_ID,
                "occurred_at": "2026-09-08T00:00:00Z",
                "immutable_input": {
                    "path": "source.txt",
                    "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                },
                "workflow_family": "academic-pipeline",
                "workflow_mode": "inline-role-prompts",
                "workflow_definition_id": CORE_WORKFLOW.definition_id,
                "workflow_definition_sha256": CORE_WORKFLOW.sha256,
                "journal_layout": "segmented-v1",
                "capabilities": ["canonical-journal"],
                "event_id": "evt-00000000-0000-4000-8000-000000000099",
                "command_id": "cmd-00000000-0000-4000-8000-000000000099",
                "actor_id": "parent.runtime",
            }
        ),
    )
    request = ArtifactAcceptanceRequest.model_validate(
        {
            "schema_version": "1.0.0",
            "run_id": RUN_ID,
            "occurred_at": "2026-09-08T00:01:00Z",
            "event_id": "evt-00000000-0000-4000-8000-000000000100",
            "command_id": "cmd-00000000-0000-4000-8000-000000000100",
            "actor_id": "parent.runtime",
            "actor_role": "parent_control_plane",
            "expected_revision": 1,
            "artifact_id": "artifact.cleaned",
            "artifact_kind": "ignored",
            "media_type": "text/plain",
            "content_path": "ignored.txt",
            "content_sha256": "f" * 64,
            "base_revision": 1,
            "consumed_sha256": [replay_run(root).last_event_sha256],
        }
    )
    return root, source, request


def sanitize(root, request, **kwargs):
    return ArtifactIntegrityService().sanitize(
        root,
        "source.txt",
        run_root=root,
        request=request,
        privacy=True,
        remove_codepoints=["U+200B"],
        **kwargs,
    )


def tree(root):
    return {
        str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()
    }


def test_inspect_does_not_mutate_or_create_roots(tmp_path):
    root, _source, _ = setup_run(tmp_path)
    before = tree(root)
    assert ArtifactIntegrityService().inspect(root, "source.txt").status == "inspected"
    assert tree(root) == before
    missing = tmp_path / "absent"
    with pytest.raises(ArtifactOperationError):
        ArtifactIntegrityService().inspect(missing, "source.txt")
    assert not missing.exists()


def test_accepted_bundle_is_recoverable_and_retry_idempotent(tmp_path):
    root, source, request = setup_run(tmp_path)
    original = source.read_bytes()
    result = sanitize(root, request)
    assert result["accepted"] and result["status"] == "accepted"
    bundle = json.loads((root / result["bundle_path"]).read_bytes())
    assert bundle["source"]["text"].encode() == original == source.read_bytes()
    assert (
        bundle["derived"]["text"].encode()
        == (root / result["export_path"]).read_bytes()
    )
    assert bundle["derived"]["sha256"] == result["derived_sha256"]
    assert replay_run(root).event_count == 2
    # The accepted bundle retains both byte sequences even without the mirror.
    (root / result["export_path"]).unlink()
    again = sanitize(root, request)
    assert again["status"] == "already_accepted" and again["accepted"]
    assert (root / again["export_path"]).read_bytes() == bundle["derived"][
        "text"
    ].encode()
    assert replay_run(root).event_count == 2


@pytest.mark.parametrize(
    "relative", ["../source.txt", "./source.txt", "a//b", "/etc/passwd", "a\\b"]
)
def test_paths_reject_traversal_and_ambiguity(tmp_path, relative):
    with pytest.raises(ArtifactOperationError):
        ArtifactIntegrityService().inspect(tmp_path, relative)


def test_symlinks_special_files_and_unsupported_platform(tmp_path, monkeypatch):
    root, source, _ = setup_run(tmp_path)
    (root / "link").symlink_to(source)
    (tmp_path / "linked-root").symlink_to(root, target_is_directory=True)
    os.mkfifo(root / "fifo")
    for path in ("link", "fifo"):
        with pytest.raises(ArtifactOperationError):
            ArtifactIntegrityService().inspect(root, path)
    with pytest.raises(ArtifactOperationError):
        ArtifactIntegrityService().inspect(tmp_path / "linked-root", "source.txt")
    monkeypatch.setattr("arw_artifact_integrity.service.PLATFORM_SUPPORTED", False)
    with pytest.raises(ArtifactOperationError, match="platform_unsupported"):
        ArtifactIntegrityService().inspect(root, "source.txt")


def test_authorization_refusal_changes_nothing(tmp_path):
    root, _source, request = setup_run(tmp_path)
    before = tree(root)
    with pytest.raises(ValueError, match="privacy"):
        ArtifactIntegrityService().sanitize(
            root,
            "source.txt",
            run_root=root,
            request=request,
            privacy=False,
            remove_codepoints=["U+200B"],
        )
    assert tree(root) == before


def test_stale_request_never_claims_acceptance(tmp_path):
    root, _source, request = setup_run(tmp_path)
    result = sanitize(root, request.model_copy(update={"expected_revision": 0}))
    assert not result["accepted"] and result["status"] == "rejected"
    assert result["reason_code"] == "stale-revision"
    assert replay_run(root).event_count == 1


def test_interrupted_acceptance_reuses_only_exact_candidate(tmp_path, monkeypatch):
    root, _source, request = setup_run(tmp_path)
    original_accept = RuntimeCommandService.accept_artifact

    def fail(self, request):
        raise OSError("injected interruption")

    monkeypatch.setattr(RuntimeCommandService, "accept_artifact", fail)
    with pytest.raises(ArtifactOperationError, match="acceptance_interrupted"):
        sanitize(root, request)
    assert replay_run(root).event_count == 1
    assert len(list(root.glob("arw-sanitize-*.receipt.json"))) == 1
    monkeypatch.setattr(RuntimeCommandService, "accept_artifact", original_accept)
    assert sanitize(root, request)["accepted"]
    assert replay_run(root).event_count == 2


def test_post_commit_interruption_retry_does_not_duplicate(tmp_path, monkeypatch):
    root, _source, request = setup_run(tmp_path)
    original_accept = RuntimeCommandService.accept_artifact

    def fail_after(self, request):
        original_accept(self, request)
        raise OSError("after journal commit")

    monkeypatch.setattr(RuntimeCommandService, "accept_artifact", fail_after)
    with pytest.raises(ArtifactOperationError):
        sanitize(root, request)
    assert replay_run(root).event_count == 2
    monkeypatch.setattr(RuntimeCommandService, "accept_artifact", original_accept)
    assert sanitize(root, request)["status"] == "already_accepted"


def test_conflicting_retry_and_altered_export_are_rejected(tmp_path):
    root, _source, request = setup_run(tmp_path)
    result = sanitize(root, request)
    with pytest.raises(ArtifactOperationError):
        sanitize(root, request.model_copy(update={"actor_id": "parent.changed"}))
    export = root / result["export_path"]
    export.chmod(0o600)
    export.write_bytes(b"altered")
    with pytest.raises(ArtifactOperationError, match="output_collision"):
        sanitize(root, request)
    assert replay_run(root).event_count == 2


def test_raw_content_hash_cannot_be_consumed_provenance(tmp_path):
    root, source, request = setup_run(tmp_path)
    result = sanitize(
        root,
        request.model_copy(
            update={
                "consumed_sha256": [hashlib.sha256(source.read_bytes()).hexdigest()]
            }
        ),
    )
    assert not result["accepted"] and result["reason_code"] == "stale-consumed-input"


def test_canonical_replay_retains_source_after_both_text_files_are_removed(tmp_path):
    root, source, request = setup_run(tmp_path)
    original = source.read_bytes()
    result = sanitize(root, request)
    source.unlink()
    (root / result["export_path"]).unlink()
    assert RuntimeCommandService(root).read_state().accepted_revision == 2
    bundle = json.loads((root / result["bundle_path"]).read_bytes())
    assert bundle["source"]["text"].encode() == original
    assert (
        hashlib.sha256(bundle["derived"]["text"].encode()).hexdigest()
        == result["derived_sha256"]
    )


def test_unstable_source_and_symlink_ancestor_rejected(tmp_path, monkeypatch):
    root, source, _request = setup_run(tmp_path)
    (root / "nested").symlink_to(root, target_is_directory=True)
    with pytest.raises(ArtifactOperationError):
        ArtifactIntegrityService().inspect(root, "nested/source.txt")
    read = os.read
    altered = False

    def race(fd, size):
        nonlocal altered
        chunk = read(fd, size)
        if not altered:
            altered = True
            source.write_bytes(b"changed")
        return chunk

    monkeypatch.setattr("arw_artifact_integrity.service.os.read", race)
    with pytest.raises(ArtifactOperationError, match="unstable_input"):
        ArtifactIntegrityService().inspect(root, "source.txt")


def test_failed_directory_walk_closes_every_descriptor(tmp_path):
    root, _, _ = setup_run(tmp_path)
    (root / "nested").mkdir()
    # Linux-specific diagnostic; production code rejects unsupported platforms.
    fd_dir = __import__("pathlib").Path("/proc/self/fd")
    if not fd_dir.is_dir():
        pytest.skip("descriptor inventory unavailable")
    before = len(list(fd_dir.iterdir()))
    for _ in range(20):
        with pytest.raises(ArtifactOperationError):
            ArtifactIntegrityService().inspect(root, "nested/missing/file")
    assert len(list(fd_dir.iterdir())) == before


def test_uninitialized_existing_run_does_not_create_lock_or_candidates(tmp_path):
    root, _, request = setup_run(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(ArtifactOperationError):
        ArtifactIntegrityService().sanitize(
            root,
            "source.txt",
            run_root=empty,
            request=request,
            privacy=True,
            remove_codepoints=["U+200B"],
        )
    assert list(empty.iterdir()) == []


@pytest.mark.parametrize("seam", ["replay", "accept"])
@pytest.mark.parametrize("ancestor", [False, True])
def test_root_swapped_before_runtime_boundary_never_writes_outside(
    tmp_path, monkeypatch, seam, ancestor
):
    container = tmp_path / "container"
    container.mkdir()
    root, _, request = setup_run(container)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "run").mkdir()
    (outside / "run" / "sentinel").write_bytes(b"outside")
    outside_before = tree(outside)
    victim = container if ancestor else root
    moved = tmp_path / "retained"
    target = outside if ancestor else outside / "run"

    def swap():
        victim.rename(moved)
        victim.symlink_to(target, target_is_directory=True)

    if seam == "replay":
        retry = ArtifactIntegrityService._accepted_retry

        def swapped_retry(run_root, candidate, descriptor):
            swap()
            return retry(run_root, candidate, descriptor)

        monkeypatch.setattr(
            ArtifactIntegrityService, "_accepted_retry", staticmethod(swapped_retry)
        )
    else:

        def swapped_constructor(run_root):
            runtime = RuntimeCommandService(run_root)
            swap()
            return runtime

        monkeypatch.setattr(
            "arw_artifact_integrity.service.RuntimeCommandService", swapped_constructor
        )
    with pytest.raises(ArtifactOperationError):
        sanitize(root, request)
    assert tree(outside) == outside_before
