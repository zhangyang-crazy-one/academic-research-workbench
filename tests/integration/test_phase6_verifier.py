from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
LOADER = importlib.machinery.SourceFileLoader("verify_phase_6", str(ROOT / "scripts/verify-phase-6"))
SPEC = importlib.util.spec_from_loader("verify_phase_6", LOADER)
assert SPEC and SPEC.loader
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


def test_evidence_root_is_repo_owned_and_symlink_free(tmp_path: Path) -> None:
    with pytest.raises(VERIFY.VerificationError):
        VERIFY.owned_root(tmp_path / "outside", clean=False)
    link = VERIFY.EVIDENCE_BASE / "phase6-test-link"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.unlink(missing_ok=True)
    link.symlink_to(tmp_path, target_is_directory=True)
    try:
        with pytest.raises(VERIFY.VerificationError):
            VERIFY.owned_root(link, clean=True)
    finally:
        link.unlink(missing_ok=True)


def test_canonical_bytes_reject_nonfinite_values() -> None:
    with pytest.raises(ValueError):
        VERIFY.canonical({"value": float("nan")})


def test_release_blockers_are_independent_of_technical_verdict() -> None:
    assert VERIFY.RELEASE_BLOCKERS == ("SUP-04", "P04-09", "permission_unresolved")


def test_stage_inventory_rejects_private_payload(tmp_path: Path) -> None:
    stage = tmp_path / "stage"
    (stage / "runs").mkdir(parents=True)
    (stage / "runs" / "private.json").write_text("secret", encoding="utf-8")
    with pytest.raises(VERIFY.VerificationError, match="private/generated"):
        VERIFY.stage_inventory(tmp_path / "evidence", stage)


def test_tree_digest_is_bound_to_worktree_state() -> None:
    first = VERIFY.tree_digest()
    assert len(first) == 64
    assert first == VERIFY.tree_digest()


def test_command_scans_untruncated_status_markers(tmp_path: Path) -> None:
    root = VERIFY.EVIDENCE_BASE / "phase6-status-scan"
    if root.exists():
        import shutil
        shutil.rmtree(root)
    owned = VERIFY.owned_root(root, clean=False)
    script = "import sys; sys.stdout.write('x' * 600000 + '\\nSKIPPED\\n')"
    with pytest.raises(VERIFY.VerificationError, match="skipped"):
        VERIFY.command(owned, "long-status", [str(VERIFY.PYTHON), "-c", script])
