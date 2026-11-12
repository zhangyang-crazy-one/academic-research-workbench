# Figure role and instruction priority (ARW overlay)

Before loading a visualization agent or image-generation template, prepare a
brief and run `codex/scripts/route_figure.py --brief FILE`. This is an instruction
planner, not a renderer, source verifier or acceptance authority. Its immutable
role names do not replace runtime artifact kinds. The machine-readable
[applicability matrix](figure_role_rules.json) is the effective checklist.

Record the single visual argument, scientific objects, relationship/comparison,
physical width/height in millimetres, font family, backend and required
capabilities. Choose `audit_view`, `quantitative`, `schematic` or `composite`;
route 2–4 composite children independently. Do not infer support from a prompt.

| Role | Applicable constraints | Excluded global defaults |
| --- | --- | --- |
| audit_view | evidence/state/limitations; source and output safety | publication-layout claims and statistics-only axes/APA |
| quantitative | exact data/interval meaning; honest axes/units and comparison | schematic depth requirements and generic decorative templates |
| schematic | scientific objects, typed relations, source-linked meaningful depth | mandatory statistical axes, APA chart checklist, universal boxes |
| composite | panel argument, reading order, shared meaning; each child's role | applying the quantitative checklist to every panel |

Scientific facts, source boundaries, exact values and output safety are
invariant. Apply **verified** venue constraints and explicit author choices
within their scope, then the matching role rules, then optional style choices.
A source URL or a `checked_at` string is not proof of venue verification. The
planner reports supplied venue records as requiring verification, and reports
font/title conflicts for resolution. Do not turn its output into venue approval.
When verification and author requirements materially conflict, record both
requirements and resolve the conflict before finalizing; do not silently choose.

Use one declared font family in a task; final font availability, glyphs and
physical size must be checked on the real output. The v1 backends have a fixed
Noto Sans CJK stack. An author/venue font that differs is a reported capability
gap, not permission to substitute a font while claiming compliance. Default
figure titles remain in the caption; panel tags and short scientific labels
remain on the canvas. A verified venue exception must be resolved explicitly.

`flat_minimal_muted` is an optional author-selected profile. It is not a
universal gate. Colour, texture, contrast and spatial depth must carry
explainable scientific meaning; no complexity or decoration reward is implied.
Sourced spatial mechanisms may use depth. Perspective that distorts ordinary
quantitative comparisons is blocked. Backend support for depth is a separate
question: the v1 deterministic SVG backends do not implement spatial geometry.

Load the [strict box workflow](../../ars/academic-paper/references/academic_svg_box_diagram_standards.md)
only for `strict_box=true`. This preserves explicit strict-box authoring without
claiming that a v1 renderer satisfies its additional geometry checks. Otherwise
choose the layout from objects and relations, including a simple loop or boxes
when those communicate the paper accurately.

The upstream main-figure and image-generation references retain their original
provenance. Use their matching scientific guidance selectively; do not reload
`visualization_agent`'s entire `All Figures` statistics checklist or generic
image style defaults as additional normative instructions. Image-model
eligibility, truthful disclosure and source restrictions still apply. Current
v1 outputs remain single-panel; unsupported histograms, multiple panels,
custom fonts, strict-box certification or depth must be reported unavailable.

Six synthetic public briefs and saved routing outputs live in
`codex/tests/fixtures/figure_roles/`. They test instruction selection, not visual
quality. They contain no private manuscripts, external artworks or model calls.
