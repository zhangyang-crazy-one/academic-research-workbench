"""Regression coverage for retained qualification stage discovery."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from arw.kernel.policy import integration_lock
from tests import qualification_support


@pytest.fixture
def retained_qualification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo = tmp_path / "repo"
    stage = repo / "build/.submission-skill-acceptance-final.example/qualified-stage-v5"
    stage.mkdir(parents=True)
    evidence = repo / "build/evidence/submission-workflow-live-v3"
    (evidence / "host-canary").mkdir(parents=True)
    lock_path = evidence / "integration-lock.json"
    lock_bytes = b"retained-lock"
    lock_path.write_bytes(lock_bytes)
    canary_path = evidence / "host-canary/canary.json"
    canary_path.write_bytes(b"retained-canary")
    canary_sha = hashlib.sha256(canary_path.read_bytes()).hexdigest()
    stage_sha = "a" * 64
    lock = SimpleNamespace(
        hook=SimpleNamespace(
            host_canary_evidence_sha256=canary_sha,
            stage_sha256=stage_sha,
        )
    )
    summary = {
        "status": "PASS",
        "integration_lock": {"sha256": hashlib.sha256(lock_bytes).hexdigest()},
        "host_canary": {"sha256": canary_sha},
        "qualified_stage": {
            "path": stage.relative_to(repo).as_posix(),
            "sha256": stage_sha,
        },
    }
    summary_path = evidence / "acceptance-summary.json"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    launcher = tmp_path / "codex-launcher"
    native = tmp_path / "codex-native"
    monkeypatch.setattr(qualification_support, "REPOSITORY_ROOT", repo)
    monkeypatch.setattr(qualification_support.shutil, "which", lambda _: str(launcher))
    monkeypatch.setattr(
        integration_lock, "discover_codex_native_binary", lambda _: native
    )
    monkeypatch.setattr(integration_lock, "load_integration_lock", lambda _: lock)
    return SimpleNamespace(
        repo=repo,
        stage=stage,
        lock_path=lock_path,
        canary_path=canary_path,
        lock=lock,
        lock_bytes=lock_bytes,
        canary_sha=canary_sha,
        summary_path=summary_path,
        summary=summary,
        launcher=launcher,
        native=native,
    )


def test_acceptance_stage_exact_host_tuple_is_discovered(
    retained_qualification,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retained = retained_qualification
    verified = []

    def verify(lock, **kwargs):
        verified.append(kwargs)
        assert kwargs == {
            "stage_root": retained.stage,
            "codex_launcher": retained.launcher,
            "codex_native_binary": retained.native,
            "host_canary_evidence": retained.canary_path,
        }

    monkeypatch.setattr(integration_lock, "verify_integration_lock", verify)
    assert qualification_support.discover_bundled_qualification() == (
        retained.stage,
        retained.lock_path,
        retained.canary_path,
    )
    assert len(verified) == 1


@pytest.mark.parametrize("changed", ["launcher", "native"])
def test_acceptance_stage_rejects_stale_host_tuple(
    retained_qualification,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    retained = retained_qualification
    if changed == "launcher":
        monkeypatch.setattr(
            qualification_support.shutil,
            "which",
            lambda _: str(retained.launcher.with_name("other-launcher")),
        )
    else:
        monkeypatch.setattr(
            integration_lock,
            "discover_codex_native_binary",
            lambda _: retained.native.with_name("other-native"),
        )

    def verify(lock, **kwargs):
        if (kwargs["codex_launcher"], kwargs["codex_native_binary"]) != (
            retained.launcher,
            retained.native,
        ):
            raise integration_lock.IntegrationLockError("host tuple changed")

    monkeypatch.setattr(integration_lock, "verify_integration_lock", verify)
    assert qualification_support.discover_bundled_qualification() is None


@pytest.mark.parametrize(
    "damage",
    [
        "traversal",
        "absolute",
        "symlink",
        "malformed",
        "wrong_lock_sha",
        "wrong_stage_sha",
    ],
)
def test_acceptance_stage_rejects_unsafe_or_damaged_receipt(
    retained_qualification,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    damage: str,
) -> None:
    retained = retained_qualification
    summary = retained.summary
    outside = tmp_path / "outside-stage"
    outside.mkdir()
    if damage == "traversal":
        summary["qualified_stage"]["path"] = "build/../../outside-stage"
    elif damage == "absolute":
        summary["qualified_stage"]["path"] = str(outside)
    elif damage == "symlink":
        (retained.repo / "build/escaped-stage").symlink_to(
            outside, target_is_directory=True
        )
        summary["qualified_stage"]["path"] = "build/escaped-stage"
    elif damage == "wrong_lock_sha":
        summary["integration_lock"]["sha256"] = "0" * 64
    elif damage == "wrong_stage_sha":
        summary["qualified_stage"]["sha256"] = "0" * 64

    retained.summary_path.write_text(
        "{broken" if damage == "malformed" else json.dumps(summary),
        encoding="utf-8",
    )

    def unexpected_verify(*args, **kwargs):
        pytest.fail("untrusted stage reached integration lock verification")

    monkeypatch.setattr(integration_lock, "verify_integration_lock", unexpected_verify)
    assert qualification_support.discover_bundled_qualification() is None


def test_acceptance_stage_rejects_evidence_root_symlink_escape(
    retained_qualification,
) -> None:
    retained = retained_qualification
    evidence = retained.repo / "build/evidence"
    external_evidence = retained.repo.parent / "external-evidence"
    evidence.rename(external_evidence)
    evidence.symlink_to(external_evidence, target_is_directory=True)

    assert (
        qualification_support._acceptance_stage(
            retained.lock_path,
            retained.lock_bytes,
            retained.lock,
            retained.canary_sha,
        )
        is None
    )
