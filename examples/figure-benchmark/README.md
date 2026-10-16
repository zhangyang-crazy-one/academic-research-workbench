# Public scientific figure benchmark

Issue #153 provides four repository-authored public synthetic tasks, not real
experimental findings or copied paper figures. The frozen facts, conceptual
boundaries, size/profile and license are in `tasks.json`; `tasks.sha256` is checked
before generation. Their first commit precedes rendering. The 180 × 330 mm main
figure profile is an author-defined toy canvas, **not a journal-format claim**.

Run from a checkout with the ARW Python dependencies installed:

```sh
PYTHONPATH=src:extensions/research-artifact/src .venv/bin/python \
  examples/figure-benchmark/run.py build/new-figure-benchmark
```

The output directory must be fresh. The real ARW parent ledger accepts synthetic
JSON and losslessly serialized CSV. Numeric core evaluates raw points, supplied
means and precomputed ranges. The result SVG is a genuinely accepted v1 child;
sequence/graph sources are bound through the existing canonical adapters.
Composition candidates are **not** publication-accepted. No model or API is called.

Rasterization is optional: the default `/usr/bin/python3` must have GI librsvg,
Pango/PangoCairo and pycairo, with fontconfig and RPM font-license metadata. The
recorded execution used Fedora's existing system packages and installed Noto
fonts; it did not add a default runtime dependency. `--raster-python PATH` selects
another prepared optional environment. Missing dependencies/fonts report
`unavailable`, never visual PASS. This is a concrete tested chain, not a mandatory
ARW host/harness/version requirement.

[Retained review packet](evidence/REVIEW.md) links the actual color PNGs, grayscale
PNGs and source/PDF outputs. [Execution report](evidence/report.json) records
actual dimensions, versions, font files/digests and RPM license identifiers. Font
files are not redistributed. SVG remains editable text; PDF editor round-tripping
is not certified. PNGs are generated at the frozen physical size and 150 dpi;
viewers/screens may rescale them, so physical review needs the declared dimensions.

For loop/mixed tasks, row, column and grid change panel organization/read path and
hierarchy while retaining identical content/source digests. The producer's
preselection is column because it gives each panel the full width. This is a
candidate choice **pending independent confirmation**, not an approved best design.
All three actual previews remain available. Do not alter facts or thresholds to
turn a failure into a pass.

The report separates four dimensions:

- **Source/numeric:** canonical binding and exact numeric checks passed at the
  stated synthetic scope. This does not establish scientific validity of real data.
- **Mechanical:** actual raster success/nonempty ink/border screening/Pango coverage
  probe/minimum physical font. Border/Pango probes do not certify all clipping,
  occlusion, glyph appearance or accessibility. Grayscale PNGs support human review.
- **Visual argument:** producer critique and specific defects, without a score or
  authority to approve. Small panels and relation density remain review findings.
- **Independent human:** `pending`; no producer/model self-score is accepted as a
  human decision. `review-pending.json` has blank identity/decision/reason fields.

Actual retained execution: 8 candidates × 5 mechanical checks = 40 observations;
33 passed, 7 failed the frozen 7 pt minimum, none unavailable/not-run. The simple
result panel passes all five screens; it is still pending independent review.
The six controlled fault injections are detected: altered exact number/mark,
reversed directed marker, missing required object, actual blank crop, unknown
glyph and altered series color. This proves coverage of those known injections,
not general machine understanding of arbitrary figures. Faults are observational
files, never admitted as scientific evidence.

`review_state` checks that a supplied non-producer human record includes identity,
reason/decision and the exact binding of task/IR/SVG/PNG/PDF/grayscale/environment/
font evidence. Any bound change makes a previous decision stale. This metadata
helper is **not authentication or publication authorization**. Publication use
still needs parent-owned acceptance of the existing `arw.visual-review.v1`
evidence binding the exact composition IR/SVG; the benchmark never signs it.

All example scripts, tasks and original synthetic outputs are first-party MIT
under the repository's first-party code/data license. Noto font metadata records
OFL-1.1; only raster/PDF outputs, not font source files, are retained. No upstream
scientific-visualization skill, external artwork or publisher asset was copied.
