# Failed experiments through the governed writing path

This deterministic integration pilot exercises existing runtime capabilities. It
is **not** a claim that arbitrary final-report prose is semantically verified.
There is no production behavior change in this pilot.
`evals/experiment_reporting.py` supplies a pilot-only deterministic outcome renderer.

## Reproduce

From the checkout, with the development environment installed:

```sh
PYTHONPATH="$PWD/src:$PWD/extensions/academic-humanization/src" \
  .venv/bin/python -m pytest -q \
  tests/integration/test_failed_experiment_report_chain.py \
  tests/unit/test_claim_experiment_replay.py \
  tests/integration/test_writing.py \
  tests/integration/test_experiment_provenance.py
```

The new test module has eleven cases, including receipt-identity, invalid-comparison
output-isolation, and damaged-evidence regressions. Its temporary run directories retain the
canonical journals, content-addressed contracts/provenance/acceptance receipts,
report source, writing bundles and synthetic human-review fixtures. Pytest's
`--basetemp` option can put these artifacts in a chosen disposable directory.
No real solver, LLM, human reviewer or external dataset is used.
Receipt binding uses the claim revision’s exact evidence node and accepted
reference, not equality of numerical check outputs. Invalid comparison evidence
is blocked rather than counted as an honest negative. Retained outcome data is
canonically copied before hashing, isolating it from later graph mutation.
All-passed numeric conformance is explicitly tested as `unverified`; deleting or
tampering with an otherwise honest-negative CSV changes a fresh replay to
`unverified`, not `negative_result`.

## Observed chain

Each case admits a contract through `RuntimeCommandService`, attempts provenance
admission, evaluates numeric acceptance, admits the acceptance artifact, replays
it through ClaimGraph, binds an `ExperimentResult` to an actual report occurrence,
and runs the report through `WritingService.prepare` and `record`. The pilot also
derives a structured outcome from those actual checks and execution policy,
renders a deterministic outcome section, and admits a `pilot-final-report` JSON
artifact containing both. It binds the exact accepted experiment reference,
ClaimGraph snapshot, result digest, outcome digest and section digest. Generic
artifact admission is deliberately distinguished from trustworthy check results.

| Case | Observable evidence | Replayed checks | Honest report |
| --- | --- | --- | --- |
| Input read fails; synthetic substitute attempted | Real missing-file read followed by source-digest mismatch; provenance admission rejected | `not_checked`, even though substitute numeric mean conforms and a generic receipt was admitted | Accepted after fixture review, with source failure preserved |
| Solver never starts | Controlled execution policy says `BLOCKED`, subprocess permission false; execution-log artifact only, requested scores absent | `failed` (contract names an absent artifact) | Accepted after fixture review, with non-execution preserved |
| Silently shrunk scope | CSV has one sample; declared count metric requires three | Mean `passed`, sample-count check `failed` | Accepted after fixture review, with scope failure preserved |
| Honest negative result | CSV mean is 0.75; baseline is 0.9 | Reproduction `passed`, improvement `failed` | Accepted after fixture review, without inventing an improvement |

The first three adverse scenarios cannot obtain all-passed ClaimGraph checks.
The honest negative is not rejected as an invalid artifact merely because the
improvement criterion fails. All four report sources explicitly protect their
outcome sentence and the statement that verified success is not established.
Replacing these with a success-only report is hard-rejected, including when a
fixture reviewer tries to approve that exact rejected candidate.

The generated structured outcomes are respectively `unverified`, `blocked`,
`blocked`, and `negative_result`. All four sections state that verified success
is not established and enumerate the check statuses and blocker reason codes.
The runtime currently offers no qualified execution evidence authorizing a
`verified_success` label, so even all-passed numeric conformance alone must remain
`unverified`; the pilot does not pretend to have a positive execution verifier.

## Numerical pilot summary

- Generated false-success labels: **0/3 adverse scenarios**.
- Unsupported success-only rewrites rejected: **3/3 adverse scenarios**.
- Honest negative reports accepted: **1/1**, false rejects **0/1 (0%)**.
- Honest failure/negative reports accepted across all scenarios: **4/4**.
- Automatic acceptance of the explicit contradictory appended conclusion: **0/1**.
- Contradictory appended conclusion admitted after an incorrect fixture review:
  **1/1**, an explicit limitation rather than a successful truth check.

These tiny deterministic fixtures are coverage evidence, not estimated population
error rates. Fixture reviews are not genuine human or model judgments.

## Boundaries and remaining work

The acceptance receipt says `contract_conformance_only` and explicitly records
external execution timing as unobserved. The controlled execution adapter remains
disabled; this test observes its decision, not a real solver startup failure.
The substitute case pins original source identity; it does not detect a caller
who rewrites provenance to declare a different dataset. The sample-count case
requires a declared count and truthful expected-count metric; it is not a general
scope or authorization detector. External provenance remains imported evidence.

The governed writing path has no automatic ClaimGraph-to-prose truth binding.
The author explicitly provides protected spans. They stop removal/reversal of
those spans, but cannot stop appending a contradiction while leaving them intact.
The fifth test demonstrates that appending “The experiment was a verified
success.” needs review, declares semantic equivalence unproven, and can be
admitted by an incorrect reviewer. Artifact acceptance does not certify that
sentence as true. The same risk exists with or without protected spans.

A general no-false-success guarantee for free-form prose therefore remains
**unimplemented**. The pilot constrains its generated machine-readable outcome
and deterministic section only; it is not automatically used by production
report-writing entrypoints. A future production report-outcome contract should
adopt these evidence bindings and define qualified positive execution evidence. Free-form
narrative still needs contextual review. A lexical blacklist or reinterpreting
all failed experimental hypotheses as invalid reports would be misleading and
would risk rejecting valid negative findings.
