from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEED = REPOSITORY_ROOT / "tests/fixtures/recovery/seed"


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "arw.cli", *args],
        text=True,
        capture_output=True,
        check=False,
    )


def test_status_missing_root_is_read_only(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    result = _run("status", "--json", "--run-root", str(missing))
    assert result.returncode != 0
    assert not missing.exists()


def test_status_json_for_phase1_fixture_uses_versioned_contract(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    (run_root / "input").mkdir(parents=True)
    shutil.copyfile(SEED / "input/source.txt", run_root / "input/source.txt")
    initialized = _run(
        "init",
        "--run-root",
        str(run_root),
        "--request",
        str(SEED / "init-request.json"),
    )
    assert initialized.returncode == 0, initialized.stderr
    before = {p.relative_to(run_root): p.read_bytes() for p in run_root.rglob("*") if p.is_file()}
    result = _run("status", "--json", "--run-root", str(run_root))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["run_id"].startswith("run-")
    assert payload["current_stage"] == "initialized"
    assert payload["accepted_revision"] == 1
    assert payload["recovery_health"] == "healthy"
    after = {p.relative_to(run_root): p.read_bytes() for p in run_root.rglob("*") if p.is_file()}
    assert after == before
