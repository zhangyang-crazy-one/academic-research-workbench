# Contract inventory

| Existing contract | Reuse |
|---|---|
| `locked_replay`, `append_runtime_event_unlocked`, `build_runtime_event` | The existing parent run lock and hashchain serialize canonical admission. |
| `RuntimeCommandRequest` | Expected revision, actor, event and command identities; no extension-specific journal writer. |
| `publish_once`, `unlink_retained`, `read_retained_bytes` | Create-only, fsync publication and confined, symlink-rejecting retained-file access. |
| `ArtifactManifest`, accepted artifact events | Verification, author-target, evidence and retention references; no parallel evidence authority. |
| Core `event_versions.MIGRATIONS` | Migration 0002 adds version 1.2.0 memory families; 1.0.0/1.1.0 historical bytes remain unchanged. |
| FileProvider | Five existing tools and request/response contracts stay frozen. Memory has its own Protocol and four optional MCP tools. |

A project-level memory lock surrounds the existing run writer lock. Bodies precede
accepted events; the SQLite projection follows them. A crash can leave an unadmitted
body, which doctor reports and an exact retry may admit. No index row admits evidence.
Same logical content within a project/run returns the same memory identity; explicit
ID reuse with different content is a conflict. Harness metadata does not change the
logical identity, and retained provenance belongs to the original creator.

`research_memory_created`, `research_handoff_created`, `research_memory_superseded`,
`research_memory_rejected`, `research_memory_distilled`, `research_memory_activated`,
`research_memory_verified` carry IDs/digests/provenance, never raw body/title text.
Historical readers use only core models. Governance supplies separate status/trust
and previous-event digest fields, and a broken or forked chain fails recall closed.
