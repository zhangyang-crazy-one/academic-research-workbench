"""The qualification wrapper rejects destructive root layouts before writing."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/prepare-qualified-stage"


@pytest.mark.parametrize(
    ("stage_suffix", "evidence_suffix", "variable", "temporary_suffix", "message"),
    [
        ("accepted", "accepted", None, None, "must be disjoint"),
        ("accepted", "accepted/evidence", None, None, "must be disjoint"),
        ("accepted/stage", "accepted", None, None, "must be disjoint"),
        ("accepted", "evidence", "TMPDIR", "accepted/scratch", "temporary root"),
        ("accepted", "evidence", "TMPDIR", ".", "temporary root"),
        ("accepted", "evidence", "ARW_STAGE_TMP_ROOT", "accepted/scratch", "temporary root"),
        ("accepted", "evidence", "ARW_STAGE_TMP_ROOT", ".", "temporary root"),
    ],
)
def test_preflight_keeps_accepted_stage_untouched(
    tmp_path: Path,
    stage_suffix: str,
    evidence_suffix: str,
    variable: str | None,
    temporary_suffix: str | None,
    message: str,
) -> None:
    accepted = tmp_path / "accepted"
    accepted.mkdir()
    marker = accepted / "accepted.txt"
    marker.write_text("retained\n", encoding="utf-8")
    stage = tmp_path / stage_suffix
    evidence = tmp_path / evidence_suffix
    env = os.environ.copy()
    env["ARW_BUILD_PYTHON"] = sys.executable
    env.pop("TMPDIR", None)
    env.pop("ARW_STAGE_TMP_ROOT", None)
    if variable is not None:
        assert temporary_suffix is not None
        env[variable] = str(tmp_path / temporary_suffix)

    result = subprocess.run(
        [str(SCRIPT), "--clean", "--stage-root", str(stage),
         "--evidence-root", str(evidence)],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )

    assert result.returncode == 64, result.stderr
    assert message in result.stderr
    assert marker.read_text(encoding="utf-8") == "retained\n"
    assert sorted(path.relative_to(accepted).as_posix() for path in accepted.rglob("*")) == [
        "accepted.txt"
    ]
    if evidence != accepted and accepted not in evidence.parents and evidence not in accepted.parents:
        assert not evidence.exists()


@pytest.mark.parametrize(
    ("variable", "unsafe_root"),
    [("TMPDIR", Path("/")), ("ARW_STAGE_TMP_ROOT", ROOT)],
)
def test_preflight_rejects_unsafe_temporary_root_before_stage_work(
    tmp_path: Path, variable: str, unsafe_root: Path,
) -> None:
    stage = tmp_path / "accepted"
    stage.mkdir()
    marker = stage / "accepted.txt"
    marker.write_text("retained\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    env = os.environ.copy()
    env["ARW_BUILD_PYTHON"] = sys.executable
    env.pop("TMPDIR", None)
    env.pop("ARW_STAGE_TMP_ROOT", None)
    env[variable] = str(unsafe_root)

    result = subprocess.run(
        [str(SCRIPT), "--clean", "--stage-root", str(stage),
         "--evidence-root", str(evidence)],
        cwd=ROOT, env=env, text=True, capture_output=True, check=False,
    )

    assert result.returncode == 64, result.stderr
    assert "unsafe temporary root" in result.stderr
    assert marker.read_text(encoding="utf-8") == "retained\n"
    assert not evidence.exists()
