# Verification

All six foundation tasks are implemented and verified. This change owns AcceptedRef adapters and the independent numeric core, not graph authentication, disclosure extraction or plot rendering.

- Dedicated accepted/numeric tests: 31 passing, including real artifact acceptance, all seven adapter boundaries, SourceLocator v1/v2, project journal refs, fixed run/journal prefixes after torn later tails, lock-contained source verification, lexical JSON precision, exact 1/3, percentage-point/relative-change semantics, stable rows/groups, missing policies, DataSelector mapping, DAG/resource bounds, derivation request identity and schema semantics.
- With coordinated original prefix tests and dependency ratchet/import-order tests: 41 passing.
- After extracting ComparisonContext, legacy experiment acceptance, golden run replay, precise-source integration and dependency tests: 130 passing. Old experiment schemas compare exactly with checked-in documents; the old ComparisonContext import is the same class as the shared state import.
- Earlier broader original integrity/venue/provenance/experiment/golden replay pass: 229 passing before the data-model extraction; the affected extraction paths were then independently revalidated above.
- OpenSpec strict validation passes. Ruff passes for added foundation modules and dedicated tests. The existing experiment_acceptance module has pre-existing lint findings; the extraction adds one import and removes the identical data class without unrelated edits.

Commands use the installed main environment only for dependencies: PYTHONPATH is explicitly this worktree's src, so executable kernel imports use this branch. No new dependency or model call was used.

Schema registry includes only the four foundation schemas. Graph and plot schemas are integrated separately. The approved dependency baseline adds precisely ledger -> policy for lazy delegation of the original integrity validator; extracting shared context prevents state -> artifacts coupling.

Coordinator prefix prerequisite commits are 595767d and ea21cf9. Local cherry-picked equivalents are 47afe5c and 5e52cc9 and should not be applied twice. Foundation commits are 03abe29,796e511,264e6e5,19f103d,87bcd85 and the final documentation/identity commit.
