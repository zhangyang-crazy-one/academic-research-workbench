# Capability and host separation

Local research, manuscript, text, and explicitly rooted file operations should remain usable when Codex host qualification is absent. The existing route conflates those capabilities with the Codex execution adapter. Add a separate core route and installed-stage integrity gate while retaining the strict legacy execution contract.

This change affects the launcher, core route/schema, stage validation, installed CLI/MCP guards, and canonical routing guidance. It does not add a Claude execution adapter or relax Codex Phase 4 dispatch.
