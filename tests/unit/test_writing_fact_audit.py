"""Fact-lock checker resolution in source and bound installed plugin roots."""

import shutil
from pathlib import Path

from arw_writing.fact_audit import audit

ROOT = Path(__file__).resolve().parents[2]
CHECKER = (
    ROOT / "skills/academic-research-suite/codex/scripts/check_fact_locked_revision.py"
)
UPSTREAM = (
    ROOT
    / "skills/academic-research-suite/ars/scripts/check_revision_token_conservation.py"
)


def test_installed_root_runs_bundled_checker(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    checker = (
        root
        / "skills/academic-research-suite/codex/scripts/check_fact_locked_revision.py"
    )
    upstream = (
        root
        / "skills/academic-research-suite/ars/scripts/check_revision_token_conservation.py"
    )
    checker.parent.mkdir(parents=True)
    upstream.parent.mkdir(parents=True)
    shutil.copyfile(CHECKER, checker)
    shutil.copyfile(UPSTREAM, upstream)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(root))
    report = audit("The result was 5%.", "The result was 6%.")
    assert report["status"] == "available"
    assert report["mechanical_status"] == "failed"
    assert report["semantic_status"] == "human_review_required"


def test_missing_installed_checker_remains_unsupported(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    root.mkdir()
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(root))
    report = audit("The result was 5%.", "The result was 5%.")
    assert report["status"] == "unsupported"
    assert report["mechanical_status"] == "not_run"


def test_broken_installed_checker_reports_error(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    checker = (
        root
        / "skills/academic-research-suite/codex/scripts/check_fact_locked_revision.py"
    )
    checker.parent.mkdir(parents=True)
    checker.write_text("def broken(:\n")
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(root))
    report = audit("5%", "5%")
    assert report["status"] == "error"
    assert report["reason"] == "SyntaxError"


def test_installed_symlink_checker_and_root_rejected(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    checker = (
        root
        / "skills/academic-research-suite/codex/scripts/check_fact_locked_revision.py"
    )
    checker.parent.mkdir(parents=True)
    checker.symlink_to(CHECKER)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(root))
    assert audit("5%", "5%")["reason"] == "unsafe_checker_path"
    linked_root = tmp_path / "linked"
    linked_root.symlink_to(root, target_is_directory=True)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(linked_root))
    assert audit("5%", "5%")["status"] == "error"
