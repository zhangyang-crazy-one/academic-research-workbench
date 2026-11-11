# ARW control-plane capabilities

These are routes under the installed `academic-research-workbench` skill, not
independent trigger descriptions. Resolve `<installed-plugin-root>` as the parent
of `skills/`. The parent runtime alone writes canonical state; projection stores,
hook receipts, and advisory checklists never authorize transitions by themselves.

| Request | Route and boundary |
| --- | --- |
| Runtime health and workflow route | `bin/arw health --json` for platform/file-base readiness; `bin/arw route --core --json` for local capability inventory; `bin/arw route --json` for strict Codex host-qualified dispatch; `bin/arw status --run-root RUN --json` for an existing run. |
| New or resumed research direction | `bin/arw research start/status/resume --project-root PROJECT`; read [research-direction-workflow](research-direction-workflow.md) before selecting a paper narrative. |
| Project paper narrative | `bin/arw narrative register/select/status/propose/approve --project-root PROJECT`; select before `init --task-kind paper` and reload on handoff/resume. Non-paper runs need no narrative. |
| Literature review, citation methods, peer review, experiment design | Read `academic-research-suite/SKILL.md` and its selected `ars/*/WORKFLOW.md`; do not substitute a generic control-plane query for ARS methodology. |
| Bounded local files and search | `bin/arw files enable` to opt in a project config; `bin/arw files status/sync/rebuild/repair --control-root ROOT --root-id ID`. MCP exposes only `list_files`, `read_file`, `search_files`, `get_outline`, `get_context` (`scripts/file-base-mcp` or `bin/arw _files-store-mcp`). |
| Research graph, provenance, and optional semantic recall | `bin/arw provenance record/lineage/verify/rebuild --run-root RUN --store STORE` (Semantica Lite sidecar); `bin/arw semantic build/rebuild/search` (explicit pinned local model); `bin/arw _graph-mcp --control-root ROOT --root-id ID` for stdio graph queries. All projections are rebuildable from canonical ledger events. |
| Evidence impact review | `bin/arw evidence impact --control-root ROOT --root-id ID --update UPDATE.json --expected-watermark N [--proposals PROPOSALS.json]`. Produces a read-only `arw.evidence-impact-checklist.v1` report (`accepted_outputs_modified: false`); human review is required before revising claims, plans, or prose. |
| Claims, exact numeric derivations, and experiment contracts | `bin/arw claims` for revision-bound manuscript claim projection/attestation; `bin/arw numeric` for exact `AcceptedRef` rational derivations; `bin/arw experiment` for versioned offline experiment contract evaluation. |
| Scholarly citations, PDF locators, and selection audit | `bin/arw citation check/gate` (offline receipts or explicit `--allow-network`, see [database-lookup-advisory](database-lookup-advisory.md)); `bin/arw pdf` for bounded local PDF text/locator proposals; `bin/arw selection-audit export/replay` for candidate screening traces. |
| Artifact integrity, typed artifact IR, and RO-Crate | `bin/arw artifact inspect/sanitize` for explicit Unicode/metadata inspection and derived cleanup; `bin/arw artifact compile/reproduce/doctor` for deterministic figure/view IR; `bin/arw artifact ro-crate-export/ro-crate-verify` for read-only archival bundles. |
| Memory, handoff, and heuristic learning | `bin/arw memory save/search/read/list/doctor/handoff` (or `bin/arw _memory-mcp`) and `bin/arw resume --memory-handoff ID --memory-project-root PROJECT`; `bin/arw learn` for evaluated, human-consented lessons. |
| Writing proposals, advisory review, and AI disclosure | Read [writing-revisions](writing-revisions.md) for `bin/arw writing`; `bin/arw review diagnose/verify/replay/prov` for source-bound advisory concerns and PROV export; `bin/arw disclosure summary/draft/replay` for AI participation summaries requiring final human review. |
| Audit replay and lifecycle recovery | `bin/arw replay --run-root RUN`, `bin/arw checkpoint`, `bin/arw resume`, `bin/arw recover`. The append-only ledger and immutable manifests remain the sole canonical truth. |
| Manuscript submission packets and outcomes | Read `submission/SKILL.md` (`bin/arw submission prepare/record/review-import/response-record/check/qualify/ready/record-result/status`); no external portal upload or auto-submit. |

For experimental survey research, the opt-in `bin/arw storm` path is described in
`SKILL.md`. It requires explicit user consent and `--api-key-env`, never reuses
agent credentials, and produces pre-writing material rather than canonical evidence.
