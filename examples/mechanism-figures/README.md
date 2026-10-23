# Source-bound mechanism figures — issue #162, milestone 1

These are repository-owned MIT synthetic examples, not model experiments or
evidence of scientific novelty. They exercise a real accepted source, a separate
`MechanismFigureIR`, editable deterministic SVG, parent-owned qualification,
reproduction and publication blocking without visual review.

The three examples cover token/representation correspondence and a supplied
one-hot sum, tool request/observation/state/conditional return, and an original
constraint/counterexample/guarded state. Values in the mechanism are supplied
source literals; this renderer does not run a new statistical calculation.
Quantitative result figures continue through the existing numeric core.

## Execute

From a source checkout with the project environment and research-artifact
extension available, select a new output directory:

```sh
PYTHONPATH=src:extensions/research-artifact/src .venv/bin/python \
  examples/mechanism-figures/run.py build/mechanism-example
```

This runs no model or rasterizer and reports pixels as unavailable. If the
optional local GI/librsvg/Pango/Cairo/fontconfig environment is already installed:

```sh
PYTHONPATH=src:extensions/research-artifact/src .venv/bin/python \
  examples/mechanism-figures/run.py build/mechanism-pixels \
  --raster-python /usr/bin/python3

.venv/bin/python examples/mechanism-figures/prepare_review_cases.py \
  build/mechanism-pixels build/mechanism-truth.json
```

The latter prepares six actual pixel controls. Give `reviewer-input.json` and
`reviewer-blind-cases.json` to a separate read-only figure-reviewer; withhold the
truth file, producer evaluation and injection code during that review. No
dependency is installed or external service activated by either command.

The author-defined profile is 180 mm wide, at least 8 pt text and 150 dpi raster
previews. These are measured example choices, not universal publication rules,
required harness versions or venue certification. A different profile needs its
own actual final-size review.

## Retained actual evidence

- [Summary and limits](evidence/summary.json).
- [Round 1 independent review](evidence/reviews/round1.md) and
  [round 2 comparison](evidence/reviews/round2.md), with complete JSON records.
- Actual [representation](evidence/round2/representation.png),
  [tool loop](evidence/round2/tool-loop.png) and
  [constraint](evidence/round2/constraint.png) PNGs. Each directory also contains
  SVG, vector PDF, grayscale PNG, IR, exact bindings and the canonical run.
- [Blind-case truth](evidence/reviews/negative-truth.json), opened only after
  the independent review; [full stop-text omission supplement](evidence/round2/supplemental/report.json).
- [Byte inventory](evidence/manifest.json), including the quiescent run lock
  files required by ledger replay. The examples contain no active process locks.

The original reviewer records retain their actual `build/mechanism-162-*` paths.
`review-one` maps to `evidence/round1`, `review-final` to `evidence/round2`, and
`independent-review` to `evidence/reviews`. No original report was rewritten to
change its observations. Reference-paper pixels were inspected locally, but
publisher/preprint images and PDFs are not redistributed here. The review links
the official OpenHands paper and identifies the actual VGGT author-preprint
version used after the requested proceedings PDF was unavailable.

`tasks.v1.json` and its SHA retain the original frozen answer. The independently
identified missing counter convention was explicitly corrected in revision 2
before the next render: initialization, increment and found/missing alternatives
are source-author-defined synthetic facts. Revision 2 names the original SHA.
Other scientific answers remain unchanged; layout changes are separately visible
in the source revisions. Rendering does not invent these missing steps.

The two actual advisory rounds used separate Codex producer/reviewer roles with
`gpt-6.1-sol/high`. This is an observed development environment, not a product
restriction or statistical independence claim. Reviewer records contain actual
sampled time and tool counts; token and monetary metering were unavailable.

## Results and remaining work

Structural comparison observed 3 normal figures without differences and 16
detected injected controls including the supplement. It compares frozen answers
with visible SVG content, ports and arrow geometry; it is not pixel comprehension
or proof that the source's method is scientifically complete.

The independent reviewer observed the specific difference in each of 6 blind
images. Case 4 changed the **stop role label**, leaving its predicate intact;
it must not be counted as complete stop-condition omission. The latter has a
separate actual raster and structural check, with independent pixel review
explicitly `not_run` after the two-round budget. No broad sensitivity or
specificity estimate is asserted from this small, purpose-built sample.

Two original findings were resolved, three partly resolved. Remaining issues
include local label placement, coordinate-wise vector explanation, highlighting
the changed guard, a split `counterexample` label, and ambiguity between one-time
initialization and the retry target. They remain findings, even though mechanical
checks and source-consistency qualification pass.

All visual results remain **human_pending**; no publication visual PASS exists.
The optional backend can be unavailable, and missing/mismatched review blocks
publication acceptance. Original v1 result/schematic/composition contracts and
renderers are unchanged. Round 1's unreleased prototype mechanism pin is retained
for audit; its renderer is unavailable in the revised implementation rather than
silently substituted.

Later #162 milestones remain open: three genuinely different explanation
strategies and selection evidence, remaining mechanism/visual findings,
independent human acceptance, and an optional draw.io adapter with real editor
round-trip and publication privacy checks. General attention/tensor graphics,
automatic layouts and arbitrary editor import are unsupported in this milestone.

## Round3 repair packet (2026-10-23)

The [round3 packet](evidence/round3/README.md) implements the retained normal
figure repairs and provides [new exact-output reviewer inputs](evidence/round3/reviewer-input.json).
It is producer evidence awaiting independent pixel/reference review, not a third
review or acceptance. Round1/2 evidence is unchanged. Revision 3 preserves
`tasks.v2.json` and SHA, decomposes initialization from the repeated request, and
makes the supplied coordinate/rule expansion explicit. The
[mechanical record](evidence/round3/mechanical.json) verifies v2 scientific fact
preservation after that declared decomposition.

Reproduce into a **new** directory using the run command above, then screen actual
font ink bounds and local-label edge clearance with the optional GI interpreter:

```sh
/usr/bin/python3 examples/mechanism-figures/check_readability.py build/mechanism-pixels
```

The [task 3.2 assessment](strategy-assessment.md) records available source facts,
the missing representation control/treatment and implementation steps. The new
coordinate table and guard diff do not count as three explanation strategies.
