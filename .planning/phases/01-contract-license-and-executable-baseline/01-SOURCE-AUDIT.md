# Phase 1 Multi-Source Coverage Audit

All in-scope GOAL, REQ, RESEARCH, and CONTEXT items are covered. The 13 requirement IDs are owned exactly once across seven plans. Deferred and later-phase items remain explicit exclusions.

| SOURCE | ID | Feature / constraint | Plan | Status | Notes |
|---|---|---|---|---|---|
| GOAL | — | Install and exercise a legally classified, reproducibly sourced plugin whose authority and filesystem boundaries are proven | 01–07 | COVERED | Exact installed stage through clean integrated evidence |
| REQ | PKG-01 | Clean install and manifest validation | 01 | COVERED | Frozen package/wheelhouse, stage-relative Python, isolated source-independent install |
| REQ | PKG-02 | Installed skill routes declared ARS family/mode | 02 | COVERED | Executed RED contract plus fresh host probe/adapt/reinstall success |
| REQ | SUP-01 | Reproduce pinned source trees and ordered patches | 03 | COVERED | Exact-pin legal preflight before copy, then checked-in-only network-denied reconstruction |
| REQ | SUP-02 | Source/patch/lock/legal/artifact drift fails | 03 | COVERED | Independent mutation classes fail before staging |
| REQ | SUP-03 | Licenses, notices, SBOM, source manifest | 04 | COVERED | Pre-vendor receipt plus preserved/extended native gate and full dependency inventory |
| REQ | SUP-04 | Use/distribution/permission gate | 04 | COVERED | Technical PASS/release BLOCKED pending authentic evidence |
| REQ | SUP-05 | Exclude private material | 04 | COVERED | Positive allowlist, unique canaries, no symlinks/extras |
| REQ | RUN-01 | Initialize declared-capability run | 05 | COVERED | Strict manifest plus first canonical event |
| REQ | RUN-02 | Sole-writer deterministic hash-chained events | 05 | COVERED | Lock/revision/sequence/hash/fsync and forced-stop replay |
| REQ | PKG-03 | Installed bundled MCP has no source absolute path | 06 | COVERED | Stage-relative native launcher; source/network/PYTHONPATH denied |
| REQ | FILE-05 | Traversal/root/symlink/sensitive/budget denial before content | 06 | COVERED | Executed red direct-native tests precede 0002; unchanged upstream + sanitizers pass offline |
| REQ | PKG-04 | One complete installed version command | 07 | COVERED | Reads final packaged identity after all source/legal/native/schema outputs |
| REQ | VER-01 | Independent Python/MCP schema validation | 07 | COVERED | Draft 2020-12 regeneration/drift and independent fixtures |
| RESEARCH | — | Approved Python/uv/Pydantic/jsonschema/portalocker/hatchling/pytest stack | 01, 05, 07 | COVERED | Package Legitimacy Audit has no ASSUMED/SUS/SLOP entries |
| RESEARCH | — | Concrete installed Python runtime | 01 | COVERED | Self-locating bin/arw, checked-in wheelhouse, cache-local venv, no-index |
| RESEARCH | — | Installed route and MCP launcher uncertainty | 02, 06 | COVERED | Convergence loops cannot finish on non-auth blocking result |
| RESEARCH | — | License gate mandatory before vendoring | 03 | COVERED | Exact clean native gate/policy/checkers/generator execute before vendor/sources copy |
| RESEARCH | — | Source/patch manifest and checked-in-only build | 03, 06 | COVERED | Network denied/audited; 0001 then red-tested 0002 |
| RESEARCH | — | Full file-base legal baseline and dependency inventory | 03, 04, 06 | COVERED | Preflight, preservation, post-materialization extension, and post-0002 rerun |
| RESEARCH | — | Canonical ARS/experiment license paths | 03, 04 | COVERED | Exact source/materialized/staged paths and digests |
| RESEARCH | — | SUP-04 unresolved legal facts | 04, 07 | COVERED | Technical PASS and release BLOCKED absent authentic evidence |
| RESEARCH | — | Strict two-event envelope and sole-writer append | 05 | COVERED | No projection authority or deferred lifecycle behavior |
| RESEARCH | — | MCP-internal descriptor-safe bounded read | 06 | COVERED | 4096-byte/200-line Linux claim; no Windows junction claim |
| RESEARCH | — | Unchanged upstream C suite and sanitizer safety | 06, 07 | COVERED | Network-denied upstream, ASan+UBSan, and separate TSan raw evidence required |
| RESEARCH | — | Final build identity after all identity-bearing outputs | 07 | COVERED | Includes pre-vendor, patches, native suite, schemas, stage payload |
| RESEARCH | — | Build-identity-keyed raw evidence | 01–07 | COVERED | Commands/streams/status plus technical/release summaries |
| RESEARCH | — | ASVS access control, validation, data protection, files/resources, configuration | 01–07 | COVERED | Threat model and concrete controls in every plan |
| CONTEXT | D-01 | Plugin identity and installed validation | 01, 02 | COVERED | Valid stage, source-independent install, successful installed route |
| CONTEXT | D-02 | Headless install→route→runtime→MCP→evidence skeleton | 01, 02, 05, 06, 07 | COVERED | No UI/service/database additions |
| CONTEXT | D-03 | Python CLI sole writer; JSONL authority | 02, 05 | COVERED | Hooks/route read-only; writer exclusive |
| CONTEXT | D-04 | Exact pins, materialized snapshots, patches, notices | 03, 04, 06 | COVERED | Pre-vendor gate precedes snapshots; legal gate reruns after 0002 |
| CONTEXT | D-05 | Mixed-license gate and private-safe stage | 01, 03, 04, 07 | COVERED | Separate licenses and honest release BLOCKED |
| CONTEXT | D-06 | MCP-internal confinement | 06 | COVERED | Direct-native tests; wrapper/hook is not boundary |
| CONTEXT | D-07 | Complete version and schema identity | 01, 03, 05, 06, 07 | COVERED | Final identity includes all source/native/schema evidence |
| CONTEXT | D-08 | Compatibility behavior is probed, not assumed | 02, 06 | COVERED | Adapt/reinstall to successful host evidence; Linux-only claim |
| CONTEXT | D-09 | Raw smoke/schema/digest/install/confinement/recovery evidence | 01–07 | COVERED | Includes pre-vendor, network, native suites, all attempts, SIGKILL, replay, denials |

## Exact Requirement Ownership Check

`PKG-01→01, PKG-02→02, SUP-01→03, SUP-02→03, SUP-03→04, SUP-04→04, SUP-05→04, RUN-01→05, RUN-02→05, PKG-03→06, FILE-05→06, PKG-04→07, VER-01→07`

No requirement ID appears in more than one PLAN frontmatter and none is missing.

## Explicit Exclusions

- CONTEXT Deferred Ideas: full Phase 2 runtime/recovery, Phase 3 indexing/retrieval, Phase 4 subagents/review/human-gate UX, Phase 5 graph, Phase 6 dossier, Phase 7 cross-matrix qualification, and post-v1 UI/domain/remote/telemetry work.
- RESEARCH out-of-scope items: production search/index schemas, comprehensive checkpoint repair, PDF extraction, general orchestration, database/graph authority, and Windows junction claims in the Linux Phase 1 baseline.
