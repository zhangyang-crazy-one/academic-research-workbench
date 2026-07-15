# Scientific audit dossier

`arw.audit-dossier.v1` is a bounded, content-addressed manifest assembled by
the parent control plane after replaying the canonical journal.  The manifest
is the sole source for its JSON and Markdown views; neither view is authority.
Ledger events, immutable run/artifact/Passport manifests, integrity receipts,
external experiment provenance, five-state access decisions, review reports
and dissent, human decisions, graph projection receipts, test/benchmark logs,
source/build identities, and the ARS integration lock are retained by exact
SHA-256 reference.

## Replay and projection boundary

Assembly validates the run replay and referenced records before collecting
metadata.  SQLite and graph rows are disposable projections.  If a selected
projection is missing, stale, or corrupt, the assembler may rebuild it from
canonical records; otherwise it adds a bounded `projection_unavailable`
blocker to the in-memory dossier manifest only.  It never appends a ledger
event, changes a claim verdict, or treats a Markdown statement as evidence.

`generated_at` is injected into the manifest.  Canonical JSON uses sorted
keys and fixed UTF-8 bytes; rendering the same sealed manifest twice therefore
produces byte-identical JSON and Markdown.  The Markdown header explicitly
labels every projection and rendering as non-authoritative.

## Evidence and safety limits

The dossier contains digests, bounded names, statuses, and replacement
evidence—not private full text, credentials, environment dumps, absolute paths,
or unresolved license material.  Secret-looking values, private path markers,
duplicate or unsorted references, non-canonical hashes, unknown fields, and
oversized records fail strict validation.  Missing or stale records remain
visible as typed blockers and are never silently upgraded.

Technical qualification and release qualification are independent.  A
technical `PASS` means that the replay and evidence contracts were satisfied;
it is not permission to distribute.  The current mixed ARS/ARW package keeps
release qualification `BLOCKED` for `SUP-04`, `P04-09`, and
`CC_BY_NC_PERMISSION_UNRESOLVED` until intended use, distribution class,
accountable approval, and permission evidence are resolved.

Controlled experiment execution is not implied by an external provenance
record.  Science Workbench paper AST/export remains a v2 capability and is
not represented as a completed ARW research-to-paper replacement.
