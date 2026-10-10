# Claim graph and result plot verification

Base: origin/main 71b02ba42dd84fa0789cb7fd6187bfe92cffd384.
Tested implementation: 6d284de9a23cb316064055a2a9aa1bf4bf228170.

## Complete local test scope

The final complete non-host CI command passed with **2278 passed, 89 skipped,
80 deselected** in 441.38 seconds:

```sh
PYTHONNOUSERSITE=1 UV_OFFLINE=1 .venv/bin/python -m pytest -q \
  -m "not codex_host and not v2_compat" tests/
```

The checkout's src/ and extension src/ directories were explicitly supplied
through PYTHONPATH because the shared development venv has an editable main
checkout. The complete tests/ discovery root includes schema validation and
all new modules; this count supersedes the earlier 504-test focused subset.
The dedicated v2 compatibility baseline passed with **74 passed, 3 skipped**
in 51.27 seconds. Review-focused regressions passed with 118 tests; the updated
public CLI time-window cases passed all 9 CLI tests.

The 89 complete-tree skips require unavailable native file-base builds,
retained qualification/candidate/stage evidence, optional offline detector
assets or isolation tooling. The 3 compatibility skips require native
file-base. Host tests are explicitly excluded and compatibility tests run in
their own step. These prerequisites and authority evidence were not
manufactured. All three pinned source snapshots were materialized and
verified. No native patch or vendor source changed in this PR.

The initial complete run found one legacy CLI fixture whose request instant
preceded authentication. The success fixture now uses an applicable instant;
CLI negative cases verify before-anchor and after-expiry refusal. The entire
non-host tree was rerun after that correction and passed.

All 119 registered schemas validate against their model projections. Embedded
CanonicalEvent definitions in both narrative-fit snapshot schemas include the
additive 1.6.0 anchor reader. Legacy experimental schemas and retained receipt
semantics remain unchanged. Changed Python files pass the adopted E4/E7/E9/F
lint rules; new modules pass project lint. All three OpenSpec changes pass
strict validation. Fresh interpreter import-order tests preserve kernel and
writing-engine boundaries.

## PR #96 review boundaries

Launcher coverage verifies each installed command, including claims and
numeric, exports both plugin-root and manifest bindings. Parent admission
verifies the actual external journal and full N-1 vector. Canonical replay
checks run-local hash/prefix/authority invariants without cross-log proof
reads. A real run with 129 independently admitted anchors stays healthy;
run-only archival, corrupt external journal and sibling writer lock do not
block parent health. Re-sealed changed confirmations are unverifiable in
projection and cannot authenticate; local authority corruption still blocks
canonical replay. Each journal read validates each registration once.

A local fixed-prefix microbenchmark, using three repetitions and reporting
the minimum, measured 30 anchors at 0.0093 seconds and 129 at 0.1116 seconds.
This is a local diagnostic, not a cross-host performance guarantee.

Claim writes preserve 256 KiB of the original 1 MiB project-journal budget
for core narrative events. Upgrade/downgrade boundaries are documented:
claim events require claim-enabled readers from PR #96 or later, while
parent anchors require the additive 1.6.0 reader.

Hard caption capture requires an explicit UTC evaluation instant. Parent
qualification uses its request occurred_at, overriding an earlier verifier
instant. No new parent event is needed to detect expiry; before-anchor and
after-expiry checks fail. Historical graph defaults remain deterministic
snapshot-time applicability, separate from a current hard check.

Relative changes accept same-context nonnegative quantities, with zero
baseline undefined and negative inputs out of domain. Percentage-point
comparisons remain normalized ratio/proportion-only. Dense grouped bars fit
their slots, and log bars fail with bar_requires_linear_y.

## MVP limits

Synthetic time/accuracy and observation/mean/precomputed-interval SVG samples
were inspected for local layout. No visual-review signature was created;
publication quality and cross-host font equivalence remain unverified.
Q5 uses parent-anchor occurred_at for historical authentication time. The
bounded MVP remains single-panel SVG and rational operations. TeX/PGFPlots,
SD/SE recomputation, disclosure generation and ReviewConcern are deferred as
specified by the reviewed issues.
