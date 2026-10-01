"""Fact-lock checker resolution in source and bound installed plugin roots."""

import shutil
from pathlib import Path

import pytest
from arw_writing.fact_audit import audit

ROOT = Path(__file__).resolve().parents[2]
CHECKER = (
    ROOT / "skills/academic-research-suite/codex/scripts/check_fact_locked_revision.py"
)
UPSTREAM = (
    ROOT
    / "skills/academic-research-suite/ars/scripts/check_revision_token_conservation.py"
)


def _installed_files(root):
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
    return checker, upstream


@pytest.mark.parametrize(
    ("revision", "expected_status"),
    [("The result was 5%.", "passed"), ("The result was 6%.", "failed")],
)
def test_installed_root_runs_bundled_checker(
    tmp_path, monkeypatch, revision, expected_status
):
    root = tmp_path / "installed"
    checker, upstream = _installed_files(root)
    shutil.copyfile(CHECKER, checker)
    shutil.copyfile(UPSTREAM, upstream)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(root))
    report = audit("The result was 5%.", revision)
    assert report["status"] == "available"
    assert report["mechanical_status"] == expected_status
    assert report["semantic_status"] == "human_review_required"
    assert report["report"]["schema"] == "arw.fact-locked-revision-report.v1"
    assert isinstance(report["report"]["findings"], list)


def test_missing_installed_checker_remains_unsupported(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    root.mkdir()
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(root))
    report = audit("The result was 5%.", "The result was 5%.")
    assert report["status"] == "unsupported"
    assert report["mechanical_status"] == "not_run"


def test_missing_or_nonregular_installed_dependency(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    checker, upstream = _installed_files(root)
    shutil.copyfile(CHECKER, checker)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(root))
    assert audit("5%", "5%")["status"] == "unsupported"
    upstream.mkdir()
    report = audit("5%", "5%")
    assert report["status"] == "error"
    assert report["reason"] == "unsafe_checker_path"


def test_broken_installed_checker_reports_error(tmp_path, monkeypatch):
    root = tmp_path / "installed"
    checker, upstream = _installed_files(root)
    checker.write_text("def broken(:\n")
    upstream.write_text("# regular dependency fixture\n")
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
    linked_parent = tmp_path / "linked_parent"
    linked_parent.symlink_to(tmp_path, target_is_directory=True)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(linked_parent / "installed"))
    assert audit("5%", "5%")["reason"] == "unsafe_checker_path"


@pytest.mark.parametrize(
    "target", ["dependency", "dependency_ancestor", "checker_ancestor"]
)
def test_installed_symlink_dependency_or_ancestor_rejected(
    tmp_path, monkeypatch, target
):
    root = tmp_path / "installed"
    checker, upstream = _installed_files(root)
    shutil.copyfile(CHECKER, checker)
    shutil.copyfile(UPSTREAM, upstream)
    if target == "dependency":
        upstream.unlink()
        upstream.symlink_to(UPSTREAM)
    else:
        path = upstream.parent if target == "dependency_ancestor" else checker.parent
        replacement = tmp_path / target
        path.rename(replacement)
        path.symlink_to(replacement, target_is_directory=True)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(root))
    report = audit("5%", "5%")
    assert report["status"] == "error"
    assert report["reason"] == "unsafe_checker_path"
    assert report["mechanical_status"] == "not_run"


@pytest.mark.parametrize(
    "body",
    [
        "value = 1\n",
        "audit = None\n",
        "def audit(source, revision):\n    return None\n",
        "def audit(source, revision):\n    return {}\n",
        "def audit(source, revision):\n    return {'passed': 1}\n",
    ],
)
def test_invalid_checker_contract_is_bounded(tmp_path, monkeypatch, body):
    root = tmp_path / "installed"
    checker, upstream = _installed_files(root)
    checker.write_text(body)
    upstream.write_text("# regular dependency fixture\n")
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(root))
    report = audit("5%", "5%")
    assert report["status"] == "error"
    assert report["reason"] == "TypeError"
    assert report["mechanical_status"] == "not_run"
    assert report["semantic_status"] == "human_review_required"


@pytest.mark.parametrize(
    "checker_report",
    [
        {"passed": True},
        {"schema": "other", "passed": True, "findings": []},
        {"schema": "arw.fact-locked-revision-report.v1", "passed": True},
        {
            "schema": "arw.fact-locked-revision-report.v1",
            "passed": False,
            "findings": [],
        },
        {
            "schema": "arw.fact-locked-revision-report.v1",
            "passed": True,
            "findings": {},
        },
        {
            "schema": "arw.fact-locked-revision-report.v1",
            "passed": True,
            "findings": [None],
        },
        {
            "schema": "arw.fact-locked-revision-report.v1",
            "passed": True,
            "findings": [{}],
        },
        {
            "schema": "arw.fact-locked-revision-report.v1",
            "passed": True,
            "findings": [
                {
                    "check": "F1",
                    "severity": "fail",
                    "detail": "changed",
                    "values": ["6"],
                }
            ],
        },
        {
            "schema": "arw.fact-locked-revision-report.v1",
            "passed": False,
            "findings": [
                {
                    "check": "F1",
                    "severity": "error",
                    "detail": "changed",
                    "values": ["6"],
                }
            ],
        },
        {
            "schema": "arw.fact-locked-revision-report.v1",
            "passed": False,
            "findings": [
                {"check": "F1", "severity": "fail", "detail": "changed", "values": [6]}
            ],
        },
        {
            "schema": "arw.fact-locked-revision-report.v1",
            "passed": False,
            "findings": [{"check": "F1", "severity": "fail", "values": ["6"]}],
        },
    ],
)
def test_malformed_checker_report_is_bounded(tmp_path, monkeypatch, checker_report):
    root = tmp_path / "installed"
    checker, upstream = _installed_files(root)
    checker.write_text(f"def audit(source, revision):\n    return {checker_report!r}\n")
    upstream.write_text("# regular dependency fixture\n")
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(root))
    report = audit("5%", "5%")
    assert report == {
        "status": "error",
        "reason": "TypeError",
        "mechanical_status": "not_run",
        "semantic_status": "human_review_required",
    }


@pytest.mark.parametrize("checker_report", [{}, {"passed": True}])
def test_malformed_report_survives_prepare_record_and_audit(
    tmp_path, monkeypatch, checker_report
):
    from arw_writing.service import WritingAuditService

    from tests.integration.test_research_artifacts import request
    from tests.integration.test_writing import prepared, proposal

    root = tmp_path / "installed"
    checker, upstream = _installed_files(root)
    checker.write_text(f"def audit(source, revision):\n    return {checker_report!r}\n")
    upstream.write_text("# regular dependency fixture\n")
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(root))

    _, service = prepared(tmp_path)
    candidate = service.prepare("artifact.manuscript", proposal())
    assert candidate["fact_lock"]["status"] == "error"
    assert candidate["verification"]["fact_lock"]["mechanical_status"] == "not_run"
    receipt = service.record(
        "artifact.manuscript", proposal(), request=request(service.run_root, 50)
    )
    assert receipt["status"] == "recorded"
    assert receipt["candidate_accepted"] is False
    report = WritingAuditService().audit_texts(
        "The result was 5%.", "The result was 5%.", detector_config={"detectors": []}
    )
    assert report["fact_lock"]["status"] == "error"
    assert report["fact_lock"]["mechanical_status"] == "not_run"
