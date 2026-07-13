from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from tests.file_plane_helpers import snapshot_tree


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update({"PYTHONNOUSERSITE": "1", "UV_OFFLINE": "1"})
    return subprocess.run(
        [sys.executable, "-m", "arw.cli", *arguments],
        cwd=REPOSITORY_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )


def _service(control_root: Path, *, builder: Path | None = None):
    from arw.files import FilesAdminService

    identifiers = iter(
        [
            "rootinst_test_001",
            "generation_test_001",
            "receipt_test_001",
            "attempt_test_001",
            "generation_test_002",
            "receipt_test_002",
            "attempt_test_002",
            "generation_test_003",
            "receipt_test_003",
            "attempt_test_003",
        ]
    )
    return FilesAdminService(
        control_root,
        native_builder=builder,
        id_factory=lambda _kind: next(identifiers),
        clock=lambda: "2026-07-14T00:00:00Z",
    )


def _write_root(root: Path) -> None:
    (root / "papers").mkdir(parents=True)
    (root / "papers/current.md").write_text("# Current\n\ncurrent evidence\n", encoding="utf-8")


def test_files_cli_uses_parent_only_resource_commands(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    _write_root(root)
    control = tmp_path / "control"
    registered = _run_cli(
        "files",
        "root",
        "register",
        "--control-root",
        str(control),
        "--root-id",
        "research-root",
        "--root-path",
        str(root),
        "--policy-id",
        "research-files-v1",
    )
    assert registered.returncode == 0, registered.stderr
    assert json.loads(registered.stdout)["root_id"] == "research-root"

    synced = _run_cli(
        "files",
        "sync",
        "--control-root",
        str(control),
        "--root-id",
        "research-root",
        "--extractor-version",
        "1.0.0",
    )
    assert synced.returncode == 0, synced.stderr
    assert json.loads(synced.stdout)["selected_generation_id"]

    status = _run_cli(
        "files",
        "status",
        "--control-root",
        str(control),
        "--root-id",
        "research-root",
    )
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["selected_generation"]["generation_id"]


def test_parent_only_admin_commands_build_complete_sibling_generation(tmp_path: Path) -> None:
    from arw.files import load_selected_generation

    root = tmp_path / "research root"
    root.mkdir()
    _write_root(root)
    before = snapshot_tree(root)
    service = _service(tmp_path / "control")
    registered = service.register_root(
        root_id="research-root",
        root_path=root,
        policy_id="research-files-v1",
    )
    assert registered.root_id == "research-root"

    receipt = service.sync("research-root", extractor_version="1.0.0")
    assert receipt.status == "complete"
    assert receipt.selected_generation_id == receipt.candidate_generation_id
    selected = load_selected_generation(service.control_root, "research-root")
    assert selected.generation_id == receipt.selected_generation_id
    generation = service.generation_path("research-root", selected.generation_id)
    assert (generation / "identity-manifest.json").is_file()
    assert (generation / "generation-manifest.json").is_file()
    assert (generation / "files.sqlite3").is_file()
    assert not list(generation.parent.glob(".building-*"))
    assert snapshot_tree(root) == before

    connection = sqlite3.connect(f"file:{generation / 'files.sqlite3'}?mode=ro", uri=True)
    try:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT relative_path FROM files").fetchall() == [
            ("papers/current.md",)
        ]
    finally:
        connection.close()


def test_failed_generation_preserves_selected_pointer_and_emits_receipt(tmp_path: Path) -> None:
    from arw.files import FilesAdminError, load_selected_generation

    root = tmp_path / "root"
    root.mkdir()
    _write_root(root)
    service = _service(tmp_path / "control")
    service.register_root(root_id="research-root", root_path=root, policy_id="research-files-v1")
    first = service.sync("research-root", extractor_version="1.0.0")
    selected_before = load_selected_generation(service.control_root, "research-root")
    pointer_path = service.root_control_path("research-root") / "selected-generation.json"
    pointer_before = pointer_path.read_bytes()
    (root / "papers/current.md").write_text("# Changed\n\nstale canary\n", encoding="utf-8")

    reached: list[str] = []

    def failpoint(name: str) -> None:
        reached.append(name)
        if name == "before_promote":
            raise FilesAdminError("injected_failure", "stop before pointer replacement")

    with pytest.raises(FilesAdminError, match="stop before pointer"):
        service.sync("research-root", extractor_version="1.0.0", failpoint=failpoint)
    assert reached == ["scan_complete", "index_complete", "manifest_closed", "before_promote"]
    assert pointer_path.read_bytes() == pointer_before
    assert load_selected_generation(service.control_root, "research-root") == selected_before
    receipts = sorted((service.root_control_path("research-root") / "receipts").glob("*.json"))
    blocked = json.loads(receipts[-1].read_text(encoding="utf-8"))
    assert blocked["status"] == "blocked"
    assert blocked["selected_generation_id"] == first.selected_generation_id
    assert "injected_failure" in blocked["blocking_reasons"]
    assert not list((service.root_control_path("research-root") / "generations").glob(".building-*"))
