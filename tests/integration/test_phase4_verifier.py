from __future__ import annotations

import importlib.machinery
import importlib.util
import json
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = REPOSITORY_ROOT / "scripts/verify-phase-4"


def _verifier_module():
    loader = importlib.machinery.SourceFileLoader("arw_verify_phase4", str(VERIFIER_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_phase4_verifier_rejects_evidence_outside_owned_root(tmp_path: Path) -> None:
    verifier = _verifier_module()
    with pytest.raises(verifier.VerificationError) as error:
        verifier.validate_evidence_path(tmp_path / "outside")
    assert error.value.code == 64
    assert not (tmp_path / "outside").exists()


def test_phase4_verifier_refuses_to_clean_unowned_existing_root() -> None:
    verifier = _verifier_module()
    root = verifier.EVIDENCE_BASE / "phase-04-verifier-safety-unowned"
    root.mkdir(parents=True, exist_ok=True)
    sentinel = root / "keep.txt"
    sentinel.write_text("retain\n", encoding="ascii")
    try:
        with pytest.raises(verifier.VerificationError) as error:
            verifier.prepare_evidence_root(root, clean=True)
        assert error.value.code == 64
        assert sentinel.read_text(encoding="ascii") == "retain\n"
    finally:
        sentinel.unlink(missing_ok=True)
        root.rmdir()


def test_phase4_parent_evaluator_emits_all_48_without_sealed_labels(tmp_path: Path) -> None:
    verifier = _verifier_module()
    summary = verifier.evaluate_corpus(tmp_path)
    assert summary["total_cases"] == 48
    assert summary["development_cases"] == 32
    assert summary["sealed_parent_only_cases"] == 16
    assert sum(summary["family_counts"].values()) == 48
    rendered = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "corpus/case-results").glob("*.json")
    )
    assert "label_id" not in rendered
    assert "adjudication" not in rendered
    for path in (tmp_path / "corpus/case-results").glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert set(payload) == {
            "schema_version",
            "corpus_version",
            "case_id",
            "manifest_sha256",
            "authority_normalized_replay_sha256",
            "terminal_status",
            "execution_mode",
            "evidence_sha256",
            "sealed_parent_only",
        }


def test_phase4_verifier_does_not_treat_host_absence_as_pass(tmp_path: Path) -> None:
    verifier = _verifier_module()
    qualification = verifier.host_qualification(tmp_path, require_host=False)
    assert qualification["status"] == "BLOCKED"
    assert qualification["execution_mode"] == "blocked"
