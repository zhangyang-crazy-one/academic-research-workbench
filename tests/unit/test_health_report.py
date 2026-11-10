"""Health observes optional blockers without claiming release qualification."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arw.cli import main
from arw.health import health_report


@pytest.mark.parametrize(
    ("system", "tier"),
    [("Linux", "tier-1"), ("Darwin", "tier-2"), ("Windows", "unsupported")],
)
def test_health_preserves_platform_limits(
    monkeypatch: pytest.MonkeyPatch, system: str, tier: str
) -> None:
    monkeypatch.setattr("arw.platform_support.platform.system", lambda: system)
    report = health_report()
    assert report["platform"]["tier"] == tier
    assert report["status"] == "ok"
    assert "qualified" not in report


def test_direct_health_reports_invalid_optional_root_without_failing_core(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ARW_PLUGIN_ROOT", "relative-root")
    monkeypatch.setenv("ARW_RUNTIME_MODE", "agent")
    assert main(["health", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["runtime_mode"] == "agent"
    assert report["status"] == "ok"
    assert report["file_base"]["reason_code"] == "plugin_root_invalid"
    assert "launcher" in report["file_base"]["enable_command"]


def test_health_reports_enabled_project_missing_native_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin = tmp_path / "plugin"
    plugin.mkdir()
    (plugin / ".mcp.json").write_text('{"mcpServers": {}}')
    project = tmp_path / "project"
    (project / ".codex").mkdir(parents=True)
    config = project / ".codex/config.toml"
    config.write_text(
        '[mcp_servers.file-base]\ncommand="file-base"\n'
        '[mcp_servers.file-base.env]\nCBM_ALLOWED_ROOT="/research"\n'
        'CBM_ALLOWED_ROOT_ID="research"\nCBM_CACHE_DIR="/cache"\n'
    )
    before = config.read_bytes()
    monkeypatch.chdir(project)
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(plugin))
    report = health_report()
    assert report["status"] == "ok"
    assert report["file_base"]["state"] == "unavailable"
    assert report["file_base"]["reason_code"] == "native_binary_missing"
    assert "scripts/build-file-base" in report["file_base"]["recommendation"]
    assert config.read_bytes() == before
    assert not (plugin / "libexec").exists()
