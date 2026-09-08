# Privacy and retention

Secret-shape checks run before memory bodies, events or indexes are published.
Rejections return typed codes, never input payloads. This is defense in depth, not a
proof of detecting every secret. Deliberate sensitive content still needs operator
review before submission. MCP diagnostics omit validation excerpts and raw values.

Bodies are immutable files keyed by content digest. Events retain only metadata,
IDs and hashes; cached summaries are rebuildable from admitted bodies. Inventory
limits bound memory count, run count, individual document size and aggregate bytes.
Doctor reports schema, digest, path, references, duplicate identity, lifecycle and
cycle faults without modifying or deleting files. Unsafe bodies are logically
quarantined (`body_recoverable=false` in the fault); doctor does not follow them or
claim that a symlink target is a retained body. A path-security fault carries a
report-only quarantine tombstone (`durable=false`); it is distinct from an
authorized durable retention tombstone and leaves the unsafe path untouched.

Authorized purge requires `--authorize-purge` and a separately accepted JSON artifact
with `action=purge_memory`, exact `memory_id` and `content_digest`. It writes a durable
tombstone citing the authorization run/event before removing body bytes, then rebuilds
the disposable index. Retries preserve the marker and ledger. Doctor reports the
intentional tombstone; explicit read raises `BodyUnavailable`. Index rebuild restores
the tombstone, not the body. A preserved hashchain does not mean full-body recovery
is possible. External backups and already exported copies are outside this deletion.
