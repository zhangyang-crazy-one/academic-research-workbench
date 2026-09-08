# Research artifact contract inventory

- `RuntimeCommandRequest`, `ArtifactManifest`, `ArtifactAcceptedPayload`, stable
  runtime IDs, canonical JSON and SHA-256 remain the identity primitives.
- `locked_replay`, `build_runtime_event`, `append_runtime_event_unlocked`,
  `install_artifact_manifest` retain ownership of canonical writes. The internal
  `commit_artifact_pipeline` delegate serializes the entire qualification,
  publishes immutable files before append, then publishes a rebuildable binding.
- Receipts are family-specific: artifact integrity receipts, graph projection
  receipts, audit dossiers, and the new research-artifact receipt are distinct.
  No universal extensible receipt payload is introduced.
- The existing local-store `artifacts` table and `initialize_fresh` numbered
  SQLite migration runner supply the builder's disposable in-memory index.
  Labels and facts are reread from digest-verified canonical artifacts.
- Journal events have no historical migration/rewrite helper. Migration 0001
  adds the `1.1.0` event reader families through `state.event_versions`; it does
  not rewrite a `1.0.0` byte. `schemas/migrations/0001-research-artifact-events.json`
  records this additive migration. SQLite migrations must not be applied to the
  canonical JSON journal.
- Generated IR and receipt schemas join the normal schema registry, independent
  JSON Schema validation, packaging identity and compatibility checks.
- Capability factories are lazy at the composition root. The kernel has no
  renderer import; disabling the extension leaves all event decoders available.
