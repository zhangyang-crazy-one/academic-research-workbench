# Strict Academic SVG Box-Diagram Standards

Use this reference only when the user explicitly requests a strict academic SVG
box diagram, framework diagram, workflow diagram, research-content diagram, or
evidence-chain diagram. The explicit choice of a box diagram overrides the
suite's non-boxed main-figure default for that artifact only.

Do not apply this reference to statistical charts, heatmaps, primary research
images, mechanism illustrations, graphical abstracts, or general infographics
unless the user explicitly chooses a box-diagram form for the requested
artifact.

## 1. Freeze Meaning Before Geometry

Write a relationship contract before drawing. For every connection, record:

| Source | Target | Direction | Short label | Intended meaning |
|---|---|---|---|---|
| module or object | module or object | one-way or feedback | manuscript term | input, constraint, execution, evidence, evaluation, or iteration |

Apply these rules:

- Give every arrow one defensible semantic role. Do not use arrows merely to
  fill empty space or imply a vague association.
- Distinguish a sequence from a dependency, an evidence transfer, and a
  feedback loop. Encode different meanings consistently.
- Keep output ownership precise. A platform or workflow may output data
  products, logs, versions, and observations; an evaluation module should own
  evaluative conclusions, effect judgments, and applicability boundaries.
- Route feedback to every module that the feedback actually revises. Do not
  terminate a general design-iteration arrow at only one affected module.
- Treat parallel evidence categories as parallel categories, not as a temporal
  sequence. When one source supplies several categories, use a common rail or
  bus and branch to each category.
- Do not let a common-evidence arrow visually terminate at one evidence box if
  the prose claims that it feeds all boxes.

## 2. Use a Restrained Academic Visual Grammar

- Prefer two to five main modules, with an optional narrow scope/input column.
- Build each main module from a consistent outer frame, title band, and inner
  content boxes. Align corresponding title bands and content rows.
- Use square corners or a very small corner radius. Avoid interface-card
  styling, pills, decorative containers, icons, shadows, gradients, glossy
  effects, perspective, and three-dimensional decoration.
- Use low-saturation module colors with adequate grayscale contrast. Never rely
  on color alone to communicate direction, category, or status.
- Keep the root background white and preserve generous exterior margins.
- Keep the image free of a visible figure title. Put the figure number and title
  in the manuscript caption. Visible text should be limited to module names,
  object labels, relationship labels, and concise explanatory phrases.
- Do not introduce bars, bands, or filled lengths that could be mistaken for
  quantitative encoding unless they represent actual measured quantities.

## 3. Establish a Typesetting Hierarchy

- For Chinese manuscript figures, prefer Source Han Serif, Noto Serif CJK SC,
  SimSun, or the thesis-specified Chinese font. Use a Times-compatible face for
  Latin letters and numerals when required by the institution.
- Define a small, stable hierarchy: module identifier, module title, inner-box
  title, explanatory text, and edge label. Reuse it across the entire figure.
- Use Chinese academic terminology rather than literal English calques. At the
  first occurrence of an imported technical term, use the manuscript form
  `中文术语（English Full Name, ABBR）` when the English name or abbreviation is
  needed.
- Set text with editable SVG `<text>` elements. Do not rasterize labels.
- Treat wrapping as explicit geometry. SVG `<text>` does not wrap automatically;
  split long labels into separate `<text>` lines or use `<tspan>` elements with
  explicit `x` and `dy` values before the label approaches its container edge.
- Preserve at least 8--12 viewBox units of horizontal padding around ordinary
  box text and at least 6 units vertically. A string that technically fits but
  falls below this clearance fails the typesetting gate.
- Do not rely on centered mixed-font `<tspan>` runs or `baseline-shift` for
  compact formulas and subscripts without testing the production renderer.
  Some SVG renderers recenter individual runs and make glyphs overlap. Prefer a
  single plain-text notation or separately positioned text runs when portability
  matters.
- Check legibility at the intended insertion width, not only on a zoomed editing
  canvas. Shorten wording before reducing type below the manuscript's readable
  threshold.
- Do not rotate Chinese edge labels. Offset vertical-connector labels beside the
  line and keep their glyphs horizontal.

## 4. Draw Orthogonal, Constant-Scale Arrows

- Use horizontal and vertical segments. Avoid diagonal connectors unless the
  diagram's argument cannot be expressed orthogonally.
- Eliminate edge crossings. Reorder modules, add a rail, or reserve a routing
  corridor before accepting a crossing.
- Terminate the shaft at the target boundary. The arrowhead must remain outside
  the target's text area and must not visually penetrate the box.
- Use `markerUnits="userSpaceOnUse"` so arrowheads retain a constant visual size
  across strokes and short connectors. Do not use the default stroke-scaled
  marker when it makes short-arrow heads disproportionately large.
- A reliable baseline marker for a medium-size academic canvas is:

```svg
<marker id="arrow" markerWidth="14" markerHeight="12"
        refX="13" refY="6" orient="auto"
        markerUnits="userSpaceOnUse">
  <path d="M0,0 L14,6 L0,12 Z" fill="currentColor"/>
</marker>
```

- Scale this baseline only once for the whole figure. If branch arrows require a
  second marker, define one deliberately smaller constant-size marker and use it
  consistently.
- As a starting geometry check, reserve about 28--36 viewBox units of free span
  for a short connector using a 14-unit arrowhead. Increase the span when it
  also carries a label.
- As a starting style check, use roughly 2.6--3.0 viewBox units for major
  inter-module connections and 2.0--2.4 for internal workflow arrows, then
  adjust proportionally to the canvas and final print size.
- Use solid lines for the principal route and a clearly defined secondary style,
  commonly a dashed line, for feedback or iteration. Explain the distinction in
  the caption when it is not self-evident.

## 5. Reserve Space for Relationship Labels

Relationship labels are part of the geometry, not an afterthought.

- Estimate or measure the rendered label width before fixing module positions.
- Reserve a horizontal gap at least equal to the label width plus approximately
  16--24 viewBox units of side clearance. If the label does not fit, widen the
  gap or shorten the label; do not let it overlap a module border.
- Place horizontal labels above the line or interrupt the line behind the label.
  Place labels for vertical connections 8--12 viewBox units to one side of the
  shaft.
- Use one edge-label font size, weight, color, and baseline convention throughout
  the figure.
- Put a white, stroke-free knockout rectangle behind a label when a line, border,
  or nearby content could reduce legibility. A useful starting padding is 8
  units horizontally and 4 units vertically.
- Keep the knockout local. It must not hide arrowheads, target borders, branch
  points, or semantically meaningful line segments.
- Never place text directly across a module border. A label that appears to sit
  on a border makes the connection endpoint ambiguous.

## 6. Express One-to-Many Evidence and Feedback Correctly

- Use a common rail for one source feeding two or more parallel objects. Connect
  the source to the rail, then branch with separate arrowheads into every target.
- Keep branch points visually explicit and aligned. Avoid accidental T-junctions
  that could be read as crossings.
- If categories are ordered only for layout, do not connect them with sequential
  arrows.
- Separate forward execution/evidence flow from backward evaluation/design
  feedback. Use direction, routing corridor, and line style together rather than
  color alone.
- Check that the diagram agrees with the surrounding prose about which evidence
  supports which conclusion and which module is revised by feedback.

## 7. Keep the SVG Deterministic and Editable

- Use native SVG shapes, paths, and editable text.
- Do not embed `<image>` or `<foreignObject>` elements in the canonical figure.
- Permit `<title>` and `<desc>` metadata for accessibility, but do not render
  production notes, prompts, audit comments, or conversational explanations.
- Centralize fonts, strokes, fills, and label backgrounds in CSS classes or
  reusable attributes so global corrections remain deterministic.
- Use a stable `viewBox` and export from the same canonical SVG. Do not manually
  redraw the PNG version.

## 8. Run a Rendered-Image Audit

Validate source and rendering; source inspection alone is insufficient.

1. Run `xmllint --noout figure.svg` or an equivalent XML validator.
2. Confirm that the canonical SVG contains no `<image>` or `<foreignObject>`.
3. Render a one-times preview in a standards-compliant browser.
4. Read the rendered `getBBox()` of every `<text>` node and compare it with its
   intended containing rectangle. Reject any negative margin and any ordinary
   box label with less than 8 viewBox units of horizontal clearance. Do not limit
   this audit to edge labels or visually obvious long strings.
5. Inspect centered mixed-script labels, formulas, subscripts, and every explicit
   line break in the same renderer used for final PNG/PDF export. Check that text
   runs remain ordered and do not recenter or overlap.
6. Inspect a crop of every external arrow, arrowhead, branch, and relationship
   label. Check the actual pixels for border collisions, oversized heads,
   clipped glyphs, and ambiguous endpoints.
7. Inspect the entire figure at the intended manuscript insertion size.
8. Correct the SVG geometry, rerender, and repeat the audit.
9. Produce the final raster derivative at two-times resolution when a PNG is
   required, while retaining the SVG as the editable source.

## 9. Acceptance Gate

Do not deliver the box diagram until all answers are yes:

- Does every arrow have the correct source, target, direction, and meaning?
- Are all main paths orthogonal and free of crossings?
- Are arrowheads constant in scale and outside target content areas?
- Does every relationship label have sufficient reserved space and a consistent
  baseline?
- Are labels free of line, border, and arrowhead collisions at target size?
- Does every box label remain inside its container with the required safety
  padding after actual rendering, with all intended wrapping made explicit?
- Are mixed Chinese/Latin text runs, formulas, and subscripts free of reordered
  or overlapping glyphs in the production renderer?
- Are one-to-many evidence relations drawn with an explicit rail or branches to
  every target?
- Are platform observations separated from evaluation conclusions?
- Do feedback arrows reach every module they are claimed to revise?
- Are all visible strings manuscript-facing rather than conversational?
- Is all text editable, with no embedded raster or HTML content?
- Is the figure free of an in-image title and false quantitative encodings?
