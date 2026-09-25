"""A real candidate retains one wheel identity through the local release handoff."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _run(*argv: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)
    assert result.returncode == 0, f"{argv!r}: {result.stdout}\n{result.stderr}"
    return result


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_real_candidate_stage_install_and_transfer(tmp_path: Path) -> None:
    canonical = [ROOT / "SBOM.cdx.json", ROOT / "vendor/source-manifest.json"]
    before = [_sha256(path) for path in canonical]
    candidate = tmp_path / "candidate"
    gate = tmp_path / "gate"
    stage = tmp_path / "stage"
    build = ROOT / "scripts/build-candidate"
    _run(sys.executable, str(build), "--output-root", str(candidate))
    build_evidence = candidate / "build-evidence.json"
    build_record = json.loads(build_evidence.read_text(encoding="utf-8"))
    wheel_row = next(row for row in build_record["artifacts"] if row["kind"] == "wheel")
    wheel = candidate / wheel_row["path"]
    digest = wheel_row["sha256"]
    assert _sha256(wheel) == digest

    _run(str(ROOT / "scripts/license-gate"), "--wheel", str(wheel),
         "--build-evidence", str(build_evidence), "--output-root", str(gate))
    _run(str(ROOT / "scripts/stage-plugin"), "--candidate-wheel", str(wheel),
         "--build-evidence", str(build_evidence), "--candidate-evidence-root", str(gate),
         "--stage-root", str(stage), "--evidence-root", str(tmp_path / "stage-evidence"))
    staged_wheel = stage / "share/arw/wheels" / wheel.name
    assert _sha256(staged_wheel) == digest

    smoke = tmp_path / "smoke"
    _run(str(ROOT / "scripts/smoke-staged-plugin"), "--install-cli",
         "--fresh-home", str(tmp_path / "installed-home"),
         "--evidence-root", str(smoke), str(stage))
    installed = json.loads((smoke / "plugin/runtime-bootstrap/installation-inventory.json").read_text())
    assert installed["source_wheel_sha256"] == digest
    assert installed["installed_package"] == {"name": "academic-research-workbench", "version": "0.1.0"}

    upload = tmp_path / "upload"
    _run(str(ROOT / "scripts/candidate-bundle"), "create", "--wheel", str(wheel),
         "--build-evidence", str(build_evidence), "--candidate-evidence-root", str(gate),
         "--output-root", str(upload))
    download = tmp_path / "download"
    shutil.copytree(upload, download)
    selected = tmp_path / "selected.txt"
    _run(str(ROOT / "scripts/candidate-bundle"), "verify", "--bundle-root", str(download),
         "--files-output", str(selected))
    assert download / "dist" / wheel.name in map(Path, selected.read_text().splitlines())
    assert _sha256(download / "dist" / wheel.name) == digest
    (download / "dist" / wheel.name).write_bytes(b"substituted")
    rejected = subprocess.run(
        [str(ROOT / "scripts/candidate-bundle"), "verify", "--bundle-root", str(download)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )
    assert rejected.returncode != 0
    assert "digest mismatch" in rejected.stderr
    assert [_sha256(path) for path in canonical] == before
