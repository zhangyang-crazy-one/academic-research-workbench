# Harness capability matrix

| Operation | Codex | Claude | Cursor |
|---|---|---|---|
| Save/search/read/doctor | native CLI | adapter-backed MCP | instruction-backed CLI |
| List | native CLI | adapter-backed empty-query search | instruction-backed CLI |
| Structured handoff save/read | native CLI | adapter-backed MCP | instruction-backed CLI |
| Canonical resume | native CLI | instruction-backed CLI | instruction-backed CLI |
| Activate/reject/verify/distill/purge | native parent CLI | unsupported MCP | instruction-backed parent CLI |

Native means the installed ARW launcher directly executes the parent runtime; Codex
needs no MCP loopback. Adapter-backed means the implemented four-tool stdio adapter
has protocol tests. These tests do not claim a live Claude host session was executed.
Cursor instruction-backed means an operator can run the documented CLI; no Cursor
plugin or automatic injection adapter is shipped. Unsupported MCP governance is
intentional: provider code cannot be reached through arbitrary tool names.

Harness selection is process configuration and provenance. A Claude read of a Codex
handoff returns the same memory ID and original source harness. It does not copy a
memory into a host-specific database. The example in `examples/` executes this round
trip locally with the actual MCP transport adapter and parent resume service.
