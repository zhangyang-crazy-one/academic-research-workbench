# Research Memory

The optional `arw_research_memory` provider stores advisory research context and
structured handoffs under an explicit ARW project identity. Canonical parent
writes admit immutable bodies through the existing journal. A disposable SQLite
index supports inspection and can be removed without losing accepted history.

## Operations

`MemoryProvider` defines `save`, `search`, `read`, `list`, and `doctor`.
The composition root registers `research.memory.save`, `.search`, `.read`, `.list`,
`.doctor`, and `.handoff`; absent provider imports fail with `CapabilityUnavailable`.
The kernel retains event decoding when the extension is unavailable.

```sh
arw memory init-project --project-root PROJECT
arw memory save --project-root PROJECT --run-root RUN --input note.json --request request.json
arw memory search --project-root PROJECT --query baseline --max-items 5 --max-tokens 4096
arw memory read MEMORY_ID --project-root PROJECT
arw memory doctor --project-root PROJECT
arw memory rebuild --project-root PROJECT --run-root RUN
```

Inputs use the checked schemas in `schemas/v1/research-memory*.schema.json`.
Requests use the existing `RuntimeCommandRequest` contract: parent actor,
current expected revision, command/event UUID identities and UTC seconds.
The CLI reads bounded, confined input files. No transcript importer is provided.
`--harness` is startup provenance, never a memory input field.

Search returns metadata and excerpts, not complete body bytes. It filters by
explicit scope, project, kind, run and timestamp; active entries rank before
created entries, then newest timestamp and stable ID. Superseded/rejected/
distilled entries require explicit read. UTF-8 byte accounting conservatively
bounds token context without assuming a host tokenizer. Small budgets may return
no matches with `RecallBudgetExceeded`; read is a separate bounded-body operation.

## Governance and continuation

`activate`, `reject`, `verify`, and `distill` are parent CLI operations; the MCP
surface cannot call them. Lifecycle events overlay immutable documents. Activation
does not raise trust. Verification requires a separately accepted JSON artifact
binding `action=verify_memory`, `memory_id`, `content_digest`, and nonempty
`source_artifact_ids`; distillation uses `action=distill_memory`. All named evidence
must already be admitted. These explicit authorizations are not produced by save.

`arw memory handoff` requires all structured handoff fields. `arw memory resume`
verifies accepted author-target links and current decisions before returning the
next suggested action. `arw resume --memory-handoff ID --memory-project-root PROJECT`
adds this same bounded context to normal Passport resume; flagless resume retains
its original output. A later author decision blocks the old suggestion and returns
canonical decision references for reconciliation. Completed work remains advisory;
author requirements establish intended scope, not empirical truth.

The optional transport is `python -m arw.memory_mcp --project-root PROJECT
--run-root RUN --harness claude`, also available as `bin/arw _memory-mcp` in an
installed bundle. Omit run root for read-only hosting. It offers exactly
`memory_save`, `memory_search`, `memory_read`, `memory_doctor`, with bounded JSON-RPC
stdio requests. It does not modify the frozen FileProvider tool set.

See [identity](PROJECT-IDENTITY.md), [privacy](PRIVACY.md),
[contracts](CONTRACT-INVENTORY.md), and the [harness matrix](HARNESS-CAPABILITY-MATRIX.md).
