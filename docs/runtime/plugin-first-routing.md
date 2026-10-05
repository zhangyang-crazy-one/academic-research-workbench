# Plugin-First Routing (Issue #6 Phase 4)

Codex reaches ARW's capabilities through the plugin's own skills and the
composition root's capability router. The file-base MCP binary remains
available as an **opt-in transport adapter** — it is no longer the
architecturally privileged path.

## Request paths

```text
Codex skill ──▶ arw CLI ──▶ composition.default_router ──▶ capability router
                                                              │
                              ┌───────────────────────────────┼───────────────────────┐
                              ▼                               ▼                       ▼
                     files.local (native:            knowledge.graph         research.literature
                     LocalStoreFilesAdapter          (GraphStore / local      artifact.inspect
                     over .arw/arw.db)               store projection)       (bundled ARS)

external client ──▶ MCP adapter (file-base / arw files MCP) ──▶ the same ports
```

## Capability activation

`bin/arw route --core --json` reports staged core integrity and provider
records without qualifying an execution host. Installed commands verify the
closed stage inventory, wheel, source/build evidence, licenses, and SBOM before
operation. The legacy `route --json` and Phase 4 dispatch retain their exact
Codex IntegrationLock gate. An editable source checkout is `UNVERIFIED`.
The capability rows are selected, nonexhaustive observations; each command
resolves its own provider and configuration when invoked.
Direct Python `health` and `version` are diagnostics; their success does not
attest installed core integrity or execution qualification. Use
`route --core --json` for the staged-integrity report.
For an installed launcher, an explicit `ARW_PLUGIN_ROOT` must equal that
launcher's stage root. Use agent mode only with a source checkout; it cannot
relabel an installed bundle as editable source.

- The plugin manifest (`.codex-plugin/plugin.json`) declares the capability
  set (`research`, `literature`, `experiment`, `evidence`, `files`, `graph`,
  `provenance`, `artifact`, `audit`).
- `arw.composition.declared_capabilities()` reads the declared set;
  `default_router()` registers providers lazily. Capabilities without a
  provider resolve to a typed `CapabilityUnavailable`, never an import error.
- Optional research engines (STORM, and Semantica in a later phase) register
  via `CapabilityRouter.register_optional`: when the extra is not installed,
  resolution returns a capability-not-available receipt and every other
  capability keeps working.

## Default providers

- `files.local` resolves to the **native local-store adapter** when the
  composition root is given a `store_path` whose store carries an ingested
  files projection. The v1 file-base generation path stays selectable by
  simply not passing `store_path`.
- Equivalence between the v1 adapter and the local-store adapter is pinned
  by `tests/integration/test_local_store_files.py` (dual-adapter parity over
  list/read/search/outline/context) and the golden-envelope fixtures in
  `tests/compat/test_local_store_files_adapter.py`.

## MCP approval policy

The MCP server remains available for external clients. Plugin-scoped policy
keeps the read tools (`list_files`, `read_file`, `search_files`,
`get_outline`, `get_context`) auto-approved; index/sync administration
(`arw files sync` / `register-root` / `rebuild`) stays operator-prompted.
No Codex session needs the MCP loopback for ARW's own local file/knowledge
APIs.
