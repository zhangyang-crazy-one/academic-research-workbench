"""Fail-closed aggregation and release-boundary probes for Phase 7."""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import shutil
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _verifier_module():
    loader = importlib.machinery.SourceFileLoader("verify_phase7", str(ROOT / "scripts/verify-phase-7"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_prior_phase_graph_and_independence_receipts_are_exact() -> None:
    verifier = _verifier_module()
    receipts = verifier.validate_receipts()
    graph = receipts["phase5_graph"]
    independence = receipts["phase41_independence"]
    assert graph["technical_qualification"] == "PASS"
    assert graph["file_base_build_evidence_path"].endswith("build/stage/phase-05/.file-base/build-evidence.json")
    assert graph["requirements"] == ["GRAPH-01", "GRAPH-02", "GRAPH-03", "GRAPH-04", "GRAPH-05", "GRAPH-06", "VER-05"]
    assert independence["technical_qualification"] == "PASS"
    assert independence["case_result_count"] >= 48
    assert set(independence["independence_command_exit_sha256"]) == {"P04-05-T01", "P04-05-T02"}


def test_missing_file_base_receipt_fails_closed(tmp_path: Path) -> None:
    verifier = _verifier_module()
    phase5 = tmp_path / "phase-05"
    shutil.copytree(verifier.PHASE5_ROOT, phase5)
    (phase5 / "stage-tree.json").write_text(
        (phase5 / "stage-tree.json").read_text(encoding="utf-8").replace(
            '".file-base/build-evidence.json"', '".file-base/missing-build-evidence.json"'
        ),
        encoding="utf-8",
    )
    with pytest.raises(verifier.VerificationError, match="file-base/build-evidence.json"):
        verifier.validate_receipts(phase5_root=phase5)


def test_tampered_graph_verdict_fails_closed(tmp_path: Path) -> None:
    verifier = _verifier_module()
    phase5 = tmp_path / "phase-05"
    shutil.copytree(verifier.PHASE5_ROOT, phase5)
    verdict_path = phase5 / "verdict.json"
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    verdict["stage_identity_sha256"] = "0" * 64
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")
    with pytest.raises(verifier.VerificationError, match="stage identity is stale"):
        verifier.validate_receipts(phase5_root=phase5)


def test_tampered_independence_receipt_fails_closed(tmp_path: Path) -> None:
    verifier = _verifier_module()
    phase41 = tmp_path / "phase-04.1"
    shutil.copytree(verifier.PHASE41_ROOT, phase41)
    exit_path = phase41 / "commands/P04-05-T01/exit.json"
    exit_path.write_text('{"returncode":1}\n', encoding="utf-8")
    with pytest.raises(verifier.VerificationError, match="P04-05-T01 failed"):
        verifier.validate_receipts(phase41_root=phase41)


def test_technical_pass_keeps_legal_release_blocked() -> None:
    verifier = _verifier_module()
    result = verifier.aggregate_verdict(
        receipt_summary={"phase5_graph": {"technical_qualification": "PASS"}},
        stage_summary={"stage_sha256": "a" * 64},
        test_commands=[],
        license_summary={"technical_qualification": "PASS", "release_qualification": "BLOCKED"},
        git_head="b" * 40,
        git_tree="c" * 40,
    )
    assert result["technical_qualification"] == "PASS"
    assert result["release_qualification"] == "BLOCKED"
    assert {"SUP-04", "P04-09", "CC_BY_NC_PERMISSION_UNRESOLVED"} <= set(result["release_blockers"])
