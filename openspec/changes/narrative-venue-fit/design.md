# Narrative venue fit design

Capture verifies the selected narrative and canonical accepted artifact event,
then reads the exact retained manuscript bytes. An accepted narrative-draft
sidecar can be used directly. For a failing proposed realization, an accepted
manuscript source plus explicit proposed sidecar is allowed; the source digest
must agree. The existing narrative realization validator produces the
structural PASS or a stable FAIL reason code. It does not assert semantic
truth.

With only `--run-root` and `--target`, capture selects the latest accepted
draft event and maps the requested target from the bundled annual venue
registry. The conversion freezes exact registry bytes and locators; its
natural-language hard-gate strings have no typed predicate and remain unknown.
No per-rule official URL is synthesized from a registry-wide source list.
Explicit manuscript and reviewed profile inputs override these defaults.

The venue profile freezes its exact bytes, SHA-256 and version. Each official
rule has a URL, source digest and locator; a typed predicate requires reviewer
attribution. Unbound natural-language requirements remain unknown. Exact
headings and literals are bounded observations. A page limit uses only bytes
from an accepted PDF, frozen and re-counted during replay. A listed-marker
absence never establishes comprehensive anonymity.

Only promoted heuristics applicable to the requested venue and domain enter
the empirical layer. Capture calls the learning service's validated inspection
path and freezes the inspected record digest, promotion event, support,
counterexample and unknown evidence. A heuristic match needs a reviewed typed
predicate. The report does not aggregate counts into a probability.
When no heuristic was selected, `empirical_status` is `not_evaluated`;
an absent reviewer judgment is explicitly `not_supplied`.

The snapshot embeds the manuscript, realization, profile, referenced accepted
predecessor/evidence manifests and content, plus optional PDF bytes. Replay
checks all digests, recomputes the realization result and page count, and
returns the same deterministic report without reading the active run. This
guarantees repeatability for a captured local snapshot; its original ledger
authenticity is established at capture. A separate freshness request compares
the active narrative and profile bytes and uses explicit `--as-of` against the
profile review date. Reviewer judgment binds the frozen input digest and may
include a model/provider/prompt version, but the command makes no model call.

The report is advisory. A typed mismatch yields a review suggestion; it does
not mutate the selected plan, accepted artifacts, or journal.

## Explicit public evidence mode

`--without-selected-narrative` is an additive opt-in for a run without a narrative
binding. It requires an accepted artifact ID and a separate
`arw.narrative-fit-public-snapshot.v1` contract; the selected-narrative v1 contract
is unchanged. Public proof embeds accepted event, manifest and content bytes.
Capsules retain their own digest separately from the reviewed external PDF
digest and never stand in for full manuscript text or retained PDF bytes.
Replay verifies each proof and exact profile bytes. Only actual accepted PDF
bytes establish page counts, and capsule-linked PDF bytes must match the recorded
PDF digest. Structural narrative assessment stays UNKNOWN/not_evaluated. The
bounded mode declines realization, heuristic selection and judgment options;
unpromoted source annotations cannot enter the empirical layer. Empty audit
profiles explicitly mark official requirements not supplied/not_evaluated.
