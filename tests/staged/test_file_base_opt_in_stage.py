"""Executable issue #27 acceptance against explicitly supplied staged plugins.

Set ARW_ISSUE27_CODEX_STAGE and ARW_ISSUE27_CLAUDE_STAGE to stage roots built
from the current wheel. The test uses their real bin/arw and native binary.
"""

from __future__ import annotations

import json
import os
import subprocess
import tomllib
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("host", "stage_variable"),
    [
        pytest.param("codex", "ARW_ISSUE27_CODEX_STAGE", marks=pytest.mark.requires_retained_evidence("env:ARW_ISSUE27_CODEX_STAGE")),
        pytest.param("claude", "ARW_ISSUE27_CLAUDE_STAGE", marks=pytest.mark.requires_retained_evidence("env:ARW_ISSUE27_CLAUDE_STAGE")),
    ],
)
def test_staged_plugin_disabled_then_project_opt_in_reads_bounded_source(
    tmp_path: Path, host: str, stage_variable: str
) -> None:
    supplied = os.environ.get(stage_variable)
    assert supplied, f"set {stage_variable} to a staged plugin root"
    stage = Path(supplied).resolve(strict=True)
    launcher = stage / "bin/arw"
    assert launcher.is_file()
    assert json.loads((stage / ".mcp.json").read_text(encoding="utf-8")) == {
        "mcpServers": {}
    }

    project = tmp_path / "project"
    project.mkdir()
    (project / ".codex").mkdir()
    root = tmp_path / "research"
    root.mkdir()
    (root / "source.txt").write_text("Bounded research source.\n", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()
    runtime_home = Path(
        os.environ.get(
            "ARW_ISSUE27_RUNTIME_HOME", str(tmp_path.parent / "shared-codex-home")
        )
    )
    (tmp_path / "home").mkdir()
    (tmp_path / "tmp").mkdir()
    environment = {
        key: value
        for key, value in os.environ.items()
        if key != "ARW_PLUGIN_ROOT"
        and not key.startswith("CBM_")
        and not key.startswith("ARW_FILES_")
    }
    environment.update(
        HOME=str(tmp_path / "home"),
        CODEX_HOME=str(runtime_home),
        TMPDIR=str(tmp_path / "tmp"),
    )

    def cli(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(launcher), *args],
            cwd=project,
            env=environment,
            text=True,
            capture_output=True,
            timeout=120,
            check=False,
        )

    before = cli("health", "--json")
    assert before.returncode == 0, before.stderr
    before_health = json.loads(before.stdout)["file_base"]
    assert before_health["state"] == "disabled"
    assert before_health["bundle_state"] == "disabled"
    assert before_health["project_configs"][host] == "absent"

    target = project / (".codex/config.toml" if host == "codex" else ".mcp.json")
    enabled = cli(
        "files",
        "enable",
        "--provider",
        "native",
        "--host",
        host,
        "--target",
        str(target),
        "--root",
        str(root),
        "--root-id",
        "research",
        "--cache-dir",
        str(cache),
    )
    assert enabled.returncode == 0, enabled.stderr or enabled.stdout
    assert json.loads(enabled.stdout)["status"] == "enabled"
    config = (
        tomllib.loads(target.read_text(encoding="utf-8"))["mcp_servers"]
        if host == "codex"
        else json.loads(target.read_text(encoding="utf-8"))["mcpServers"]
    )
    server = config["file-base"]
    assert server["command"] == str(stage / "scripts/file-base-mcp")
    assert Path(server["command"]).is_file()
    assert server["env"]["CBM_ALLOWED_ROOT"] == str(root)
    assert server["env"]["CBM_CACHE_DIR"] == str(cache)
    assert "ARW_PLUGIN_ROOT" not in environment

    after = cli("health", "--json")
    assert after.returncode == 0, after.stderr
    after_health = json.loads(after.stdout)["file_base"]
    assert after_health["state"] == "enabled"
    assert after_health["bundle_state"] == "disabled"
    assert after_health["project_configs"][host] == "configured"

    read_request = {
        "schema_version": "1.0.0",
        "allowed_root": "research",
        "relative_path": "source.txt",
        "max_bytes": 64,
        "max_lines": 10,
    }
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "read_file", "arguments": read_request},
        },
    ]
    launched = subprocess.run(
        [server["command"]],
        cwd=project,
        env={**environment, **server["env"]},
        input="\n".join(json.dumps(item) for item in requests) + "\n",
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert launched.returncode == 0, launched.stderr
    responses = [json.loads(line) for line in launched.stdout.splitlines() if line]
    assert len(responses) == 2
    tools = [entry["name"] for entry in responses[0]["result"]["tools"]]
    assert "read_file" in tools
    read = json.loads(responses[1]["result"]["content"][0]["text"])
    assert read["status"] == "ok"
    assert read["content"] == "Bounded research source.\n"
    assert read["bytes_read"] <= read_request["max_bytes"]
