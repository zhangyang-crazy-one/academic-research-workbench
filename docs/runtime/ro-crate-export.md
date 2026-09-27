# Read-only RO-Crate export

`arw artifact ro-crate-export` reads a verified canonical run under the existing
read-side journal lock and writes an independent crate. It never repairs a run,
accepts an artifact, updates a projection, or creates an audit dossier.

```bash
bin/arw artifact ro-crate-export --run-root RUN --output run.zip --format zip
bin/arw artifact ro-crate-export --run-root RUN --output crate --format directory \
  --include-artifact-id artifact.public-summary
bin/arw artifact ro-crate-verify --crate run.zip --run-root RUN
bin/arw execution-metadata --run-root RUN --request request.json --payload owner-metadata.json
```

The run manifest and complete accepted event chain are replayed. The exporter
rejects an unhealthy journal, missing/invalid accepted manifests, an unavailable
read lock, history or byte limits, a changed selected body, and an output path
inside the run. Publication uses a sibling temporary path. An existing output
is never intentionally replaced. The command returns exit `65` on rejection.

No artifact body is disclosed by default because the canonical artifact manifest
has no authoritative public/shareable classification. Operators explicitly list
accepted artifact IDs to include. Even then, kinds or paths marked private,
sensitive, secret, restricted, or similar are omitted. Selected JSON bodies
with recorded non-shareable `privacy_classification`, non-public
`access_state`, or non-clear `license_status` are also omitted. A selected body
with a credential-like JSON key at any nesting level or a recognized secret
shape in a decoded JSON string is rejected, including escaped JSON keys/values.
These checks are safeguards, not proof that content is safe to publish. Review
every selected body before sharing.
The immutable input, source manifest bodies, complete event payloads, assignment files,
private notes, and generated audit dossiers are never packaged. Digest-only
omissions carry an explicit reason. The binding file records every accepted
event digest so omission does not silently truncate run history.
Its execution-fact section contains only fields needed to reconstruct the
public graph and source checks. Host error text is excluded; paths with a
private/sensitive marker are replaced by their digest and block profile
completeness. A private workflow source path also prevents its source bytes
from entering the crate. Owner publication metadata is checked for recognized
secret shapes before export.

The crate contains RO-Crate 1.3 JSON-LD metadata (`ro-crate-metadata.json`)
and `arw-source-binding.json`. The descriptor points to the root `Dataset`.
Exported files have SHA-256 and `contentSize` calculated from emitted bytes.
The binding separately records accepted source manifest, content and event
digests. The root's `name`, `description`, `datePublished` and `license` come
only from the latest parent-accepted dataset metadata event. RO-Crate 1.3
requires these four properties, as well as root `@type` and `@id`. An absent event
leaves all four fields absent and the base status `incomplete` with each field
listed as missing. The base verifier checks the serialized root independently:
missing or invalid properties cannot pass, but valid base and workflow-profile
properties may pass even if an owner event is absent or disagrees. Such provenance gaps instead make
ARW metadata completeness incomplete or failed, and fail live source binding.
Descriptive richness and a
license-entity link are SHOULD guidance, not the fields' presence. Run creation time
and repository licensing are never substituted. The owner can supply metadata
through `execution-metadata` after a run; corrections append a revision that
names the prior event and gives a rationale. `datePublished` is an ISO date.
File order, JSON serialization, ZIP timestamp (1980-01-01 00:00:00), and ZIP
permissions are fixed. The same unchanged run and disclosure choices yield
identical ZIP bytes.

The target is Provenance Run Crate 0.6. Parent-accepted execution events now
provide a workflow source, workflow and tool action intervals, tool identities,
step relations, and input/output source bindings. The exporter maps these to
`ComputationalWorkflow`, `CreateAction`, `HowToStep`, and `ControlAction` nodes.
The workflow source file is included only when its retained event bytes pass
the privacy check. Its name is copied from the accepted context. When the
parent event supplies a complete `programming_language` object (`uri`, `name`,
`url`, `version`), the workflow's `programmingLanguage` is an `@id` link to a
contextual `ComputerLanguage` entity with exactly those event-backed fields.
When the object is absent, neither the link nor the entity is emitted; the
profile reports `workflow_language_identity`. The exporter never derives
language identity or version from a runtime or raw label.

Input and proposal-output bodies remain excluded by default. Their canonical
event, path, digest, and size bindings stay in the binding file, but the graph
does not portray an absent file as a crate `File`, `object`, or `result`. An
action links to a data `File` only when the exact accepted artifact body is
copied into the crate and the source event, manifest, digest, and size match.
This follows the [RO-Crate data entity rule](https://www.researchobject.org/ro-crate/specification/1.3/data-entities.html):
a local file data entity must be packaged, while web-based data entities need
an actual web identity. The missing action data remains an explicit ARW
`digest_only_action_data` completeness gap; omitted results produce a SHOULD
warning. No unknown host-internal tool execution is asserted.

Profile declarations follow the [Provenance Run Crate 0.6](https://www.researchobject.org/workflow-run-crate/profiles/provenance_run_crate/)
direction rules, including the inherited [Workflow Run Crate 0.6](https://www.researchobject.org/workflow-run-crate/profiles/workflow_run_crate/)
and [Process Run Crate 0.6](https://www.researchobject.org/workflow-run-crate/profiles/process_run_crate/)
requirements. Any eventual root profile declaration must be an array of links
to described `CreativeWork` profile entities. The exporter declares these
profiles only when its standard MUST checks pass; default-private omission of
`object`/`result` file bodies does not by itself prevent that declaration.

The canonical context now permits an owner-asserted, versioned language
identity. Older runs or new runs that omit it remain profile-incomplete. With
that identity and all other mandatory graph facts, an observed run can pass
Provenance Run Crate 0.6 and carry root `conformsTo` even under the default
private disclosure policy. Its ARW completeness remains `incomplete` until
bound action data is actually admitted. Process Run Crate 0.6 marks
`CreateAction.object` MAY and `result` SHOULD; Workflow Run 0.6 makes formal
input/output slots optional. The verifier reports those SHOULD omissions
separately from standard MUST status.
RO-Crate 1.3 base MUST conformance (root identity and all four metadata fields) is reported separately
from ARW metadata completeness, profile relationships, exported-byte integrity,
and optional live source-run binding. The metadata descriptor identifies the
base RO-Crate 1.3 version. This is a bounded offline graph and byte check,
not an independent RDF validation service. Without `--run-root`, source-run
binding remains `unverified`. An altered file, invalid JSON, duplicate or
traversal path, or ZIP symlink is rejected. Verification
accepts only regular-file ZIP inputs, opens them with O_NOFOLLOW, checks the
opened descriptor's type and size, and reads members through that descriptor.
It bounds archive size, expanded bytes, and entry count before reading member
bodies, and scans bounded EOCD/central-directory records before ZipFile builds
its member list. ZIP64, multi-disk archives, and compression methods other than
stored/deflated are rejected; prepended/self-extracting ZIP layouts are also
unsupported. ZIP verification requires host O_NOFOLLOW support. Directory
crates reject special entries and enforce their entry budget while scanning.
Publication atomically renames the staged directory with
no-replace semantics; if that operation is unavailable, export fails and
removes the stage directory. Digests are not digital
signatures and cannot prove the publisher's identity. The verifier reconstructs
the canonical metadata from the binding record to detect metadata-only edits;
a coordinated rewrite of both files requires comparison with the canonical
run (`--run-root`) to detect substitution.

The canonical event recorder is developed under the separate
`parent-owned-execution-provenance` change. This exporter consumes its
replay-validated projection and does not read hooks, transcripts, or mutable
indexes as execution evidence. Historical runs are not upgraded or backfilled.

Defaults: at most 4,096 events, 512 entries, 64 MiB total crate bytes, and
8 MiB per crate member. `--max-events`, `--max-entries`, and `--max-bytes` can
lower these bounds. Exceeding one fails the export; no partial-history profile
is available. No runtime dependency or network access is required.

Repository citation metadata is in `codemeta.json`. Its root has no blanket
license. Component licensing follows [`LICENSE`](../../LICENSE),
[`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md), and the
[source manifest](../../vendor/source-manifest.json): ARS/experiment-agent
workflow content is CC BY-NC 4.0; vendored file-base is MIT.
Codemeta's `codeRepository` and `relatedLink` values are absolute HTTPS URLs;
component licenses remain attached to their respective `hasPart` entries.
