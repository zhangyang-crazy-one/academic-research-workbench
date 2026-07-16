# AI-Assisted Scientific Image Generation Protocol

Use this reference when ARS uses an image model to ideate, draft, critique, or
revise a manuscript-facing figure: graphical abstract, mechanism schematic,
experimental workflow, model architecture, method overview, teaser figure, or
conceptual research diagram.

## Core Rule

Treat an image model as a **scientific schematic sketch and layout generator**.
Do not treat it as a generator of real data figures, experimental observations,
clinical images, microscopy panels, western blots, heatmaps, statistical plots,
or any evidence-bearing primary research image.

Data plots and experimental/clinical images must come from the underlying data,
instrument, or reproducible analysis workflow. Image models may help propose a
layout or conceptual visual metaphor, but the evidence-bearing final artifact
must remain data-derived, auditable, and venue-compliant.

## Figure-Type Eligibility Gate

Before using image generation, classify the requested figure.

| Figure type | Image-model suitability | Required handling |
|---|---:|---|
| Graphical abstract / visual abstract | High | Use for composition, visual metaphor, layout, and exact short labels; inspect all text. Disclose only if the final manuscript contains AI-generated image content or the venue policy requires process disclosure. |
| Conceptual mechanism schematic | Medium-high | Use for conceptual relationships; verify every scientific element against manuscript evidence or cited literature. |
| Experimental workflow diagram | High | Use for pipeline sketch, icon style, and arrow relationships; final step labels should be human-edited or vectorized. |
| Model architecture / method overview | Medium-high | Use for overall layout; module names, formulas, variables, losses, and metric values should be edited in deterministic vector/text tools. |
| Motivating case / task example figure | Medium | Use only when exact short labels and short evidence snippets can be rendered and inspected. If the figure contains long passages, rules, prompts, or outputs, prefer deterministic PDF-native text boxes. |
| Prompt, rubric, or task-design figure | Low-medium | Use image generation for layout ideas only. Final long prompt/rubric text should normally be produced as deterministic LaTeX/SVG/PDF text, unless the user explicitly requires image-gen and the generated text passes exact-text QC. |
| Data chart, statistical figure, heatmap | Low | Do not directly generate with an image model; use Python/R/GraphPad/Origin or equivalent from source data. |
| Main result table, taxonomy table, dataset-statistics table | Prohibited as image generation | Produce as LaTeX/booktabs, Markdown draft, CSV, or deterministic vector/PDF table. Do not image-generate table cells or numeric values. |
| Microscopy, western blot, tissue section, gel, CT/MRI, pathology, patient image | Prohibited or extreme risk | Do not generate, alter, or "improve" as research evidence. Use original data and journal-compliant image processing only. |

If the figure mixes safe schematic elements with data-derived panels, generate
only the schematic layer. Data panels must be inserted from verified sources.

When a published paper figure is used as a reference, use it only to identify
the artifact type and scholarly function. Do not ask an image model to recreate,
copy, trace, or closely imitate that figure's protected expression, exact
layout, distinctive icon set, color arrangement, example content, or wording.
The generated or redrawn figure must use the user's own labels, data, examples,
evidence, and a meaningfully different composition.

## Publisher and Venue Policy Gate

Policies differ and change. Before final submission, verify the target venue's
current author instructions and AI policy. Use these anchors as policy patterns:

| Policy pattern | Operational rule |
|---|---|
| Elsevier-style explanatory-image allowance | Some explanatory images such as workflows, timelines, and conceptual schematics may be AI-assisted under human supervision and disclosure when the AI-generated image itself is part of the submitted artifact. Data visualizations must come from underlying data and reproducible analysis. |
| Nature Portfolio / Springer Nature stricter image policy | Assume AI-generated images or videos are not allowed in submitted research content unless a venue-specific exception clearly applies. Prefer deterministic redraws; do not label an internally referenced sketch as AI-generated manuscript content after a clean manual redraw. |
| Taylor & Francis-style image integrity policy | Do not use generative AI to manipulate images, raw research data, clinical images, or experimental observations. Keep working records only when the submitted artifact directly contains AI-generated image content or the venue requires process-level disclosure. |
| PLOS-style disclosure responsibility | Authors remain responsible for accuracy, attribution, and disclosure of AI-assisted manuscript content. |

Policy anchors to verify before submission:

- Elsevier generative AI policies for journals: https://www.elsevier.com/about/policies-and-standards/generative-ai-policies-for-journals
- Nature Portfolio AI editorial policy: https://www.nature.com/nature-portfolio/editorial-policies/ai
- Taylor & Francis images and figures policy: https://authorservices.taylorandfrancis.com/editorial-policies/images-and-figures/
- PLOS Research Integrity and Publication Ethics: https://plos.org/research-integrity-and-ethics/
- Nature research figure specifications: https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/

Do not copy policy commentary or source URLs into manuscript figures or captions
unless the paper explicitly studies publication policy. Keep policy records in a
separate audit artifact.

### Disclosure Boundary

Do not mark a figure as AI-generated merely because an image model was used as
an internal brainstorming sketch, composition reference, or layout exploration
and the submitted figure is manually redrawn or deterministically recreated.

Use AI disclosure or AI-use records only when at least one condition applies:

- the submitted manuscript figure directly contains AI-generated pixels,
  shapes, icons, textures, backgrounds, or other generated visual content;
- the venue explicitly requires disclosure of image-model use even for internal
  figure ideation or layout assistance;
- the figure is an explanatory image submitted as an AI-assisted image rather
  than a clean human/vector redraw;
- the work's methodology or audit package intentionally reports AI-assisted
  figure generation as part of the research process.

For non-data conceptual schematics, workflows, model overviews, and graphical
abstracts that are manually redrawn from an AI layout sketch, keep the sketch as
temporary design material if useful, but do not put AI-use labels in the figure
or caption by default.

## Professional Figure Standards

Use these rules for all scientific figures, whether AI-assisted or not.

1. **One figure, one claim**  
   Write a one-sentence message before designing the figure. Every visual element
   must support that message or be removed.

2. **Clear hierarchy**  
   Readers should see the overall structure first, the main path second, and
   details last. Use left-to-right for process, top-to-bottom for hierarchy,
   center for core mechanism, and perimeter for inputs/outputs/conditions.

3. **No in-image figure title**  
   For manuscript figures, do not place the figure title inside the image.
   Figure names, explanatory titles, and long framing sentences belong in the
   caption or manuscript body. Visible text inside the figure should be panel
   tags, object labels, task labels, short method labels, or short evidence
   labels only.

4. **Consistent visual encoding**  
   Use the same color, arrow type, line style, and shape for the same meaning
   throughout a figure and across a figure group where possible.

5. **Formal manuscript typography**  
   Match the figure typography to the paper's declared output format. For the
   ARS default LaTeX/PDF stack, use Times New Roman or a metric-compatible
   Times family for Latin text, Source Han Serif / 思源宋体 for Chinese text,
   and Courier New or a metric-compatible monospace only for code. If Source Han
   Serif is unavailable in the local renderer, use a CJK serif equivalent such
   as Noto Serif CJK or SimSun rather than a UI sans-serif fallback. Do not use
   generic rounded, app-dashboard, or presentation-style fonts in final
   manuscript figures unless the target venue template explicitly requires them.

6. **Short, precise text**  
   Current image-generation models can render precise short text when prompted
   explicitly. Use image generation for required short labels, panel headers,
   and compact figure tags instead of defaulting to blank placeholders. Place
   long explanation in the caption or manuscript body. Avoid microtext,
   overlapping labels, colored text that is hard to read, and decorative
   typography.

7. **Information-first color**  
   Use colorblind-friendly palettes. Avoid red-green as the only contrast and
   avoid rainbow/jet maps unless there is a domain-specific reason.

8. **Design to target size**  
   Plan for the venue's single-column, double-column, or full-page constraints
   before generating the figure. Do not design a dense poster and shrink it into
   a journal column.

9. **Caption is part of the figure package**  
   Draft the caption with the visual. The caption should state what the figure
   shows, what evidence it uses, and any boundary needed to avoid overclaiming.

## Visual Brief Template

Before prompting an image model, write a brief in this structure:

```text
Purpose:
[One sentence stating the scientific claim the figure should communicate.]

Audience:
[Target readers, e.g., NLP researchers, medical AI reviewers, immunologists.]

Figure type:
[conceptual schematic / experimental workflow / model architecture /
 graphical abstract / annotated motivating example / validation map]

Evidence status:
[schematic only / layout sketch only / data-derived panels supplied separately /
 final image directly contains AI-generated content / manually redrawn final]

Canvas and layout:
[horizontal/vertical; single-column/double-column; panel count; reading order]

Panel plan:
(a) [panel a content]
(b) [panel b content]
(c) [panel c content]

Key elements:
- [element 1: visual form, position, meaning]
- [element 2: visual form, position, meaning]
- [element 3: visual form, position, meaning]

Relationships:
[arrows, feedback loops, inhibition, input/output paths, optional branches]

Visual style:
flat vector-style scientific illustration, white background, minimal,
editorial, high contrast, thin consistent line art, no glossy 3D,
no decorative gradients

Color coding:
[input = muted blue, model = muted orange, output = muted green, etc.]
Use a colorblind-friendly palette; do not rely on red-green contrast.

Text:
Use only these exact short labels: "[label 1]", "[label 2]", "[label 3]".
Render every listed label exactly as written. No extra words, fake labels,
misspellings, paraphrases, or illegible microtext. If a generated draft misses
or distorts required text, regenerate with fewer labels or larger label regions;
use blank label areas only after repeated text-quality failure or when the venue
requires deterministic vector redraw. Do not include an in-image figure title;
the title belongs in the caption. Use formal manuscript typography: Times-style
Latin text and Source Han Serif / Noto Serif CJK / SimSun-style Chinese text.

Constraints:
[Use the compact hard-constraint block from this protocol; do not turn the
prompt into a long avoid-list.]
```

## Prompting Rules

- Do not prompt only for "professional", "Nature-style", "beautiful", or
  "scientific". These adjectives cause decorative fillers and fake science.
- Start with a positive, content-rich description of the research story: the
  concrete paper objects, motivating scene, task boundary, method change,
  evidence gate, and what the reader should infer. Negative constraints should
  be short and secondary.
- Specify task, claim, audience, figure type, panel structure, element
  relationships, visual encoding, and forbidden elements.
- For text-bearing figures, provide exact labels in quotation marks and require
  no extra text. Prefer fewer labels, larger label regions, and high contrast.
  The default expectation is that image generation directly renders the exact
  short labels.
- Inspect every generated label. Reject drafts with omitted labels, extra
  labels, misspellings, paraphrases, wrong language, unreadable text, or
  footer-note/disclaimer text.
- For formal ACL/NLP paper figures, decide whether the figure is a motivating
  example, dataset construction flow, method architecture, appendix prompt
  figure, data chart, or table before prompting. Do not use the same generic
  image prompt for all artifact roles.
- Ask for blank label regions only when a model repeatedly distorts words or
  when the final venue workflow requires deterministic vector text.
- Generate 3-6 layout drafts before polishing. Compare whether a reader can
  identify the claim in 10 seconds.

Image-model prompt anchors to verify when needed:

- OpenAI image-generation prompting guide: https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide
- Google Imagen documentation: https://ai.google.dev/gemini-api/docs/imagen
- Midjourney text guidance: https://docs.midjourney.com/hc/en-us/articles/32502277092109-Text-Generation

## Compact Hard Constraints

Append a compact version of this block to scientific image-generation prompts.
Do not paste a long prohibition list when a short one preserves the manuscript
boundary. Keep the prompt led by positive scene description.

```text
Strict constraints:
No in-image title. No fake data panels, fake plots, invented numbers, random
labels, illegible microtext, watermarks, logos, bottom banners, footer notes,
disclaimer strips, or provenance captions. Render only the exact required labels.
Do not recreate, copy, trace, or closely imitate a published reference figure's
wording, icons, layout geometry, color arrangement, example content, or
distinctive visual composition.
```

For event extraction, ontology abstraction, LLM evaluation, and prompt-design
figures, also add:

```text
Keep gold labels, reference summaries, oracle fields, and evaluation-only
signals visually outside the model input and main route. Do not invent citations,
years, authors, dataset scores, axes, formulas, or metric values.
```

## Figure-Type Prompt Templates

### Conceptual Mechanism Schematic

Use for biomedical, material, chemical, environmental, or conceptual mechanism
papers. Replace bracketed fields with verified content.

```text
Create a clean publication-style scientific mechanism schematic.

Purpose:
Illustrate the proposed mechanism that [core mechanism in one sentence].

Layout:
Central mechanism diagram with three stages arranged left to right:
1. [trigger/input]
2. [intermediate process]
3. [outcome/effect]

Key biological/chemical/material elements:
- [element A]: shown as [visual form], located [position]
- [element B]: shown as [visual form], located [position]
- [element C]: shown as [visual form], located [position]

Relationships:
Use solid arrows for activation, blunt-end lines for inhibition, dashed arrows
for indirect regulation. Make the main causal path visually dominant.

Style:
flat vector scientific illustration, white background, minimal, clear hierarchy,
consistent line weight, no photorealistic rendering.

Color:
Use muted, colorblind-friendly colors. Do not use red-green as the only contrast.

Text:
Only use short labels: "[A]", "[B]", "[C]", "[Outcome]".
No random labels or extra text.

Constraints:
[negative constraints]
```

### Experimental Workflow

```text
Create a publication-ready experimental workflow diagram.

Purpose:
Show the complete experimental workflow from [sample/source] to
[final analysis/output].

Layout:
A left-to-right pipeline with 5 steps, evenly spaced, connected by simple
arrows. Each step should be represented as a clean icon-like module.

Steps:
1. "[Step 1 label]" - visual: [describe]
2. "[Step 2 label]" - visual: [describe]
3. "[Step 3 label]" - visual: [describe]
4. "[Step 4 label]" - visual: [describe]
5. "[Step 5 label]" - visual: [describe]

Design:
white background, flat vector style, minimal, high contrast, consistent icon
size, consistent arrow style.

Constraints:
No fake data, fake microscope images, fake graphs, complex decorative
background, or unreadable microtext.
```

### Machine Learning Model Architecture

```text
Create a clean model architecture schematic for a research paper.

Purpose:
Explain how the proposed method transforms [input] into [output] through
[main modules].

Layout:
Left-to-right architecture diagram with four stages:
Input -> Feature extraction -> Core model -> Output.
Use rectangular modules, arrows, and one highlighted innovation block.

Modules:
- Input: [input types]
- Feature extractor: [module names]
- Core model: [main architecture]
- Innovation block: [new contribution]
- Output: [prediction/reconstruction/control signal/etc.]

Visual encoding:
Standard modules in muted gray/blue.
The proposed contribution block in muted orange.
Auxiliary losses or regularizers as dashed arrows.
Main data flow as solid arrows.

Text:
Use only short exact labels: "[...]", "[...]".
No fake equations unless explicitly listed.
Leave blank space for final formula editing.

Style:
flat vector diagram, white background, professional scientific layout, no 3D,
no neon, no random code snippets, no fake plots.
```

### Graphical Abstract

```text
Create a graphical abstract-style scientific illustration.

Purpose:
Communicate the central story of the paper:
[problem -> method -> key result/impact]

Composition:
Three-part visual narrative:
Left: problem/context
Center: proposed method/mechanism
Right: outcome/application

Visual hierarchy:
The central method should be the largest and most visually prominent.
Use simple arrows to show progression.
Keep the background white and uncluttered.

Style:
minimal editorial scientific illustration, flat vector look, clean shapes,
restrained colors, high contrast, no photorealism.

Text:
Use only 3-5 short labels:
"[Problem]", "[Method]", "[Result]".
No extra text.

Constraints:
No fake data charts, invented numerical results, random molecular structures,
stock-photo look, watermarks, or logos.
```

## Practical Workflow

1. **Visual brief first**  
   Define message, audience, figure type, panel structure, key elements, visual
   encoding, and forbidden elements.

2. **Generate 3-6 layout drafts**  
   Do not aim for a final figure on the first pass. Compare readability,
   scientific claim clarity, and whether the draft avoids decorative fake science.

3. **Select one composition and text-check it**  
   If the generated figure is used directly, verify every visible label against
   the required text list before accepting it. Redraw or vectorize in
   Illustrator, Figma, Inkscape, BioRender, PowerPoint, Affinity Designer,
   SVG/TikZ, or another editable workflow only when text quality, venue
   requirements, or later editing demands deterministic control.

4. **Check target venue specifications**  
   Check single/double column size, panel labels, resolution, RGB/CMYK,
   accepted formats, file-size limits, figure captions, and supplementary figure
   rules.

5. **Apply the disclosure boundary**  
   If the final submitted figure directly contains AI-generated visual content,
   or if the venue requires disclosure of internal AI figure assistance, save
   tool name, model/version, date, prompt, output image, human review, and manual
   edit record in a non-manuscript audit artifact. If the image model was only
   used as a private layout sketch and the final figure is manually redrawn, do
   not add AI-use labels to the figure or caption by default.

## Final Figure Audit Checklist

| Check | Standard |
|---|---|
| Scientific accuracy | Every element is supported by manuscript text, methods, results, or cited literature. |
| Data integrity | No AI-generated experimental image, fake curve, fake axis, fake statistic, fake scale bar, or fake evidence panel. |
| Figure claim | The main message is identifiable within 10 seconds. |
| Hierarchy | Inputs, mechanism/method, outputs, and evaluation/diagnostic layers are visually clear. |
| Text | Required short labels are rendered exactly; no in-image title, random text, omitted labels, mistranslations, typos, footer notes, or disclaimer strips. |
| Color | Colorblind-friendly palette; not only color encodes meaning. |
| Layout | Fits target single/double-column size; panel labels and spacing are consistent. |
| Format | Exported at venue-required resolution and file type. |
| Copyright | Does not copy an existing paper figure or protected visual expression. |
| AI disclosure | Prepared only when the submitted figure contains AI-generated visual content or the venue requires process disclosure; internal sketches followed by manual redraws are not labeled by default. |

## One-Sentence Operating Strategy

The image model's job is not to "make a figure look like a paper figure"; its job
is to generate a redrawable, reviewable, publication-normalizable schematic draft
that is constrained by the paper's scientific claim.
