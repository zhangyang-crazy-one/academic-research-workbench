"""Offline release observations and GitHub issue policy for vendor drift."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import vendor_drift as drift

SPEC = importlib.util.spec_from_loader(
    "vendor_drift_issue",
    SourceFileLoader("vendor_drift_issue", str(ROOT / "scripts/vendor-drift-issue")),
)
assert SPEC and SPEC.loader
issue = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(issue)


def manifests() -> tuple[dict, dict]:
    return drift.load_manifests(ROOT)


def observation(
    tag: str = "v3.22.1", status: str = "ahead", body: str = "citation security fix"
) -> dict:
    return {
        "release": {
            "tag_name": tag,
            "draft": False,
            "prerelease": False,
            "published_at": "2026-09-23T05:53:00Z",
            "body": body,
        },
        "compare": {"status": status},
    }


def both(status: str = "ahead") -> dict:
    return {
        "academic-research-skills": observation(status=status),
        "file-base": observation(tag="v0.11.0", status=status),
    }


@pytest.mark.parametrize(
    "compare,expected",
    [
        ("ahead", "drift"),
        ("identical", "current"),
        ("behind", "current"),
        ("diverged", "unknown"),
    ],
)
def test_commit_ancestry_classification(compare: str, expected: str) -> None:
    source, mcp = manifests()
    result = drift.report(source, mcp, both(compare))
    assert [row["status"] for row in result["sources"]] == [expected, expected]
    assert result["has_drift"] is (expected == "drift")
    assert issue.plan(result, [])["action"] == (
        "create" if expected == "drift" else "none"
    )


def test_missing_or_bad_release_is_unknown_and_never_writes() -> None:
    source, mcp = manifests()
    for observations in (
        {},
        {"academic-research-skills": {"release": observation()["release"]}},
        {"academic-research-skills": observation(tag="v3.22.1-rc1")},
        {
            "academic-research-skills": {
                **observation(),
                "release": {**observation()["release"], "prerelease": True},
            }
        },
    ):
        result = drift.report(source, mcp, observations)
        assert all(row["status"] == "unknown" for row in result["sources"])
        assert issue.plan(result, [])["action"] == "none"


def test_api_query_error_is_distinct_from_missing_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from urllib.error import URLError

    source, mcp = manifests()
    monkeypatch.setattr(
        drift, "get_json", lambda *args: (_ for _ in ()).throw(URLError("offline"))
    )
    observations = drift.online_observations(source, mcp)
    result = drift.report(source, mcp, observations)
    assert [row["reason"] for row in result["sources"]] == [
        "query_error",
        "query_error",
    ]
    assert [row["reason"] for row in drift.report(source, mcp, {})["sources"]] == [
        "metadata_unavailable"
    ] * 2


@pytest.mark.parametrize(
    "release_history,local_history,expected",
    [
        (["release", "local"], [], "ahead"),
        (["local"], [], "identical"),
        (["release"], ["local", "release"], "behind"),
        (["release"], ["local"], None),
    ],
)
def test_online_ancestry_uses_commit_metadata_only(
    monkeypatch: pytest.MonkeyPatch,
    release_history: list[str],
    local_history: list[str],
    expected: str | None,
) -> None:
    source, mcp = manifests()
    current = drift.sources(source, mcp)[0]["revision"]
    release_sha = "a" * 40
    calls = []

    def fake_api(url: str, token: str = "") -> list[dict]:
        calls.append(url)
        assert "/commits?sha=" in url and "/compare/" not in url
        names = local_history if f"sha={current}" in url else release_history
        return [{"sha": current if name == "local" else release_sha} for name in names]

    monkeypatch.setattr(drift, "get_api", fake_api)
    assert (
        drift.ancestry_status(
            "https://api.github.com/repos/example/repo", current, "v3.22.1", ""
        )
        == expected
    )
    assert calls


def test_release_notes_are_plain_bounded_and_links_are_allowlisted() -> None:
    source, mcp = manifests()
    observations = both()
    observations["academic-research-skills"] = observation(
        body="<script>alert(1)</script> @maintainer [click](https://evil.example)\u202e\n"
        + "x" * 9000
    )
    observations["academic-research-skills"]["release"]["html_url"] = (
        "https://evil.example/release"
    )
    result = drift.report(source, mcp, observations)
    body = result["issue_body"]
    assert len(body) <= drift.MAX_BODY
    assert len(result["sources"][0]["summary"]) <= drift.MAX_NOTES
    assert len(drift.clean_text("<" * 9000)) <= drift.MAX_NOTES
    assert "https://evil.example" not in body
    assert "<script>" not in body
    assert "@maintainer" not in body
    assert "\u202e" not in body
    assert (
        "https://github.com/Imbad0202/academic-research-skills/releases/tag/v3.22.1"
        in body
    )
    assert result == drift.report(source, mcp, observations)


def test_allowlist_and_manifest_bytes_are_unchanged(tmp_path: Path) -> None:
    source_path = ROOT / "vendor/source-manifest.json"
    before = source_path.read_bytes()
    source, mcp = manifests()
    assert [row["id"] for row in drift.sources(source, mcp)] == list(drift.SOURCES)
    with pytest.raises(ValueError, match="source identity"):
        altered = json.loads(json.dumps(source))
        next(item for item in altered["components"] if item["id"] == "file-base")[
            "upstream_url"
        ] = "https://evil.example/repo"
        drift.sources(altered, mcp)
    with pytest.raises(ValueError, match="disagree"):
        drift.sources(source, {**mcp, "upstream_commit": "0" * 40})
    fixture = tmp_path / "observations.json"
    fixture.write_text(json.dumps(both()), encoding="utf-8")
    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/vendor-drift-report"),
            "--fixture",
            str(fixture),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(run.stdout)["has_drift"]
    assert source_path.read_bytes() == before


def test_issue_plan_is_idempotent_and_fail_closed() -> None:
    source, mcp = manifests()
    result = drift.report(source, mcp, both())
    created = issue.plan(result, [])
    assert created["action"] == "create"
    existing = {"title": drift.TITLE, "body": created["body"], "number": 42}
    assert issue.plan(result, [existing]) == {"action": "none"}
    changed = {**existing, "body": drift.MARKER + "\nold"}
    assert issue.plan(result, [changed])["action"] == "update"
    with pytest.raises(ValueError, match="multiple"):
        issue.plan(result, [existing, {**existing, "number": 43}])
    with pytest.raises(ValueError, match="conflicting"):
        issue.plan(result, [{**existing, "body": "unmarked"}])


def test_issue_cli_fixture_is_no_write(tmp_path: Path) -> None:
    source, mcp = manifests()
    result = drift.report(source, mcp, both())
    issues = tmp_path / "issues.json"
    issues.write_text("[]", encoding="utf-8")
    env = {
        **os.environ,
        "ARW_DRIFT_REPORT_JSON": json.dumps(result),
        "GITHUB_REPOSITORY": "example/academic-research-workbench",
    }
    env.pop("GITHUB_TOKEN", None)
    run = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/vendor-drift-issue"),
            "--fixture-issues",
            str(issues),
        ],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(run.stdout)["action"] == "create"
    assert drift.MARKER in run.stderr


def test_workflow_is_read_only_except_single_report_job() -> None:
    workflow = yaml.load(
        (ROOT / ".github/workflows/vendor-drift.yml").read_text(),
        Loader=yaml.BaseLoader,
    )
    assert workflow["permissions"] == {}
    assert "schedule" in workflow["on"] and "workflow_dispatch" in workflow["on"]
    assert workflow["on"]["workflow_dispatch"]["inputs"]["dry_run"]["default"] == "true"
    check, reporter = workflow["jobs"]["check"], workflow["jobs"]["report"]
    assert check["permissions"] == {"contents": "read"}
    assert reporter["permissions"] == {"contents": "read", "issues": "write"}
    assert "needs.check.outputs.has_drift == 'true'" in reporter["if"]
    assert "inputs.dry_run == false" in reporter["if"]
    assert "github.ref == 'refs/heads/main'" in reporter["if"]
    for job in (check, reporter):
        for step in job["steps"]:
            if step.get("uses", "").startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] == "false"
                assert step["uses"] == "actions/checkout@v7"
            if step.get("uses", "").startswith("actions/setup-python@"):
                assert step["uses"] == "actions/setup-python@v7"
            assert "cache" not in json.dumps(step).lower()
    assert drift.MARKER == "<!-- arw:upstream-drift:v1 -->"
    assert drift.TITLE == "upstream-drift: pinned source releases"
