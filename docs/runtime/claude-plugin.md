# Claude Code Plugin Packaging

Academic Research Workbench can be installed as a **Claude Code plugin** (skills +
slash commands + hooks + MCP + `bin/arw`), parallel to the Codex marketplace package.

This is a host packaging transform. It does **not** replace the Codex stage path and
does **not** claim `isolated_codex_exec` host parity for Phase 4 orchestration.

## Build

```bash
# Optional: rebuild the Codex-positive allowlist stage first
./scripts/stage-plugin --clean

# Transform stage → Claude plugin + local marketplace
./scripts/create-claude-marketplace

# Or stage then transform in one step:
./scripts/create-claude-marketplace --stage
```

Outputs:

| Path | Role |
|------|------|
| `build/claude-stage/academic-research-workbench/` | Claude plugin root |
| `build/claude-marketplace/` | Local marketplace (`arw-claude-local`) |

Templates and the transform live under `packaging/claude/`. The Claude hook adapter is
`hooks/arw_hook_claude.py`.

## Install

CLI (durable user scope; also what Cursor can pick up from `~/.claude/plugins/`):

```bash
./scripts/create-claude-marketplace   # refresh build/claude-marketplace if needed
claude plugin marketplace add "$(pwd)/build/claude-marketplace"
claude plugin install academic-research-workbench@arw-claude-local -s user
claude plugin list   # expect Status: enabled
```

Or inside Claude Code:

```text
/plugin marketplace add <repo>/build/claude-marketplace
/plugin install academic-research-workbench@arw-claude-local
```

Installed copy lives under
`~/.claude/plugins/cache/arw-claude-local/academic-research-workbench/<version>/`.
The marketplace source still points at `build/claude-marketplace`; keep that directory
or re-run `create-claude-marketplace` before `claude plugin marketplace update arw-claude-local`.

## Route unlock (integration lock)

A Claude install only returns `execution_mode: inline-role-prompts` after an exact
Codex host canary is bound into the package:

1. `stage-plugin` → `create-claude-marketplace` (keeps `.codex-plugin` + Codex hooks)
2. `qualify-codex-host` against `build/claude-stage/academic-research-workbench`
   (use a Node on `PATH` whose parent directory is named `bin`, e.g. nvm)
3. Build `integration-lock.json` and copy the canary evidence tree to
   `supply-chain/host-canary/` (stage-identity excluded)
4. Reinstall the Claude plugin

`bin/arw route --json` then auto-discovers:

- `supply-chain/integration-lock.json`
- `supply-chain/host-canary/canary.json`
- the lock-recorded Codex launcher path

`release_qualification` remains `BLOCKED` until CC BY-NC legal gates are resolved.
Minimum host version for this unlock path: Codex CLI `>=0.144.4`. The
qualification lock still records the exact binary tuple and requires a fresh
canary for each host version.

## Component map

| Surface | Claude package location |
|---------|-------------------------|
| Manifest | `.claude-plugin/plugin.json` (declares additive `hooks/claude-hooks.json`) plus retained `.codex-plugin/` for integration-lock binding |
| Skills | `skills/academic-research-workbench/`, `skills/academic-research-suite/` |
| Slash commands | `commands/ars-*.md` (materialized from `ars/commands/`) |
| Codex lock surface | preserved `hooks/hooks.json` + `hooks/arw_hook.py` (`${PLUGIN_ROOT}`) |
| Claude runtime hooks | `hooks/claude-hooks.json` → `hooks/arw_hook_claude.py` + ARS announce/guard |
| MCP | `.mcp.json` → `${CLAUDE_PLUGIN_ROOT}/scripts/file-base-mcp` |
| Control plane | `bin/arw` + vendored runtime |

## Hook authority boundary

- `arw_hook_claude.py` is **observational only**. Receipts under
  `$XDG_DATA_HOME/academic-research-workbench/hook-observations/v1` (or `PLUGIN_DATA`
  when set) never admit evidence, mutate runs, or decide gates.
- ARS `run_guard.sh` is optional write-scope hardening with graceful pass-through when
  Python is unavailable. It is **not** ledger or provenance authority.
- Plugin trust / hook enablement remains a Claude Code host concern; correctness must
  not depend on hooks being trusted.

## Relationship to the Codex package

| | Codex | Claude |
|---|---|---|
| Marketplace script | `scripts/create-marketplace` | `scripts/create-claude-marketplace` |
| Manifest dir | `.codex-plugin/` | `.claude-plugin/` |
| Hook root env | `${PLUGIN_ROOT}` | `${CLAUDE_PLUGIN_ROOT}` |
| Hook adapter | `hooks/arw_hook.py` | `hooks/arw_hook_claude.py` |
| Slash commands | Emulated in suite `SKILL.md` | Native `commands/` |
| Stage input | `scripts/stage-plugin` | Same stage, then transform |

License inventory (including CC BY-NC ARS content) is unchanged by the host migration.
