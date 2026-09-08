# Artifact integrity: explicit UTF-8 cleanup

This extension inspects bounded UTF-8 bytes and optionally removes explicitly
selected Unicode markers from a derived copy. Findings indicate potential explicit
signals, including characters with legitimate linguistic uses. They do not prove
watermarking, absence of watermarks, or authorship.

## Commands

For an installed plugin, use `bin/arw`. From a source development environment, use
`uv run --frozen python -m arw.cli` with the same arguments. The repository launcher
uses its existing offline, locked wheelhouse; it does not fall back to source imports.

```sh
bin/arw artifact inspect --root /research/paper --path manuscript.md
bin/arw artifact sanitize --root /research/paper --path manuscript.md \
  --run-root /research/run --privacy --remove-codepoint U+200B \
  --request /research/requests/sanitize.json
```

The root and run must already exist. The run must be an initialized canonical
segmented run. Input is capped at 1 MiB; request JSON is capped at 64 KiB. Inspection
does not modify the source, journal, manifests, or missing directories. Responses
are versioned JSON and omit source snippets. An inspected result returns exit 0;
unsupported input or rejected operations return 65. An accepted sanitation returns
0 only after the canonical bundle and export mirror are rechecked.

The request uses the existing `ArtifactAcceptanceRequest` contract. For example:

```json
{
  "schema_version": "1.0.0",
  "run_id": "run-00000000-0000-4000-8000-000000000099",
  "event_id": "evt-00000000-0000-4000-8000-000000000100",
  "command_id": "cmd-00000000-0000-4000-8000-000000000100",
  "expected_revision": 1,
  "occurred_at": "2026-09-08T00:01:00Z",
  "actor_id": "parent.runtime",
  "actor_role": "parent_control_plane",
  "artifact_id": "artifact.cleaned",
  "artifact_kind": "artifact-sanitization-receipt",
  "media_type": "application/json",
  "content_path": "derived-by-service.json",
  "content_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "base_revision": 1,
  "consumed_sha256": []
}
```

Use the actual run identity/current revision and new event/command IDs. Retain the
exact request for retries. `attempt_id` is optional; when supplied, its base revision
and consumed hashes must match the active attempt. Empty consumed hashes are valid
for a parent-owned artifact without an attempt; otherwise use known ledger,
artifact-manifest, or passport hashes. The source text hash is **not** a consumed
canonical provenance hash. The service derives and replaces the kind, media type,
content path, and content hash from the actual bundle bytes. Supplied placeholder
values never decide what is accepted.

## Implemented checks and treatments

| Family | Inspection | Treatment |
| --- | --- | --- |
| Invisible Unicode, bidi controls, tags, exotic spaces | Code point, character/UTF-8 byte offsets, complete bounded-input counts; at most 256 locations | Explicit `--remove-codepoint U+XXXX` selection with `--privacy` |
| Joiners, variation selectors, directional controls | Potential signals, including legitimate language/emoji uses | Retained unless their exact code points are selected |
| EXIF/XMP, PDF/DOCX properties | `unsupported`, including UTF-8 XMP/SVG carriers | Unsupported |
| C2PA | `unsupported`; no signature validation | `--strip-provenance` explicitly returns unsupported |
| Statistical watermark/author diagnostics | `unsupported` | Separate planned writing extension |
| Recognized binary containers, invalid UTF-8, NUL-bearing input | Unsupported Unicode scan; no false clean result | Refused |

Unicode inspection is a byte-content check, not a format-aware document parser.
Scanning UTF-8 XML/SVG bytes does not qualify their metadata or structured content.
No binary extraction, archive expansion, image reconstruction, metadata removal,
statistical rewriting, or general Unicode normalization is performed. `--treatment`
accepts only `unicode` in this version. Repeat `--remove-codepoint` to select up to
256 entries. Ordinary text, citations, math, CJK, line endings, and every unselected
character retain their UTF-8 bytes. Before/after scans report residual markers and
unsupported checks independently.

## Canonical evidence and retry

The service publishes create-only files under the run root:

- `arw-sanitize-SHA256(command_id).receipt.json`: the canonical accepted artifact.
- `arw-sanitize-SHA256(command_id).txt`: a derived export mirror.

The bounded JSON bundle retains original and derived text themselves, both hashes,
relative identities, request identity, explicit authorization, selected code points,
policy/inspector versions, removal counts and postscan. The existing parent runtime
admits the bundle using `artifact.accepted`; no new event type is introduced.
The maximum encoded bundle is 14 MiB. The accepted bundle can reconstruct both texts
even when their external files are gone; an accepted receipt is not scientific
approval. Canonical replay validates the retained bundle, not the export mirror.

Exact retries recheck candidate bytes and canonical event identity and produce at
most one acceptance. Conflicting IDs, changed source/export bytes, stale revisions,
unknown consumed hashes, or mismatched candidates fail explicitly. An interrupted
operation may leave an unaccepted candidate or an already committed event. It never
rolls back a committed event or claims acceptance without verification. Retrying an
existing command requires its original input file; canonical replay and recovery of
the retained bundle remain possible after input deletion.

## Filesystem boundary

Source reads and candidate publication use descriptor-relative no-follow traversal,
regular-file and identity checks, bounded reads, exclusive temporary creation and
create-only publication. Symlink roots/ancestors/leaves, traversal, ambiguous relative
paths, special files and missing roots are rejected. This has been exercised on
Linux; platforms without the required `dir_fd`, `O_NOFOLLOW`, `O_DIRECTORY`, link and
unlink operations return `platform_unsupported` rather than using a weaker fallback.

The canonical runtime still uses its existing path-based journal/manifest APIs.
The extension rechecks the pinned run-root identity immediately around that boundary,
including before acceptance, but does **not** provide a race-proof descriptor-based
kernel transaction. Canonical run roots and their ancestors must remain under trusted
operator ownership during admission. Concurrent hostile replacement inside the
runtime's path resolution remains outside this slice's verified guarantee.

Both capabilities are gated by the plugin's `artifact` declaration. Missing optional
provider imports produce capability-unavailable results; the legacy receipt
`evaluate(...)` surface remains available on the default provider.
