# Claim graph and result plot verification

Base: origin/main 71b02ba42dd84fa0789cb7fd6187bfe92cffd384.
Tested implementation: 1146eadcacb0cafef27856dcd3ec2bd47c142f6e.

The combined local regression run completed with **504 passed, 4 skipped** in
159.78 seconds. It included every new reference, numeric, graph, authentication,
historical segment, plot, caption and public CLI test; existing reducer,
orchestration, narrative/writing, experiment, durable runtime and segmented
journal regressions; and all tests/schema and tests/compat suites.

Three skips require a qualified native file-base executable. One additionally
requires gated candidate wheel/build evidence and materialized vendor sources.
These prerequisites were not manufactured in the feature checkout. This
change modifies no native patch or vendored source.

All 119 registered schemas validate against their model projections. Embedded
CanonicalEvent definitions in both narrative-fit snapshot schemas were updated
for the additive 1.6.0 anchor reader. Legacy experimental schemas and retained
receipt semantics remain unchanged.

All changed Python files passed the adopted E4/E7/E9/F lint rules; newly added
Python files also passed the project lint rules. All three OpenSpec changes
passed strict validation. Fresh interpreter import-order tests cover the
reviewed lazy parent-writer dependency; kernel/CLI writing-engine imports
remain prohibited.

Synthetic time/accuracy and observation/mean/precomputed-interval SVG samples
were rasterized with existing local tools and inspected. This checks basic
local layout only. No visual-review signature was created; publication quality
and cross-host font equivalence remain unverified.

Q5 uses an accepted parent-ledger anchor: its occurred_at supplies the
authentication instant. Historical authorization, current claim/evidence
applicability and explicit-time expiry remain separate. Hard checks default
off, require actual authority proof, and return nonzero on failure.

The bounded MVP remains single-panel SVG and rational operations. TeX/PGFPlots,
SD/SE recomputation, disclosure generation and ReviewConcern are deferred
as specified by the reviewed issues.
