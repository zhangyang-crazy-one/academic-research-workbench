from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
CANARY_ROOT = REPOSITORY_ROOT / "tests/fixtures/private-canaries"
PLUGIN_NAME = "academic-research-workbench"


def _environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({"PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1", "PIP_NO_INDEX": "1"})
    return environment


def _run_stage(stage_root: Path, *, validate_only: bool = False) -> subprocess.CompletedProcess[str]:
    evidence_root = stage_root.parents[1] / "evidence"
    command = [
        str(REPOSITORY_ROOT / "scripts/stage-plugin"),
        "--stage-root",
        str(stage_root),
        "--evidence-root",
        str(evidence_root),
    ]
    if validate_only:
        command.append("--validate-only")
    else:
        command.insert(1, "--clean")
    return subprocess.run(
        command,
        cwd=REPOSITORY_ROOT,
        env=_environment(),
        text=True,
        capture_output=True,
        check=False,
    )


def _canaries() -> list[dict[str, str]]:
    payload = json.loads((CANARY_ROOT / "canaries.json").read_text(encoding="utf-8"))
    classes = {item["class"] for item in payload["canaries"]}
    assert classes == {
        "cache",
        "credentials",
        "extracted-text",
        "index",
        "paper",
        "run-data",
        "undeclared",
        "vcs-metadata",
    }
    return payload["canaries"]


def test_positive_allowlist_excludes_every_private_class_and_canary(tmp_path: Path) -> None:
    stage_root = tmp_path / "stage" / PLUGIN_NAME
    result = _run_stage(stage_root)
    assert result.returncode == 0, result.stderr

    staged_paths = {
        path.relative_to(stage_root).as_posix()
        for path in stage_root.rglob("*")
        if path.is_file() or path.is_symlink()
    }
    staged_bytes = b"\n".join(
        path.read_bytes() for path in stage_root.rglob("*") if path.is_file()
    )
    for canary in _canaries():
        assert canary["path"] not in staged_paths
        assert canary["token"].encode() not in staged_bytes

    forbidden_segments = {
        ".cache",
        ".git",
        "credentials",
        "extracted-text",
        "extractions",
        "generations",
        "indexes",
        "papers",
        "receipts",
        "runs",
    }
    assert not any(forbidden_segments & set(Path(path).parts) for path in staged_paths)
    assert not any(Path(path).suffix in {".db", ".sqlite", ".sqlite3"} for path in staged_paths)
    assert not any(path.is_symlink() for path in stage_root.rglob("*"))

    evidence_root = stage_root.parents[1] / "evidence"
    inventory_diff = json.loads((evidence_root / "inventory-diff.json").read_text(encoding="utf-8"))
    canary_scan = json.loads((evidence_root / "canary-scan.json").read_text(encoding="utf-8"))
    verdict = json.loads((evidence_root / "verdict.json").read_text(encoding="utf-8"))
    assert inventory_diff == {"missing": [], "unexpected": []}
    assert canary_scan["technical_qualification"] == "PASS"
    assert {item["class"] for item in canary_scan["canaries"]} == {
        item["class"] for item in _canaries()
    }
    assert all(item["present"] is False for item in canary_scan["canaries"])
    assert verdict == {
        "release_qualification": "BLOCKED",
        "technical_qualification": "PASS",
    }


@pytest.mark.parametrize("kind", ["undeclared-file", "absolute-symlink"])
def test_stage_validation_rejects_post_build_extras_and_symlinks(
    tmp_path: Path, kind: str
) -> None:
    stage_root = tmp_path / "stage" / PLUGIN_NAME
    staged = _run_stage(stage_root)
    assert staged.returncode == 0, staged.stderr

    if kind == "undeclared-file":
        injected = stage_root / "undeclared/private-canary.txt"
        injected.parent.mkdir(parents=True)
        injected.write_text("ARW-PRIVATE-UNDECLARED-CANARY-8E68F3\n", encoding="utf-8")
    else:
        injected = stage_root / "absolute-private-link"
        injected.symlink_to((CANARY_ROOT / "papers/private-paper.pdf").resolve())

    validated = _run_stage(stage_root, validate_only=True)
    assert validated.returncode != 0
    assert kind.split("-", 1)[-1] in validated.stderr.lower() or "allowlist" in validated.stderr.lower()


def test_graph_database_and_fixture_payloads_are_not_staged(tmp_path: Path) -> None:
    stage_root = tmp_path / "stage" / PLUGIN_NAME
    result = _run_stage(stage_root)
    assert result.returncode == 0, result.stderr
    paths = {path.relative_to(stage_root).as_posix() for path in stage_root.rglob("*") if path.is_file()}
    assert not any(path.endswith((".sqlite", ".sqlite3", ".db")) for path in paths)
    assert not any("generations/" in path or "graph.sqlite" in path for path in paths)
    assert not any("tests/fixtures/research-graph" in path for path in paths)
    validated = _run_stage(stage_root, validate_only=True)
    assert validated.returncode == 0, validated.stderr
