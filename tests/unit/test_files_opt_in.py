"""Issue #27: file-base stays absent until a project opts in explicitly."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from arw.cli import main
from arw.files_opt_in import OptInError, enable, health


def _layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, Path, Path]:
    plugin = tmp_path / "plugin"
    (plugin / "scripts").mkdir(parents=True)
    (plugin / "libexec").mkdir()
    launcher = plugin / "scripts/file-base-mcp"
    launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    launcher.chmod(0o755)
    (plugin / ".mcp.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
    project = tmp_path / "project"
    (project / ".codex").mkdir(parents=True)
    root = tmp_path / "research"
    root.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    monkeypatch.setenv("ARW_PLUGIN_ROOT", str(plugin))
    return plugin, project, root, cache


def _enable(host: str, target: Path, root: Path, cache: Path) -> dict[str, object]:
    return enable(
        provider="native",
        host=host,
        target=target,
        root=root,
        root_id="research",
        cache_dir=cache,
    )


def test_missing_native_binary_is_structured_and_leaves_target_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, project, root, cache = _layout(tmp_path, monkeypatch)
    target = project / ".codex/config.toml"
    assert health(plugin)["state"] == "disabled"
    assert health(plugin)["native_binary"] == "missing"
    with pytest.raises(OptInError, match="native file-base binary") as error:
        _enable("codex", target, root, cache)
    assert error.value.code == "native_binary_missing"
    assert not target.exists()


def test_cli_returns_safe_json_diagnostic_without_creating_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _, project, root, cache = _layout(tmp_path, monkeypatch)
    target = project / ".codex/config.toml"
    code = main(
        [
            "files",
            "enable",
            "--provider",
            "native",
            "--host",
            "codex",
            "--target",
            str(target),
            "--root",
            str(root),
            "--root-id",
            "research",
            "--cache-dir",
            str(cache),
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert code == 65
    assert result["reason_code"] == "native_binary_missing"
    assert str(root) not in json.dumps(result)
    assert not target.exists()


def test_source_launcher_health_and_missing_binary_are_structured(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).resolve().parents[2]
    if (repository / "share/arw/wheels").is_dir() or (
        repository / "libexec/file-base-mcp"
    ).exists():
        pytest.skip("source-checkout preflight requires an unstaged checkout")
    project = tmp_path / "project"
    (project / ".codex").mkdir(parents=True)
    root = tmp_path / "research"
    root.mkdir()
    cache = tmp_path / "cache"
    cache.mkdir()
    launcher = repository / "bin/arw"
    ready = subprocess.run(
        [str(launcher), "health", "--json"], capture_output=True, text=True, check=False
    )
    assert ready.returncode == 0
    assert json.loads(ready.stdout)["file_base"]["reason_code"] == "opt_in_required"
    target = project / ".codex/config.toml"
    result = subprocess.run(
        [
            str(launcher),
            "files",
            "enable",
            "--provider",
            "native",
            "--host",
            "codex",
            "--target",
            str(target),
            "--root",
            str(root),
            "--root-id",
            "research",
            "--cache-dir",
            str(cache),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 65
    assert json.loads(result.stdout)["reason_code"] == "native_binary_missing"
    assert result.stderr == ""
    assert not target.exists()


def test_installed_launcher_missing_runtime_reports_json(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[2]
    plugin = tmp_path / "installed-plugin"
    (plugin / "bin").mkdir(parents=True)
    wheels = plugin / "share/arw/wheels"
    wheels.mkdir(parents=True)
    launcher = plugin / "bin/arw"
    shutil.copy2(repository / "bin/arw", launcher)
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": str(tmp_path / "home"),
        "CODEX_HOME": str(tmp_path / "codex-home"),
    }
    for arguments in (("health", "--json"), ("files", "enable")):
        result = subprocess.run(
            [str(launcher), *arguments],
            env=environment,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 66
        assert result.stderr == ""
        assert json.loads(result.stdout)["reason_code"] == "runtime_artifact_missing"

    (wheels / "academic_research_workbench-0.1.0-py3-none-any.whl").write_bytes(
        b"test wheel placeholder"
    )
    environment["ARW_PYTHON"] = "/nonexistent/issue27-python"
    result = subprocess.run(
        [str(launcher), "files", "enable"],
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 78
    assert result.stderr == ""
    assert json.loads(result.stdout)["reason_code"] == "interpreter_not_found"


def test_codex_enable_preserves_existing_settings_and_rejects_repeat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, project, root, cache = _layout(tmp_path, monkeypatch)
    native = plugin / "libexec/file-base-mcp"
    native.write_bytes(b"native-test")
    native.chmod(0o755)
    target = project / ".codex/config.toml"
    target.write_text('model = "example"\n', encoding="utf-8")
    result = _enable("codex", target, root, cache)
    assert result["status"] == "enabled"
    parsed = tomllib.loads(target.read_text(encoding="utf-8"))
    assert parsed["model"] == "example"
    server = parsed["mcp_servers"]["file-base"]
    assert server["command"] == str(plugin / "scripts/file-base-mcp")
    assert server["env"]["CBM_ALLOWED_ROOT"] == str(root)
    assert server["env"]["CBM_ALLOWED_ROOT_ID"] == "research"
    assert server["env"]["CBM_CACHE_DIR"] == str(cache)
    assert server["env"]["CBM_DISABLE_UPDATE_CHECK"] == "1"
    monkeypatch.chdir(project)
    assert health(plugin)["project_configs"] == {
        "codex": "configured",
        "claude": "absent",
    }
    assert health(plugin)["state"] == "enabled"
    assert health(plugin)["bundle_state"] == "disabled"
    before = target.read_bytes()
    with pytest.raises(OptInError) as error:
        _enable("codex", target, root, cache)
    assert error.value.code == "server_already_configured"
    assert target.read_bytes() == before


def test_health_cli_reports_enabled_project_with_disabled_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plugin, project, root, cache = _layout(tmp_path, monkeypatch)
    native = plugin / "libexec/file-base-mcp"
    native.write_bytes(b"native-test")
    native.chmod(0o755)
    _enable("codex", project / ".codex/config.toml", root, cache)
    monkeypatch.chdir(project)

    assert main(["health", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)["file_base"]
    assert report["state"] == "enabled"
    assert report["bundle_state"] == "disabled"
    assert report["project_configs"] == {"codex": "configured", "claude": "absent"}
    assert json.loads((plugin / ".mcp.json").read_text(encoding="utf-8")) == {
        "mcpServers": {}
    }


def test_new_target_fsync_failure_leaves_no_visible_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, project, root, cache = _layout(tmp_path, monkeypatch)
    native = plugin / "libexec/file-base-mcp"
    native.write_bytes(b"native-test")
    native.chmod(0o755)
    target = project / ".codex/config.toml"

    def failed_fsync(_fd: int) -> None:
        raise OSError("injected fsync failure")

    monkeypatch.setattr("arw.files_opt_in.os.fsync", failed_fsync)
    with pytest.raises(OptInError) as error:
        _enable("codex", target, root, cache)
    assert error.value.code == "target_write_failed"
    assert not target.exists()
    assert list(target.parent.glob(".arw-mcp-*")) == []


def test_new_target_appearance_is_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, project, root, cache = _layout(tmp_path, monkeypatch)
    native = plugin / "libexec/file-base-mcp"
    native.write_bytes(b"native-test")
    native.chmod(0o755)
    target = project / ".codex/config.toml"

    def competing_create(_source: Path, destination: Path) -> None:
        destination.write_text('model = "other"\n', encoding="utf-8")
        raise FileExistsError("target appeared")

    monkeypatch.setattr("arw.files_opt_in.os.link", competing_create)
    with pytest.raises(OptInError) as error:
        _enable("codex", target, root, cache)
    assert error.value.code == "target_changed"
    assert target.read_text(encoding="utf-8") == 'model = "other"\n'
    assert list(target.parent.glob(".arw-mcp-*")) == []


def test_claude_enable_preserves_other_servers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, project, root, cache = _layout(tmp_path, monkeypatch)
    native = plugin / "libexec/file-base-mcp"
    native.write_bytes(b"native-test")
    native.chmod(0o755)
    target = project / ".mcp.json"
    target.write_text(
        '{"mcpServers":{"other":{"command":"other"}},"extra":true}', encoding="utf-8"
    )
    _enable("claude", target, root, cache)
    parsed = json.loads(target.read_text(encoding="utf-8"))
    assert parsed["extra"] is True
    assert parsed["mcpServers"]["other"] == {"command": "other"}
    assert parsed["mcpServers"]["file-base"]["env"]["CBM_ALLOWED_ROOT"] == str(root)


def test_invalid_targets_and_roots_never_create_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, project, root, cache = _layout(tmp_path, monkeypatch)
    native = plugin / "libexec/file-base-mcp"
    native.write_bytes(b"native-test")
    native.chmod(0o755)
    target = project / ".codex/config.toml"
    link = tmp_path / "root-link"
    link.symlink_to(root, target_is_directory=True)
    with pytest.raises(OptInError) as error:
        _enable("codex", target, link, cache)
    assert error.value.code == "root_symlink"
    with pytest.raises(OptInError) as error:
        _enable("codex", project / "config.toml", root, cache)
    assert error.value.code == "invalid_project_target"
    with pytest.raises(OptInError) as error:
        _enable("codex", target, root, root)
    assert error.value.code == "cache_inside_root"
    with pytest.raises(OptInError) as error:
        _enable("claude", plugin / ".mcp.json", root, cache)
    assert error.value.code == "bundled_config_target_denied"
    assert not target.exists()


def test_custom_codex_home_and_managed_plugin_targets_are_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, project, root, cache = _layout(tmp_path, monkeypatch)
    native = plugin / "libexec/file-base-mcp"
    native.write_bytes(b"native-test")
    native.chmod(0o755)
    target = project / ".codex/config.toml"
    monkeypatch.setenv("CODEX_HOME", str(project / ".codex"))
    with pytest.raises(OptInError) as error:
        _enable("codex", target, root, cache)
    assert error.value.code == "global_target_denied"
    assert not target.exists()

    monkeypatch.delenv("CODEX_HOME")
    (plugin / "share/arw/wheels").mkdir(parents=True)
    managed_project = plugin / "projects/example"
    (managed_project / ".codex").mkdir(parents=True)
    managed_target = managed_project / ".codex/config.toml"
    with pytest.raises(OptInError) as error:
        _enable("codex", managed_target, root, cache)
    assert error.value.code == "bundled_config_target_denied"
    assert not managed_target.exists()


def test_invalid_plugin_root_is_a_safe_diagnostic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plugin, project, root, cache = _layout(tmp_path, monkeypatch)
    native = plugin / "libexec/file-base-mcp"
    native.write_bytes(b"native-test")
    native.chmod(0o755)
    target = project / ".codex/config.toml"
    monkeypatch.setenv("ARW_PLUGIN_ROOT", "relative-plugin")
    with pytest.raises(OptInError) as error:
        _enable("codex", target, root, cache)
    assert error.value.code == "plugin_root_invalid"
    assert not target.exists()
    assert health()["reason_code"] == "plugin_root_invalid"
