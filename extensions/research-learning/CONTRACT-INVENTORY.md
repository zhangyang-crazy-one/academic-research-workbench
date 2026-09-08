# Learning contract inventory

Canonical writers reuse `arw.kernel.ledger.journal.locked_replay`,
`build_runtime_event`, `append_runtime_event_unlocked`, and `reduce_events`.
A project advisory lock precedes the canonical run lock. A held run snapshot is
passed into inventory reads so the same run lock is never reacquired. Files are
published with the existing descriptor-relative, create-only, fsynced
`publish_once`; canonical events reference content digests. Exact command retries
bind both request and operation hashes without retaining duplicate body text.
A successor's proposal and predecessor supersession remain two explicit events;
retry completes an interrupted supersession.

Version `1.3.0`, migration `0003`, adds exactly seven event families. Reader
contracts and replay invariants live in core and remain available with the
extension absent or disabled. No historical event bytes are rewritten.
The core verifies prior status, project identity, accepted source references and
digests, qualified promotion, consent, approval references, and supersession IDs.

Existing local-store metadata/FTS and graph tables remain unaffected. Learning's
rebuildable project projection lives at `.arw/learning/index.sqlite3`, with
`learning_observations`, `learning_memories`, `research_heuristics`,
`heuristic_evidence`, `heuristic_counterexamples`, `heuristic_evaluations`, and
`heuristic_promotions`. The optional-memory table is empty without a memory
adapter; it is not an authoritative memory store. Historical evaluation and
promotion IDs are retained, including superseded versions. There is no
`workflow_candidates` table.

Canonical bodies are `.arw/learning/bodies/SHA256.json`; the registered canonical
runs bind stable run identity, relative root and manifest digest. Reads validate
ledger and body bindings before returning content. Inventory is bounded to 256
runs, 1,024 record identities, 4,096 learning events, 65,536 bytes per document,
and 8 MiB aggregate body bytes. Query lists are capped at 50 entries. SQLite can
be deleted and rebuilt, and cannot grant scientific or execution authority.
Authorized-purged bodies are excluded from rebuild equivalence.

`arw.composition.default_router` registers lazy optional capabilities and filters
them against the plugin's declared `learning` capability. Resolution without the
extension gives `CapabilityUnavailable`. CLI and kernel never import the concrete
provider. `HeuristicInput`/observation schemas and the five Protocol ports form
the extension boundary. The wheel packages `arw_research_learning` separately
from the core package namespace.
