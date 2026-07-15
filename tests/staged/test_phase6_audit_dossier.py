from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _stage(tmp_path: Path) -> Path:
    stage = tmp_path / "stage" / "academic-research-workbench"
    evidence = tmp_path / "evidence"
    environment = {
        **os.environ,
        "UV_OFFLINE": "1",
        "PYTHONNOUSERSITE": "1",
        "PIP_NO_INDEX": "1",
        "TMPDIR": str(ROOT / "build/tmp/phase-06"),
        "ARW_STAGE_TMP_ROOT": str(ROOT / "build/tmp/phase-06/staged-test"),
    }
    result = subprocess.run(
        [str(ROOT / "scripts/stage-plugin"), "--clean", "--stage-root", str(stage), "--evidence-root", str(evidence)],
        cwd=ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return stage


@pytest.fixture(scope="module")
def staged(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _stage(tmp_path_factory.mktemp("phase6-stage"))


def test_staged_phase6_artifacts_are_executable_and_private_free(staged: Path) -> None:
    stage = staged
    required = {
        "scripts/verify-phase-6",
        "docs/runtime/scientific-integrity.md",
        "schemas/v1/audit-dossier.schema.json",
        "share/arw/schemas/audit-dossier.schema.json",
        "share/arw/build-identity.json",
    }
    files = {p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()}
    assert required <= files
    assert not any(Path(p).suffix.lower() in {".db", ".sqlite", ".sqlite3", ".pem", ".key"} for p in files)
    assert not any(any(part.lower() in {"runs", "papers", "private", "credentials", "receipts", "indexes"} for part in Path(p).parts) for p in files)
    schema = json.loads((stage / "schemas/v1/audit-dossier.schema.json").read_text(encoding="utf-8"))
    assert schema["$id"].endswith("audit-dossier.schema.json")
    identity = json.loads((stage / "share/arw/build-identity.json").read_text(encoding="utf-8"))
    assert identity["staged_payloads"]


def test_staged_audit_schema_digest_is_bound_in_build_identity(staged: Path) -> None:
    stage = staged
    identity = json.loads((stage / "share/arw/build-identity.json").read_text(encoding="utf-8"))
    rows = {row["path"]: row["sha256"] for row in identity["staged_payloads"]}
    path = "share/arw/schemas/audit-dossier.schema.json"
    assert rows[path] == hashlib.sha256((stage / path).read_bytes()).hexdigest()
