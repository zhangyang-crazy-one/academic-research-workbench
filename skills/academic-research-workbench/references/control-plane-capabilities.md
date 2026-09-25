# ARW control-plane capabilities

These are routes under the installed `academic-research-workbench` skill, not
independent trigger descriptions. Resolve `<installed-plugin-root>` as the parent
of `skills/`. The parent runtime alone writes canonical state.

| Request | Route and boundary |
| --- | --- |
| General run/research status | `bin/arw route --json` for workflow selection; `bin/arw status --run-root RUN --json` for existing run state. Do not infer a different family or permission. |
| Literature review, citation methods, peer review, experiment design | Read `academic-research-suite/SKILL.md` and its selected `ars/*/WORKFLOW.md`; do not use a generic control-plane query as a substitute. |
| Bounded local files and search | `bin/arw files status --control-root ROOT --root-id ID`; MCP exposes `list_files`, `read_file`, `search_files`, `get_outline`, `get_context` under the parent-supplied root. Stale metadata needs explicit parent sync. |
| Research graph and assertion provenance | Read `bin/arw status --run-root RUN --json`, then query the graph capability. The graph is a rebuildable projection; every accepted assertion requires an admitting ledger event. |
| Evidence access and artifact integrity | Inspect the run's accepted artifact/evidence state through parent commands. Reads are bounded and digest-bound; a worker's output cannot admit itself. |
| Audit replay | `bin/arw replay --run-root RUN` and `bin/arw status --run-root RUN --json`. The append-only ledger is authoritative. |
| Writing record | Read [writing revisions](writing-revisions.md); prepare and record source-bound proposals through `bin/arw writing`, with parent-controlled review/admission. |
| Manuscript submission packets and outcomes | Read `submission/SKILL.md`; readiness and portal results are distinct from writing and review methodology. |

For experimental survey research, the opt-in STORM path is described in the
parent skill. It requires the user's explicit request and produces pre-writing
material only; it does not create canonical experiment evidence.
