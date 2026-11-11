## ADDED Requirements

### Requirement: Native file-base MCP isolates its daemon runtime cohort
The `file-base` MCP provider launcher SHALL bind an isolated, owner-private `CBM_RUNTIME_DIR` when none is supplied so `file-base` never shares the default `/tmp/cbm-daemon-<uid>` cohort with an external `codebase-memory-mcp` installation or an unrelated cache directory, and SHALL reject invalid caller-supplied `CBM_RUNTIME_DIR` values fail-closed.

#### Scenario: Host already runs upstream codebase-memory-mcp
- **WHEN** upstream `codebase-memory-mcp` holds `/tmp/cbm-daemon-<uid>` and a client launches `scripts/file-base-mcp` with valid `CBM_ALLOWED_ROOT`, `CBM_ALLOWED_ROOT_ID`, and `CBM_CACHE_DIR`
- **THEN** `scripts/file-base-mcp` selects an owner-private `CBM_RUNTIME_DIR` within the Unix socket path budget, completes MCP initialization and bounded `read_file` calls without `version_cohort.conflict_retry` timeouts, and leaves the upstream daemon undisturbed

#### Scenario: Caller supplies an unsafe CBM_RUNTIME_DIR
- **WHEN** `CBM_RUNTIME_DIR` is relative, missing, a symlink, or not owned by the effective user
- **THEN** `scripts/file-base-mcp` exits non-zero before invoking the native binary

### Requirement: Plugin manifest capability gating is uniform across gated commands
Installed-mode invocations (`ARW_PLUGIN_ROOT` set) of `provenance`, `semantic`, `evidence`, and `resume --memory-handoff` SHALL require a readable `ARW_PLUGIN_MANIFEST` from `bin/arw` and SHALL gate provider resolution against `interface.capabilities` in `default_router`, while preserving the source-checkout fallback when `ARW_PLUGIN_ROOT` is unset and ordinary `resume` when `--memory-handoff` is not requested.

#### Scenario: Manifest omits provenance, semantic, or evidence capability
- **WHEN** `ARW_PLUGIN_MANIFEST` points to a valid plugin manifest whose `interface.capabilities` omits `"provenance"`, `"semantic"`, or `"evidence"`
- **THEN** `arw provenance`, `arw semantic`, or `arw evidence` respectively fails closed with capability-unavailable status (`exit 65` or `2` per command contract) without executing the provider

#### Scenario: Installed memory-handoff resume binds the bundled manifest
- **WHEN** `bin/arw resume --memory-handoff <id>` runs from a plugin root containing `.codex-plugin/plugin.json` declaring `"memory"`
- **THEN** `bin/arw` exports `ARW_PLUGIN_MANIFEST` and resolves `research.memory.handoff`, whereas a missing `.codex-plugin/plugin.json` fails closed (`exit 66`) and ordinary `arw resume` without `--memory-handoff` does not require a manifest

### Requirement: Read-only evidence impact checklist CLI and capability route
ARW SHALL register `evidence.impact` under the `"evidence"` manifest capability and expose `arw evidence impact` as a bounded, read-only CLI command over `GraphStore` and `EvidenceUpdate` without mutating canonical runs or projections.

#### Scenario: Operator evaluates a source counterevidence or withdrawal update
- **WHEN** an operator runs `arw evidence impact --control-root <root> --root-id <id> --update <json> --expected-watermark <n>` (with optional `--proposals <json>`) against a projected `GraphStore`
- **THEN** the CLI emits the deterministic `arw.evidence-impact-checklist.v1` JSON report with `accepted_outputs_modified: false` and `human_review_required: true`, returning `0` when `status == "review_required"` and `65` when `status == "incomplete"` or inputs are invalid

### Requirement: Single-pass launcher verification and complete skill capability routing
`bin/arw` SHALL memoize per-file SHA-256 digests within a single `bootstrap_wheel_runtime` check without persisting cross-process trust state, and `skills/academic-research-workbench/references/control-plane-capabilities.md` SHALL document all shipped deterministic control-plane commands and opt-in stdio MCP servers.

#### Scenario: Agent consults workbench skill references for deterministic gates
- **WHEN** an agent reads `skills/academic-research-workbench/SKILL.md` and `references/control-plane-capabilities.md`
- **THEN** every shipped control-plane command family (`research`, `narrative`, `files`, `evidence`, `claims`, `numeric`, `experiment`, `writing`, `review`, `disclosure`, `selection-audit`, `memory`, `learn`, `semantic`, `provenance`, `citation`, `pdf`, `artifact`, `submission`) and opt-in stdio MCP entrypoint is listed with its authority boundary, and `scripts/validate-skills` passes
