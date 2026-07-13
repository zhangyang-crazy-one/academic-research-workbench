from __future__ import annotations

import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_phase2_verifier_refuses_to_clean_outside_owned_evidence_root(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "must-not-exist"
    result = subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts/verify-phase-2"),
            "--clean",
            "--evidence-root",
            str(outside),
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 64
    assert "must be below" in result.stderr
    assert not outside.exists()


def test_stage_plugin_refuses_to_clean_an_unowned_existing_directory(
    tmp_path: Path,
) -> None:
    unowned = tmp_path / "academic-research-workbench"
    unowned.mkdir()
    sentinel = unowned / "keep.txt"
    sentinel.write_text("must remain\n", encoding="utf-8")
    result = subprocess.run(
        [
            str(REPOSITORY_ROOT / "scripts/stage-plugin"),
            "--clean",
            "--stage-root",
            str(unowned),
            "--evidence-root",
            str(tmp_path / "evidence"),
        ],
        cwd=REPOSITORY_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 64
    assert "ownership inventory" in result.stderr
    assert sentinel.read_text(encoding="utf-8") == "must remain\n"
