#!/usr/bin/env python3
"""Transform a Codex-staged ARW plugin into a Claude Code plugin + marketplace."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
from pathlib import Path


PLUGIN_NAME = "academic-research-workbench"
FORBIDDEN_SYMLINK_MSG = "refusing symlink in Claude plugin tree"


class BuildError(RuntimeError):
    pass


def _fail(message: str, code: int = 1) -> None:
    raise SystemExit(f"build_claude_plugin: {message}") from None


def _ensure_no_symlink(path: Path) -> None:
    if path.is_symlink():
        raise BuildError(f"{FORBIDDEN_SYMLINK_MSG}: {path}")


def _copy_tree_no_symlinks(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    for root, dirnames, filenames in os.walk(src, followlinks=False):
        root_path = Path(root)
        rel = root_path.relative_to(src)
        target_dir = dst / rel
        _ensure_no_symlink(root_path)
        target_dir.mkdir(parents=True, exist_ok=True)
        # Reject symlinked directories early.
        for dirname in list(dirnames):
            child = root_path / dirname
            if child.is_symlink():
                raise BuildError(f"{FORBIDDEN_SYMLINK_MSG}: {child}")
        for filename in filenames:
            source_file = root_path / filename
            if source_file.is_symlink():
                raise BuildError(f"{FORBIDDEN_SYMLINK_MSG}: {source_file}")
            target_file = target_dir / filename
            shutil.copy2(source_file, target_file)


def _write_text(path: Path, text: str, *, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mode is not None:
        path.chmod(mode)


def _write_json(path: Path, payload: object) -> None:
    _write_text(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def _rewrite_workbench_skill(text: str) -> str:
    replacements = (
        (
            "when delegation is later requested, use native Codex subagents\n"
            "with immutable assignment-injected ARS role instructions.",
            "when delegation is later requested, use Claude Code subagents\n"
            "with immutable assignment-injected ARS role instructions.",
        ),
        (
            "The companion hook is\n"
            "observational only, may be skipped until trusted, and is never an authorization or\n"
            "canonical-state boundary.",
            "The companion Claude plugin hook is\n"
            "observational only, may be skipped until trusted, and is never an authorization or\n"
            "canonical-state boundary.",
        ),
    )
    for old, new in replacements:
        if old in text:
            text = text.replace(old, new)
    # Broader single-line fallbacks if wrapping differs.
    text = text.replace("native Codex subagents", "Claude Code subagents")
    text = text.replace("Codex subagents", "Claude Code subagents")
    return text


def _rewrite_suite_skill(text: str) -> str:
    """Prefer Claude-native commands/hooks; keep integrity and routing rules."""
    codex_mapping_header = "## Codex Runtime Mapping"
    claude_section = """## Claude Code Runtime Notes

This package is installed as a Claude Code plugin. Prefer native surfaces:

| Surface | Claude behavior |
|---|---|
| `/ars-*` slash commands | Registered from plugin-root `commands/ars-*.md` (materialized from `ars/commands/`). |
| SessionStart / Stop / SubagentStop | ARW observational hook (`hooks/arw_hook_claude.py`) writes receipts only; never authorizes gates or provenance. |
| PreToolUse write guard | Optional ARS `run_guard.sh` hardening; graceful pass-through if Python is unavailable. Not ledger authority. |
| Agent Team / subagent | Use Claude Code subagents when the user explicitly asks; otherwise read `ars/*/agents/*.md` as role prompts inline. |
| `codex/` directory | Historical Codex adapter profile. Not the default Claude execution plane. |
| Material Passport / integrity validators | Unchanged; run vendored validators when the active workflow requires them. |
| Cross-model verification | Still disabled by default; requires explicit provider configuration and user consent. |

### Compatibility note for vendored ARS wording

Upstream ARS workflows were authored for Claude Code. On this Claude install, interpret Claude-native tool and session wording literally. Treat residual Codex-only adapter docs under `skills/academic-research-suite/codex/` as non-default reference material.

"""
    if codex_mapping_header in text:
        before, _, after = text.partition(codex_mapping_header)
        # Drop the Codex mapping section through the next ## heading.
        rest = after
        # after begins with the rest of the heading line + body
        lines = rest.splitlines(keepends=True)
        # skip first line (remainder of heading already consumed via partition - actually
        # partition keeps separator out of before/after; after starts with "\n\nThe upstream...")
        # Wait: partition(separator) -> before, sep, after where after starts AFTER separator.
        # So after starts with "\n\nThe upstream..."
        body_lines = lines
        cut = 0
        # Skip leading blank lines then content until next ## at beginning
        seen_content = False
        for index, line in enumerate(body_lines):
            if line.startswith("## ") and seen_content:
                cut = index
                break
            if line.strip():
                seen_content = True
        else:
            cut = len(body_lines)
        text = before + claude_section + "".join(body_lines[cut:])
    else:
        text = text.rstrip() + "\n\n" + claude_section

    text = text.replace(
        "If the Codex client reserves slash-prefixed input before it reaches the model,\n"
        "tell the user to use the plain alias form, for example `ars-plan my topic`.\n",
        "Slash commands are registered natively; if a client strips the leading `/`, "
        "accept the plain alias form, for example `ars-plan my topic`.\n",
    )
    text = text.replace(
        "respect Codex\napproval and filesystem constraints.",
        "respect Claude Code\napproval and filesystem constraints.",
    )
    text = text.replace(
        "respect Codex approval and filesystem constraints.",
        "respect Claude Code approval and filesystem constraints.",
    )
    return text


def _materialize_commands(plugin_root: Path) -> int:
    source = plugin_root / "skills/academic-research-suite/ars/commands"
    if not source.is_dir():
        raise BuildError("staged ARS commands directory is missing")
    target = plugin_root / "commands"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    count = 0
    for path in sorted(source.glob("ars-*.md")):
        if path.is_symlink():
            raise BuildError(f"{FORBIDDEN_SYMLINK_MSG}: {path}")
        shutil.copy2(path, target / path.name)
        count += 1
    if count == 0:
        raise BuildError("no ars-*.md commands to materialize")
    return count


def _rewrite_mcp(plugin_root: Path) -> None:
    mcp_path = plugin_root / ".mcp.json"
    if not mcp_path.is_file():
        raise BuildError(".mcp.json missing from stage")
    payload = json.loads(mcp_path.read_text(encoding="utf-8"))
    servers = payload.get("mcpServers")
    if not isinstance(servers, dict) or "file-base" not in servers:
        raise BuildError(".mcp.json missing file-base server")
    entry = servers["file-base"]
    if not isinstance(entry, dict):
        raise BuildError("file-base MCP entry must be an object")
    entry["command"] = "${CLAUDE_PLUGIN_ROOT}/scripts/file-base-mcp"
    _write_json(mcp_path, payload)


def transform(
    *,
    project_root: Path,
    stage_root: Path,
    claude_stage_root: Path,
    marketplace_root: Path,
) -> dict[str, object]:
    packaging = project_root / "packaging/claude"
    for required in (
        packaging / "plugin.json",
        packaging / "claude-hooks.json",
        packaging / "marketplace.json.template",
        project_root / "hooks/arw_hook_claude.py",
    ):
        if not required.is_file() or required.is_symlink():
            raise BuildError(f"missing packaging input: {required}")

    if not (stage_root / ".codex-plugin/plugin.json").is_file():
        raise BuildError(
            f"Codex staged plugin missing at {stage_root}; run scripts/stage-plugin first"
        )
    if not (stage_root / "skills/academic-research-suite/SKILL.md").is_file():
        raise BuildError("staged modified ARS skill is missing")
    if not (stage_root / "hooks/hooks.json").is_file():
        raise BuildError("staged Codex hooks/hooks.json is missing")
    if not (stage_root / "hooks/arw_hook.py").is_file():
        raise BuildError("staged Codex hooks/arw_hook.py is missing")

    _copy_tree_no_symlinks(stage_root, claude_stage_root)

    # Keep .codex-plugin + Codex hooks/hooks.json so integration-lock / host
    # canary can still bind this tree. Claude-specific hooks are additive.
    if not (claude_stage_root / ".codex-plugin/plugin.json").is_file():
        raise BuildError("Claude stage lost .codex-plugin during copy")

    plugin_manifest = json.loads((packaging / "plugin.json").read_text(encoding="utf-8"))
    if plugin_manifest.get("hooks") != "./hooks/claude-hooks.json":
        raise BuildError("Claude plugin.json must declare ./hooks/claude-hooks.json only")
    _write_json(claude_stage_root / ".claude-plugin/plugin.json", plugin_manifest)

    claude_hooks = (packaging / "claude-hooks.json").read_text(encoding="utf-8")
    if "${PLUGIN_ROOT}" in claude_hooks:
        raise BuildError("Claude hooks template must not reference ${PLUGIN_ROOT}")
    if "${CLAUDE_PLUGIN_ROOT}" not in claude_hooks:
        raise BuildError("Claude hooks template must reference ${CLAUDE_PLUGIN_ROOT}")
    _write_text(claude_stage_root / "hooks/claude-hooks.json", claude_hooks)

    codex_hooks = (claude_stage_root / "hooks/hooks.json").read_text(encoding="utf-8")
    if "${PLUGIN_ROOT}" not in codex_hooks:
        raise BuildError("preserved Codex hooks/hooks.json must keep ${PLUGIN_ROOT}")

    claude_hook = project_root / "hooks/arw_hook_claude.py"
    target_hook = claude_stage_root / "hooks/arw_hook_claude.py"
    shutil.copy2(claude_hook, target_hook)
    target_hook.chmod(target_hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    _rewrite_mcp(claude_stage_root)
    command_count = _materialize_commands(claude_stage_root)

    workbench_skill = claude_stage_root / "skills/academic-research-workbench/SKILL.md"
    suite_skill = claude_stage_root / "skills/academic-research-suite/SKILL.md"
    _write_text(workbench_skill, _rewrite_workbench_skill(workbench_skill.read_text(encoding="utf-8")))
    _write_text(suite_skill, _rewrite_suite_skill(suite_skill.read_text(encoding="utf-8")))

    # Marketplace assembly
    if marketplace_root.exists():
        shutil.rmtree(marketplace_root)
    plugin_dest = marketplace_root / "plugins" / PLUGIN_NAME
    _copy_tree_no_symlinks(claude_stage_root, plugin_dest)

    marketplace = json.loads(
        (packaging / "marketplace.json.template").read_text(encoding="utf-8")
    )
    _write_json(marketplace_root / ".claude-plugin/marketplace.json", marketplace)

    # Final hard checks on marketplace plugin
    if not (plugin_dest / ".claude-plugin/plugin.json").is_file():
        raise BuildError("marketplace plugin missing .claude-plugin/plugin.json")
    if not (plugin_dest / ".codex-plugin/plugin.json").is_file():
        raise BuildError("marketplace plugin must retain .codex-plugin for lock binding")
    if not (plugin_dest / "hooks/claude-hooks.json").is_file():
        raise BuildError("marketplace plugin missing hooks/claude-hooks.json")
    if "${PLUGIN_ROOT}" not in (plugin_dest / "hooks/hooks.json").read_text(encoding="utf-8"):
        raise BuildError("marketplace Codex hooks/hooks.json lost ${PLUGIN_ROOT}")
    if "${PLUGIN_ROOT}" in (plugin_dest / "hooks/claude-hooks.json").read_text(encoding="utf-8"):
        raise BuildError("claude-hooks.json must not reference ${PLUGIN_ROOT}")

    return {
        "plugin_name": PLUGIN_NAME,
        "claude_stage": str(claude_stage_root),
        "marketplace": str(marketplace_root),
        "commands_materialized": command_count,
        "hooks": "codex-preserved+claude-additional",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--stage-root", type=Path, required=True)
    parser.add_argument("--claude-stage-root", type=Path, required=True)
    parser.add_argument("--marketplace-root", type=Path, required=True)
    args = parser.parse_args(argv)

    project_root = args.project_root.resolve()
    stage_root = args.stage_root.resolve()
    claude_stage_root = args.claude_stage_root.resolve()
    marketplace_root = args.marketplace_root.resolve()

    for label, path in (
        ("stage-root", stage_root),
        ("claude-stage-root", claude_stage_root),
        ("marketplace-root", marketplace_root),
    ):
        if path in {Path("/"), project_root}:
            _fail(f"refusing unsafe {label}")

    if claude_stage_root == stage_root or marketplace_root == stage_root:
        _fail("refusing to overwrite the Codex stage root")

    try:
        summary = transform(
            project_root=project_root,
            stage_root=stage_root,
            claude_stage_root=claude_stage_root,
            marketplace_root=marketplace_root,
        )
    except BuildError as error:
        print(f"build_claude_plugin: {error}", file=sys.stderr)
        return 66

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
