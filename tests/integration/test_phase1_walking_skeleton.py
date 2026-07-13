from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_phase1_clean_evidence_gate_retains_every_required_domain(tmp_path: Path) -> None:
    script = REPOSITORY_ROOT / "scripts/verify-phase-1"
    evidence_root = tmp_path / "phase-01-evidence"
    result = subprocess.run(
        [str(script), "--clean", "--evidence-root", str(evidence_root)],
        cwd=REPOSITORY_ROOT,
        env={**os.environ, "PIP_NO_INDEX": "1", "PYTHONNOUSERSITE": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

    dossiers = [path for path in evidence_root.iterdir() if path.is_dir() and len(path.name) == 64]
    assert len(dossiers) == 1
    summary = json.loads((dossiers[0] / "summary.json").read_text(encoding="utf-8"))
    assert summary["technical_qualification"] == "PASS"
    assert summary["release_qualification"] == "BLOCKED"
    assert set(summary["domains"]) == {
        "confinement",
        "license-0002",
        "mcp-launcher",
        "native",
        "pre-vendor-license",
        "route",
        "runtime",
        "source",
        "stage",
        "version",
    }
    for domain in summary["domains"]:
        assert (dossiers[0] / domain).exists()
