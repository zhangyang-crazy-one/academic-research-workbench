from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _verifier_module():
    source = REPOSITORY_ROOT / "scripts/verify-phase-5"
    loader = importlib.machinery.SourceFileLoader("arw_verify_phase5", str(source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_verifier_rejects_unowned_or_symlinked_evidence_roots(tmp_path: Path) -> None:
    verifier = _verifier_module()
    with pytest.raises(verifier.VerificationError, match="below"):
        verifier.owned_root(tmp_path / "outside", clean=True)

    owned = verifier.EVIDENCE_BASE / "test-graph-verifier-owned-root"
    owned.mkdir(parents=True, exist_ok=True)
    (owned / verifier.MARKER).write_text("phase-5\n", encoding="ascii")
    link = verifier.EVIDENCE_BASE / "test-graph-verifier-link"
    link.unlink(missing_ok=True)
    link.symlink_to(owned, target_is_directory=True)
    try:
        with pytest.raises(verifier.VerificationError, match="symlink"):
            verifier.owned_root(link, clean=True)
    finally:
        link.unlink(missing_ok=True)
        for child in owned.iterdir():
            child.unlink()
        owned.rmdir()
