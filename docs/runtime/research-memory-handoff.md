# Research memory and handoff qualification

The `research-memory-handoff` extension provides immutable, project-bound advisory
memory, canonical lifecycle events, bounded recall and a four-tool optional MCP
transport. The core remains responsible for historical event decoding. This change
does not promote memory content into research policy or scientific verification.

## Architecture and executable evidence

| Requirement | Implementation / verification |
|---|---|
| Stable identity and isolation | `.arw/project.json`; explicit per-scope policy; tests cover distinct projects, granted cross-project team recall and explicit user recall. |
| Immutable bodies and retries | Create-only body publication, parent journal admission, post-event SQLite projection; tests kill real processes at all three boundaries and retry without duplicate events. |
| Governance | Separate lifecycle/trust fields, stable predecessor hashchain, explicit accepted verification and purge authorizations; tests verify activation remains unreviewed. |
| Bounded recall | Metadata/excerpt search, separate read, byte-conservative context limit and deterministic rank order; source and inventory limits fail closed. |
| Continuation | Accepted author-target and current author-decision resolution; later decisions suppress the stale next-action suggestion. |
| Optional transport | `arw.memory_mcp`; exactly save/search/read/doctor; startup-bound roots and harness; protocol, CLI and prohibited-operation tests. |
| Compatibility | Migration 0002; deterministic `tests/compat/golden/research_memory_events.json`; missing extension prevents new operations while historical events decode. |
| Privacy and integrity | Before-write secret-shape rejection, payload-free error codes, read-only doctor, explicit tombstones and unavailable purged bodies. |

The reproducible example is
`extensions/research-memory/examples/handoff_roundtrip.py OUTPUT`. It creates a
canonical author target, saves a Codex handoff, reads the same identity through a
Claude-configured stdio adapter and resumes from Codex. This is a real local transport
execution, not evidence of a live Claude or Cursor host integration. The harness
matrix distinguishes native, adapter-backed, instruction-backed and unsupported paths.

## Validation commands

```sh
uv run --frozen pytest tests/integration/test_research_memory.py tests/compat tests/schema tests/unit -q
uv run --frozen python extensions/research-memory/examples/handoff_roundtrip.py NEW_OUTPUT
```

The example retained under `build/examples/research-memory-20260908` used
`memory-06c12ba4edfe3160ecd56c53a3109105` across both harness paths and returned the
unfinished paired evaluation action with the accepted author target. Build outputs
are local evidence; the example script is the reproducible source artifact.

Release status is determined by the PR merge and exact-head CI checks, not local
OpenSpec checkboxes. Issue #11 stays open until delivery completes.

Local qualification on 2026-09-08: 699 broad tests passed; after final integrity
changes, 88 memory and compatibility tests passed. Targeted Ruff and whitespace
checks passed. GitHub CI/main delivery are tracked separately.
