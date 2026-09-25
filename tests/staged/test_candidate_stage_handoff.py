"""Fail closed before a candidate can replace an accepted plugin stage."""

from __future__ import annotations

import hashlib
import json
import os
import runpy
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STAGE = ROOT / "scripts/stage-plugin"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(STAGE), *args], cwd=ROOT, text=True, capture_output=True, check=False
    )


def test_stage_requires_explicit_candidate_without_rebuilding(tmp_path: Path) -> None:
    stage = tmp_path / "accepted-stage"
    stage.mkdir()
    inventory = stage / "supply-chain/stage-inventory.json"
    inventory.parent.mkdir()
    inventory.write_text("accepted\n", encoding="utf-8")

    result = _run("--clean", "--stage-root", str(stage), "--evidence-root", str(tmp_path / "stage-evidence"))

    assert result.returncode != 0
    assert "candidate" in result.stderr.lower()
    assert inventory.read_text(encoding="utf-8") == "accepted\n"
    assert "hatchling" not in result.stderr


def test_stage_rejects_substituted_wheel_before_touching_stage(tmp_path: Path) -> None:
    build_root = tmp_path / "build"
    wheel = build_root / "dist/academic_research_workbench-0.1.0-py3-none-any.whl"
    wheel.parent.mkdir(parents=True)
    wheel.write_bytes(b"candidate")
    evidence = {
        "artifacts": [{
            "kind": "wheel",
            "path": f"dist/{wheel.name}",
            "size": wheel.stat().st_size,
            "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        }],
        "build": {"python": {"version": "3.13.0"}},
    }
    build_evidence = build_root / "build-evidence.json"
    build_evidence.write_text(json.dumps(evidence), encoding="utf-8")
    wheel.write_bytes(b"substituted")
    gate = tmp_path / "gate"
    gate.mkdir()
    stage = tmp_path / "accepted-stage"
    stage.mkdir()
    marker = stage / "accepted.txt"
    marker.write_text("unchanged", encoding="utf-8")

    result = _run(
        "--clean", "--candidate-wheel", str(wheel),
        "--build-evidence", str(build_evidence),
        "--candidate-evidence-root", str(gate),
        "--stage-root", str(stage),
        "--evidence-root", str(tmp_path / "stage-evidence"),
    )

    assert result.returncode != 0
    assert "candidate" in result.stderr.lower()
    assert marker.read_text(encoding="utf-8") == "unchanged"


def test_stage_rejects_overlapping_roots_before_candidate_work(tmp_path: Path) -> None:
    stage = tmp_path / "accepted-stage"
    stage.mkdir()
    marker = stage / "accepted.txt"
    marker.write_text("unchanged", encoding="utf-8")
    nested = _run("--stage-root", str(stage), "--evidence-root", str(stage / "evidence"))
    assert nested.returncode != 0
    assert "must be disjoint" in nested.stderr
    assert marker.read_text(encoding="utf-8") == "unchanged"
    environment = os.environ.copy()
    environment["ARW_STAGE_TMP_ROOT"] = str(stage / "scratch")
    temporary = subprocess.run(
        [str(STAGE), "--stage-root", str(stage), "--evidence-root", str(tmp_path / "evidence")],
        cwd=ROOT, env=environment, text=True, capture_output=True, check=False,
    )
    assert temporary.returncode != 0
    assert "temporary root must be disjoint" in temporary.stderr
    assert not (stage / "scratch").exists()


def test_stage_rejects_rewritten_builder_metadata_before_touching_stage(tmp_path: Path) -> None:
    make_candidate = runpy.run_path(str(ROOT / "tests/integration/test_candidate_bundle.py"))["candidate"]
    build, evidence, wheel = make_candidate(tmp_path)
    payload = json.loads(build.read_text())
    payload["build"]["python"]["version"] = "3.99.0"
    build.write_text(json.dumps(payload), encoding="utf-8")
    stage = tmp_path / "accepted-stage"
    stage.mkdir()
    marker = stage / "accepted.txt"
    marker.write_text("unchanged", encoding="utf-8")
    result = _run("--clean", "--candidate-wheel", str(wheel), "--build-evidence", str(build),
                  "--candidate-evidence-root", str(evidence), "--stage-root", str(stage),
                  "--evidence-root", str(tmp_path / "stage-evidence"))
    assert result.returncode != 0
    assert "does not bind" in result.stderr
    assert marker.read_text(encoding="utf-8") == "unchanged"


def test_stage_rejects_license_inventory_build_hash_before_touching_stage(tmp_path: Path) -> None:
    make_candidate = runpy.run_path(str(ROOT / "tests/integration/test_candidate_bundle.py"))["candidate"]
    build, evidence, wheel = make_candidate(tmp_path)
    inventory_path = evidence / "license-evidence/inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["build_evidence"]["sha256"] = "0" * 64
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    stage = tmp_path / "accepted-stage"
    stage.mkdir()
    marker = stage / "accepted.txt"
    marker.write_text("unchanged", encoding="utf-8")
    result = _run("--clean", "--candidate-wheel", str(wheel),
                  "--build-evidence", str(build), "--candidate-evidence-root", str(evidence),
                  "--stage-root", str(stage), "--evidence-root", str(tmp_path / "stage-evidence"))
    assert result.returncode != 0
    assert "build evidence" in result.stderr
    assert marker.read_text(encoding="utf-8") == "unchanged"
