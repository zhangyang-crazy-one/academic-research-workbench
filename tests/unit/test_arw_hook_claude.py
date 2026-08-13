"""Claude Code observational hook adapter tests."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPOSITORY_ROOT / "hooks" / "arw_hook_claude.py"
PACKAGING_HOOKS = REPOSITORY_ROOT / "packaging" / "claude" / "claude-hooks.json"


def _install_plugin_tree(tmp_path: Path) -> Path:
    root = tmp_path / "plugin"
    hooks = root / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy2(PACKAGING_HOOKS, hooks / "hooks.json")
    shutil.copy2(HOOK_SCRIPT, hooks / "arw_hook_claude.py")
    (hooks / "arw_hook_claude.py").chmod(0o755)
    return root


def _run_hook(
    payload: dict[str, object],
    *,
    plugin_root: Path,
    data_home: Path,
) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONNOUSERSITE": "1",
            "CLAUDE_PLUGIN_ROOT": str(plugin_root),
            "XDG_DATA_HOME": str(data_home),
            "HOME": str(data_home / "home"),
        }
    )
    # Drop PLUGIN_DATA so the Claude XDG path is exercised.
    environment.pop("PLUGIN_DATA", None)
    return subprocess.run(
        [sys.executable, str(plugin_root / "hooks" / "arw_hook_claude.py")],
        input=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        capture_output=True,
        env=environment,
        check=False,
    )


def _session_start() -> dict[str, object]:
    return {
        "session_id": "session-secret-001",
        "transcript_path": "/not/read/transcript.jsonl",
        "cwd": "/workspace/research",
        "hook_event_name": "SessionStart",
        "permission_mode": "default",
        "source": "startup",
    }


def _stop() -> dict[str, object]:
    return {
        "session_id": "session-secret-001",
        "transcript_path": None,
        "cwd": "/workspace/research",
        "hook_event_name": "Stop",
        "permission_mode": "ask",
        "stop_hook_active": False,
        "reason": "completed",
    }


def test_claude_hook_has_no_arw_import() -> None:
    source = HOOK_SCRIPT.read_text(encoding="utf-8")
    assert "import arw" not in source
    assert "from arw" not in source


def test_claude_session_start_is_observational(tmp_path: Path) -> None:
    plugin_root = _install_plugin_tree(tmp_path)
    data_home = tmp_path / "xdg"
    result = _run_hook(_session_start(), plugin_root=plugin_root, data_home=data_home)
    assert result.returncode == 0
    output = json.loads(result.stdout)
    assert output["continue"] is True
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "observational" in output["hookSpecificOutput"]["additionalContext"]
    assert "decision" not in output
    assert "permissionDecision" not in output.get("hookSpecificOutput", {})


def test_claude_stop_persists_redacted_receipt(tmp_path: Path) -> None:
    plugin_root = _install_plugin_tree(tmp_path)
    data_home = tmp_path / "xdg"
    result = _run_hook(_stop(), plugin_root=plugin_root, data_home=data_home)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"continue": True}

    receipt_root = (
        data_home / "academic-research-workbench" / "hook-observations" / "v1"
    )
    receipts = tuple(receipt_root.glob("*.json"))
    assert len(receipts) == 1
    body = receipts[0].read_bytes()
    receipt = json.loads(body)
    assert receipt["schema_version"] == "arw.claude-hook-observation.v1"
    assert receipt["host"] == "claude-code"
    assert receipt["authority"] == "observational"
    assert b"session-secret-001" not in body
    unsigned = dict(receipt)
    digest = unsigned.pop("receipt_sha256")
    canonical = (
        json.dumps(unsigned, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    assert hashlib.sha256(canonical).hexdigest() == digest


def test_claude_hook_fail_closed_without_plugin_layout(tmp_path: Path) -> None:
    # Empty tree: no hooks.json next to script via CLAUDE_PLUGIN_ROOT.
    empty_root = tmp_path / "empty"
    empty_root.mkdir()
    data_home = tmp_path / "xdg"
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONNOUSERSITE": "1",
            "CLAUDE_PLUGIN_ROOT": str(empty_root),
            "XDG_DATA_HOME": str(data_home),
            "HOME": str(data_home / "home"),
        }
    )
    environment.pop("PLUGIN_DATA", None)
    result = subprocess.run(
        [sys.executable, str(HOOK_SCRIPT)],
        input=json.dumps(_session_start()).encode("utf-8"),
        capture_output=True,
        env=environment,
        check=False,
    )
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["continue"] is True
    assert "failed closed" in output["systemMessage"]
    assert b"plugin-root" in result.stderr or b"hook-definition" in result.stderr


def test_claude_hook_rejects_unsupported_event(tmp_path: Path) -> None:
    plugin_root = _install_plugin_tree(tmp_path)
    payload = _session_start()
    payload["hook_event_name"] = "PreToolUse"
    result = _run_hook(payload, plugin_root=plugin_root, data_home=tmp_path / "xdg")
    assert result.returncode == 1
    assert b"unsupported-hook-event" in result.stderr
