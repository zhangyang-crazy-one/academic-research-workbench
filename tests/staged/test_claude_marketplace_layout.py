"""Layout and host-rewrite checks for the Claude marketplace migration."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BUILDER = REPOSITORY_ROOT / "packaging/claude/build_claude_plugin.py"
CREATE = REPOSITORY_ROOT / "scripts/create-claude-marketplace"


def _write(path: Path, text: str, *, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(mode)


def _minimal_codex_stage(root: Path) -> None:
    _write(
        root / ".codex-plugin/plugin.json",
        json.dumps({"name": "academic-research-workbench", "version": "0.1.0"}) + "\n",
    )
    _write(
        root / ".mcp.json",
        json.dumps(
            {
                "mcpServers": {
                    "file-base": {
                        "command": "./scripts/file-base-mcp",
                        "env": {"CBM_DISABLE_UPDATE_CHECK": "1"},
                    }
                }
            },
            indent=2,
        )
        + "\n",
    )
    _write(
        root / "hooks/hooks.json",
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup|resume|clear|compact",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": 'python3 "${PLUGIN_ROOT}/hooks/arw_hook.py"',
                                }
                            ]
                        }
                    ]
                }
            },
            indent=2,
        )
        + "\n",
    )
    _write(root / "hooks/arw_hook.py", "#!/usr/bin/env python3\nprint('codex')\n", mode=0o755)
    _write(
        root / "skills/academic-research-workbench/SKILL.md",
        "---\nname: academic-research-workbench\ndescription: test\n---\n\n"
        "when delegation is later requested, use native Codex subagents\n"
        "with immutable assignment-injected ARS role instructions.\n"
        "The companion hook is\n"
        "observational only, may be skipped until trusted, and is never an authorization or\n"
        "canonical-state boundary.\n",
    )
    _write(
        root / "skills/academic-research-suite/SKILL.md",
        "---\nname: academic-research-suite\ndescription: test\n---\n\n"
        "If the Codex client reserves slash-prefixed input before it reaches the model,\n"
        "tell the user to use the plain alias form, for example `ars-plan my topic`.\n\n"
        "## Codex Runtime Mapping\n\n"
        "The upstream ARS files were written for Claude Code. Apply these mappings when\n"
        "using them in Codex:\n\n"
        "| Upstream wording | Codex behavior |\n"
        "|---|---|\n"
        "| Agent Team | inline |\n\n"
        "## Security Boundaries\n\n"
        "Any Bash execution must respect Codex\n"
        "approval and filesystem constraints.\n",
    )
    _write(
        root / "skills/academic-research-suite/ars/commands/ars-plan.md",
        "---\ndescription: plan\n---\n\n# plan\n",
    )
    _write(
        root / "skills/academic-research-suite/ars/commands/ars-full.md",
        "---\ndescription: full\n---\n\n# full\n",
    )
    _write(
        root / "skills/academic-research-suite/ars/scripts/announce-ars-loaded.sh",
        "#!/usr/bin/env bash\necho '{}'\n",
        mode=0o755,
    )
    _write(
        root / "skills/academic-research-suite/ars/hooks/run_guard.sh",
        "#!/bin/sh\necho '{}'\n",
        mode=0o755,
    )
    _write(root / "scripts/file-base-mcp", "#!/usr/bin/env bash\nexit 0\n", mode=0o755)
    _write(root / "bin/arw", "#!/usr/bin/env bash\nexit 0\n", mode=0o755)


def _build(tmp_path: Path) -> tuple[Path, Path]:
    stage = tmp_path / "codex-stage"
    claude_stage = tmp_path / "claude-stage" / "academic-research-workbench"
    marketplace = tmp_path / "claude-marketplace"
    _minimal_codex_stage(stage)
    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--project-root",
            str(REPOSITORY_ROOT),
            "--stage-root",
            str(stage),
            "--claude-stage-root",
            str(claude_stage),
            "--marketplace-root",
            str(marketplace),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return claude_stage, marketplace


def test_create_claude_marketplace_script_is_executable() -> None:
    assert CREATE.is_file()
    assert os.access(CREATE, os.X_OK)


def test_claude_marketplace_layout_and_host_rewrites(tmp_path: Path) -> None:
    claude_stage, marketplace = _build(tmp_path)
    plugin = marketplace / "plugins/academic-research-workbench"

    assert (plugin / ".claude-plugin/plugin.json").is_file()
    assert (marketplace / ".claude-plugin/marketplace.json").is_file()

    manifest = json.loads((plugin / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "academic-research-workbench"
    assert "interface" not in manifest
    # Codex hooks/hooks.json stays for lock binding; Claude hooks are additive.
    assert manifest["hooks"] == "./hooks/claude-hooks.json"
    assert (plugin / ".codex-plugin/plugin.json").is_file()
    assert (plugin / "hooks/hooks.json").is_file()
    assert (plugin / "hooks/claude-hooks.json").is_file()

    market = json.loads(
        (marketplace / ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
    )
    assert market["name"] == "arw-claude-local"
    assert market["plugins"][0]["source"] == "./plugins/academic-research-workbench"

    codex_hooks = (plugin / "hooks/hooks.json").read_text(encoding="utf-8")
    assert "${PLUGIN_ROOT}" in codex_hooks
    claude_hooks = (plugin / "hooks/claude-hooks.json").read_text(encoding="utf-8")
    assert "${CLAUDE_PLUGIN_ROOT}" in claude_hooks
    assert "${PLUGIN_ROOT}" not in claude_hooks
    assert "arw_hook_claude.py" in claude_hooks
    assert "announce-ars-loaded.sh" in claude_hooks
    assert "run_guard.sh" in claude_hooks

    assert (plugin / "hooks/arw_hook_claude.py").is_file()
    assert os.access(plugin / "hooks/arw_hook_claude.py", os.X_OK)

    mcp = json.loads((plugin / ".mcp.json").read_text(encoding="utf-8"))
    assert (
        mcp["mcpServers"]["file-base"]["command"]
        == "${CLAUDE_PLUGIN_ROOT}/scripts/file-base-mcp"
    )

    commands = sorted(path.name for path in (plugin / "commands").glob("ars-*.md"))
    assert commands == ["ars-full.md", "ars-plan.md"]

    workbench = (plugin / "skills/academic-research-workbench/SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "Claude Code subagents" in workbench
    assert "native Codex subagents" not in workbench

    suite = (plugin / "skills/academic-research-suite/SKILL.md").read_text(encoding="utf-8")
    assert "## Claude Code Runtime Notes" in suite
    assert "## Codex Runtime Mapping" not in suite
    assert "commands/ars-*.md" in suite
    assert "respect Claude Code" in suite

    # No symlinks in the marketplace plugin tree.
    for path in plugin.rglob("*"):
        assert not path.is_symlink(), path

    # Claude stage mirrors marketplace plugin essentials.
    assert (claude_stage / ".claude-plugin/plugin.json").is_file()
    assert (claude_stage / "commands/ars-plan.md").is_file()


def test_builder_rejects_missing_codex_stage(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(BUILDER),
            "--project-root",
            str(REPOSITORY_ROOT),
            "--stage-root",
            str(tmp_path / "missing"),
            "--claude-stage-root",
            str(tmp_path / "out"),
            "--marketplace-root",
            str(tmp_path / "market"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 66
    assert "missing" in result.stderr.lower() or "staged" in result.stderr.lower()
