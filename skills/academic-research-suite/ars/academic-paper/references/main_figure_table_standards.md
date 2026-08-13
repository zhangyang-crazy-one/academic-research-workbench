# Main Figure, Main Table, and Graphical Abstract Standards

**Used by**: `visualization_agent`, `structure_architect_agent`, `argument_builder_agent`, `formatter_agent`

This protocol defines how ARS should understand, critique, and generate the central visual artifacts of a manuscript: the main figure, main table, graphical abstract, visual abstract, overview figure, teaser figure, and method figure.

When an image model is used to ideate or generate any scientific figure, also
read `ai_scientific_image_generation.md`. That file is authoritative for
image-model eligibility, forbidden figure types, prompt brief structure, negative
constraints, disclosure boundaries, and venue disclosure checks.

## Core Principle

The main figure is not automatically the most detailed pipeline or the first dataset-specific workflow. It is the single visual artifact that best communicates the paper's central claim, contribution, or methodological logic. The main table is not a dump of all results; it is the smallest table that supports the manuscript's primary comparative claim.

The main figure, main table, captions, and table notes are manuscript artifacts,
not explanations to the user. They must contain only scholarly content that a
reader should see in the paper. Do not copy conversational planning text,
assistant-user explanations, implementation commentary, or phrases addressed to
"you"/"the user"/"我/你" into visible figure/table text.

For generated manuscript figures, the default visible canvas should not include
an in-image title. Figure titles, figure numbers, and explanatory framing belong
in captions or surrounding manuscript text. The image itself should carry the
paper content through objects, relationships, panel tags, short labels, and
evidence cues.

Figure typography must follow the manuscript's declared format profile or final
LaTeX/PDF font stack. Under the ARS default paper stack, use Times-style Latin
text and Source Han Serif / 思源宋体-style Chinese text; if the exact Source Han
font is unavailable to the renderer, use Noto Serif CJK or SimSun-style CJK
serif as the fallback. Avoid UI/dashboard sans-serif fonts for final paper
figures unless the venue template explicitly requires them.

Use this protocol whenever the user asks for any of:

- main figure / main table
- graphical abstract / visual abstract
- overview figure / teaser figure
- method figure / framework figure
- 主图 / 主表 / 图文摘要 / 图形摘要 / 方法总览图 / 研究框架图

## Evidence-Informed Rationale

Publisher and venue guidance converges on the same norm: a graphical abstract or main overview visual should be concise, self-explanatory, and focused on the central message or contribution rather than exhaustive detail. For CS and NLP-style method papers, the first major figure often functions as an overview of the method, framework, or argument structure. For empirical papers, the main table often condenses the decisive result set rather than every diagnostic.

Operational implication: first identify the manuscript's thesis, then design the figure/table. Do not start from available data files or dataset names.

### Lessons From Research-Figure Generation Tooling

Recent open-source research-figure tools converge on a workflow lesson: strong
paper figures are planned, critiqued, and refined; they are not usually obtained
by asking for a generic pipeline diagram in one pass.

Use these tooling patterns as design guidance, not as manuscript citations:

| Tooling pattern | Reusable lesson for ARS |
|---|---|
| PaperBanana-style input optimization and multi-stage planning | Generate a figure-narrative brief before image generation; include paper context, central claim, forbidden implications, and target visual grammar. |
| AutoFigure-style review-refine loops | Add a critic gate after each draft; score thesis alignment, label correctness, visual originality, evidence linkage, and leakage risk before accepting the figure. |
| Paper2Any-style editable artifact conversion | Treat image-generation output as a visual mother draft; convert accepted designs into editable SVG, draw.io, PPT, TikZ, or PDF only after the composition is worth preserving. |
| Image-to-skill / research-figure galleries | Prefer central visual metaphors, motivating examples, failure modes, and sparse hierarchy over generic boxes and arrows. |
| Scientific-figure benchmark collections | Keep a trace from source claims and evidence to visual elements so the figure can be checked, regenerated, or rejected systematically. |

Do not put tooling names, project names, URLs, or implementation provenance into
manuscript figures, captions, table notes, or graphical abstracts unless the
paper explicitly studies those tools.

## LLM Event Extraction and Reasoning Papers, 2025-2026

Recent event extraction, information extraction, and LLM reasoning papers increasingly use the first major visual to do four jobs at once:

1. **Expose the failure of the naive baseline**: show why direct prompting, direct extraction, greedy generation, or a prior task formulation fails.
2. **Define the proposed task/protocol boundary**: make explicit which signals are inputs, which are predictions, and which gold/reference fields are used only for evaluation or diagnostics.
3. **Show the main route plus diagnostic branches**: separate the protocol that supports the main claim from oracle, ablation, repair, verifier, selector, or cost-analysis branches.
4. **Anchor the figure to the decisive evidence**: include a compact result callout, metric family, or reference to the main table so the visual does not become a decorative pipeline.

Use this section especially for papers about zero-shot event detection, event argument extraction, document-level information extraction, abductive event reasoning, temporal reasoning, LLM self-correction, prompt optimization, or verifier/selector frameworks.

Observed reusable patterns from 2025-2026 papers:

| Paper pattern | Main figure form | When to use |
|---|---|---|
| Divergent-convergent event detection | Naive direct prompting failure -> Dreamer/Grounder/Judge or equivalent stages -> constrained output | Zero-shot ED or task decomposition papers |
| Event argument preference traps | Failure modes/traps -> two-stage extraction or choose/rank framework -> ablation evidence | EAE papers where hallucination, contradiction, or role confusion is central |
| Sampling and selection for DocIE | Multiple candidate generations -> selector/verifier -> selected structure -> oracle/upper-bound comparison | Papers with multi-sample, reward model, self-consistency, or verifier logic |
| Abductive event reasoning benchmark | Evidence collection -> event extraction/timeline -> candidate causes -> human/model validation | Event reasoning or evidence-grounded benchmark papers |
| Prompt optimization for LRM/LLM extraction | Task LLM -> optimizer/reasoning model -> prompt update loop -> score improvement | Prompt optimization or task-model/optimizer-model separation |

For this family of papers, a single task example is usually not enough for Figure 1. A task example can be Panel A, but the complete main figure should also show the protocol boundary, main route, diagnostic branch, and evidence link.

For feasibility or possibility studies, especially papers asking whether a new language/domain ontology abstraction task is possible under strict evidence boundaries, do not frame the main figure as case-driven. The example is illustrative evidence only. The main figure should foreground the research question, abstraction target, validation protocol, and evidence gates, with a small example inset used to make the abstract protocol concrete.

Use "case-driven" only when the paper's claim is about deriving the method from one representative case, case study reasoning, or a qualitative case analysis. Otherwise use "protocol-driven with illustrative case" or "research-question-driven framework".

### ACL/NLP Reference-Paper Figure and Table Archetypes

When the user provides a recent ACL/EMNLP/NAACL-style reference PDF, do not
infer its visual standard from captions alone. Render or crop every figure and
table, inspect them one by one, and classify each artifact before proposing a
replacement for the user's manuscript.

Reference-paper use is **pattern extraction, not imitation**. Extract the
artifact role, evidence structure, density, caption convention, and table logic.
Do not copy or closely recreate the reference paper's figure/table wording,
iconography, color arrangement, geometry, panel layout, example content, or
distinctive visual composition. The new figure/table must be built from the
user's own data, task boundary, examples, labels, and argument.

Common ACL/NLP artifact roles:

| Artifact role | What the formal paper usually shows | Correct production path |
|---|---|---|
| Motivating case figure | Realistic input, question/task, evidence/context, output, and highlighted spans or decisions | Text-bearing figure with exact labels and example snippets; image-gen only if exact text passes QC, otherwise deterministic vector/PDF text |
| Dataset construction figure | Source materials, LLM generation steps, expert review, intermediate artifacts, final dataset/product | Full-width workflow with named nodes, arrows, review gates, and final artifact; every node label must be meaningful |
| Method architecture with evidence | Input, retrieved evidence, initial answer/failure, verifier/refinement, final answer | Case-grounded architecture figure; show the failure/correction mechanism, not only boxes and arrows |
| Main results table | Setting groups, model names with citations, task/metric columns, compact numeric matrix, caption metric definitions | LaTeX/booktabs-style table; Markdown is draft-only |
| Appendix prompt/rubric figure | Verbatim prompt, input schema, output schema, rubric, or evaluation example | Deterministic text boxes or screenshot-like PDF-native figure; exact text readability is more important than aesthetics |
| Data analysis chart | Distribution of categories, task formats, difficulty levels, or other dataset statistics | Data-derived Python/R chart only; never image-generate numeric charts |
| Taxonomy or dataset-statistics table | Category hierarchy, event types, definitions, counts, task totals | Longtable/booktabs-style appendix table with grouped rows and clear caption |

Failure condition: if a proposed figure is a generic icon flow, blank-label
schematic, or decorative concept map when the reference paper uses text-bearing
case evidence, prompt/rubric boxes, or compact numeric tables, the design fails
ACL/NLP visual fidelity.

### Non-Boxed Main-Figure Grammars

Box-and-arrow diagrams are allowed only when the central contribution is a
system architecture, data pipeline, or implementation workflow. For papers whose
contribution is a task framing, feasibility claim, evidence protocol, prompt
design, ontology abstraction, or LLM evaluation boundary, start from one of
these non-boxed grammars before considering a pipeline diagram:

If the user explicitly selects a strict academic SVG box diagram after this
visual-form decision, read and apply `academic_svg_box_diagram_standards.md` for
that artifact. Its arrow, label, rail, typography, and SVG-audit requirements do
not become defaults for charts or other figure families.

| Visual grammar | What it shows | Use when |
|---|---|---|
| Annotated motivating example | A realistic input excerpt with highlighted spans, model-visible fields, predicted outputs, and evaluation-only fields | The reader must understand the task boundary and why the problem is hard |
| Evidence dossier | A central claim surrounded by source evidence, validation gates, diagnostic seals, and result snippets | The paper argues from accumulated evidence rather than a new algorithm alone |
| Abstraction lens | Concrete case on one side, abstract schema or ontology layer on the other, with the lens showing what is retained or discarded | The paper studies ontology abstraction, schema induction, or representation design |
| Failure-to-protocol contrast | Naive/direct prompting failure on the left; constrained protocol and corrected outputs on the right | The paper's contribution is a safer task formulation or protocol boundary |
| Validation map | Research question at the top, main route in the center, full-validation evidence and diagnostics as separated layers | The paper needs to prevent overclaiming across screening, full, and oracle settings |
| Prompt design card | A small set of prompt principles, a representative prompt excerpt, and the resulting behavior change | The method is prompt/task-design driven rather than architecture driven |

For image generation, run a style probe with at least three distinct grammars
when the first draft looks like a generic software architecture figure. Reject a
draft if its visual impression is dominated by evenly spaced rectangles, UI-like
cards, or pipeline arrows that do not express the paper's core intellectual move.

### Evidence-Tiered Figure Groups for Experiment Evolution

When a paper's argument depends on method evolution, literature anchoring, and
final validation, prefer a figure group over a single overloaded figure. The group
should separate:

1. **Research problem and task boundary**: what is being abstracted, what inputs are
   allowed, and which labels/references are disallowed.
2. **Literature-to-protocol rationale**: how prior work motivates the task
   representation, without claiming experimental support from citations alone.
3. **Method evolution evidence**: pilot, sample-200, or screening runs, explicitly
   labeled by data scale and model.
4. **Full-validation main results**: the final protocol versus key baselines on the
   declared full setting, with cross-model rows only when actually run.
5. **Diagnostic and boundary evidence**: oracle upper bounds, repair/span-guard
   branches, semantic validation, cost/concurrency, and human-handoff cases.

Do not draw all evolution steps as equally proven. A visual path may show
screening -> selection -> full validation, but it must label which steps are
screening evidence and which are full-validation evidence. If only the final
method has dual-model full validation, the figure must not imply that every
intermediate ablation has the same validation level.

For LLM extraction or event studies, use these manuscript-safe evidence labels:

- `sample-200 screening`
- `full-validation main result`
- `single-model full ablation`
- `cross-model robustness check`
- `oracle upper bound / diagnostic only`
- `semantic validation gate`
- `efficiency trade-off`

Avoid conversational labels such as `what we found for you`, `my recommendation`,
`user-approved route`, or `why this figure was changed`.

### Required Boundary Labels for Zero-Shot / Oracle-Sensitive Figures

When the paper uses terms such as zero-shot, given-trigger, oracle, serial, reference-free, verifier, selector, or semantic validation, the main figure and main table note must label the boundary explicitly.

Required labels when applicable:

- `given-trigger`
- `predicted event type`
- `gold event type: diagnostic/oracle only`
- `no gold argument span input`
- `reference summary used only for evaluation`
- `serial main route`
- `oracle/repair/verifier branch not used for main claim`
- `human review required for paid or inaccessible full text`

Failure condition: if a reader could mistake an oracle branch for the main zero-shot route, the figure fails scope control.

## Intake Checklist

Before proposing a main figure or main table, extract:

1. **Central research question** — What question does the paper answer?
2. **Primary contribution type** — method, framework, dataset, benchmark, theory, empirical finding, system, or mixed.
3. **Take-home claim** — What should a reviewer remember after 10 seconds?
4. **Evidence backbone** — Which result(s), ablation(s), or validation settings support that claim?
5. **Scope boundary** — What the figure/table must not imply.
6. **Venue expectations** — conference, journal, graphical abstract requirement, page/column constraints.
7. **Audience** — domain experts, general ML/NLP readers, interdisciplinary reviewers, practitioners.

If any of items 1-4 is unclear, ask for clarification or infer conservatively from the abstract, introduction, and result summary.

## Decision Tree

### Step 1: Determine the artifact's job

| Artifact job | Use when | Output form |
|---|---|---|
| Methodology / framework | The contribution is a new method, task framing, validation framework, or conceptual integration | Main methodology figure |
| Evidence condensation | The contribution is a result pattern across tasks/models/settings | Main table or compact result matrix |
| Mechanism explanation | The contribution is why a method works or where gains come from | Annotated mechanism figure |
| Dataset / benchmark definition | The contribution is a dataset, benchmark, or evaluation suite | Dataset/benchmark schema figure |
| System architecture | The contribution is an implemented system or toolchain | System overview figure |
| General-reader summary | Venue requires a graphical abstract | Graphical/visual abstract |

### Step 2: Reject misleading defaults

Avoid these common failures:

- **Dataset tunnel vision**: depicting one dataset input when the paper's contribution is a general method or validation framework.
- **Pipeline literalism**: drawing implementation order when the paper's claim is methodological.
- **Box-diagram lock-in**: forcing every main figure into rectangles and arrows even when the paper needs a motivating example, abstraction metaphor, failure contrast, or evidence map.
- **Result dumping**: filling the main table with every ablation, diagnostic, or secondary metric.
- **Decorative overview**: adding icons and arrows that do not correspond to manuscript claims.
- **Untraceable caption**: caption claims that are not backed by results, ablations, or cited literature.

### Step 3: Choose abstraction level

| Paper claim | Correct abstraction | Incorrect abstraction |
|---|---|---|
| "Task representation drives zero-shot gains" | Problem framing -> constraints -> task rewriting principles -> validation settings -> primary outcomes | One dataset input -> sequential processing -> output file |
| "A new model architecture improves accuracy" | Model components, information flow, training/inference distinction, key result callout | Full code-level architecture dump |
| "A benchmark exposes failure modes" | Evaluation dimensions, task families, representative failure modes, headline coverage | File directory tree only |
| "A clinical intervention improves outcomes" | Intervention logic, population, comparator, primary outcome | Hospital workflow diagram with no effect estimate |
| "A theory explains a phenomenon" | Constructs, causal/interpretive relationships, empirical anchors | Literature map without thesis |
| "A given-trigger zero-shot event extraction protocol is valid without label leakage" | Baseline risk -> protocol boundary -> serial main route -> oracle/diagnostic branch separated -> validation evidence | A single pretty extraction example that hides which gold/reference inputs are used |
| "Semantic validation is necessary for LLM extraction claims" | Prediction -> claim/reference evidence -> semantic verifier or human handoff -> pass/fail outcomes -> audited artifact | A result table without showing where semantic validation enters the workflow |

## Main Figure Standard Workflow

1. **Extract the thesis sentence**  
   Write one sentence: "This paper shows that ..."

2. **Classify the contribution**  
   Choose one primary contribution type and one secondary type if needed.

3. **Select the visual grammar**  
   Use one of:
   - framework map
   - method overview
   - mechanism diagram
   - evidence flow
   - task-family matrix
   - dataset/benchmark schema
   - graphical abstract
   - annotated motivating example
   - evidence dossier
   - abstraction lens
   - failure-to-protocol contrast
   - validation map
   - prompt design card

4. **Define panels**  
   Prefer 2-4 panels. Each panel must answer a different reader question:
   - What problem is addressed?
   - What is the proposed framing/method?
   - What evidence validates it?
   - What should the reader conclude?

   For LLM event extraction/reasoning papers, prefer this 4-panel grammar:
   - Panel A: Naive baseline or task example, showing the failure/risk.
   - Panel B: Proposed protocol boundary, showing allowed and disallowed inputs.
   - Panel C: Main route, showing only the path used for the paper's main claim.
   - Panel D: Diagnostic/evidence layer, showing oracle/ablation/verifier branches and the main-table link.

5. **Write figure caption first**  
   If the caption cannot state the central claim clearly, the figure is not ready.

6. **Map every visual element to a claim**  
   Each box, arrow, label, or highlight must correspond to a manuscript claim, method component, constraint, or result.

7. **Run the main-figure audit**  
   Use the checklist below before generating or editing the image.

### Image-Generation Figure Workflow

Use this workflow when generating a main figure, teaser figure, graphical
abstract, or overview figure with an image model.

1. **Figure-narrative brief**
   - Thesis sentence and research question.
   - Take-home claim after 10 seconds.
   - Positive visual story: the concrete research scene, task objects,
     protocol transformation, evidence gates, and reader inference. Avoid
     prompts dominated by prohibition lists.
   - Allowed inputs, disallowed inputs, and diagnostic-only branches.
   - Evidence tier labels and result anchors.
   - Required exact visible labels. Current image-generation models should be
     prompted to render short manuscript labels directly; do not default to
     blank placeholder labels.
   - Manuscript typography: Times-style Latin labels and Source Han Serif /
     Noto Serif CJK / SimSun-style Chinese labels, matching the paper font
     stack.
   - Hard exclusions kept compact: no in-image title, conversation markers,
     provenance text, footer notes, disclaimer strips, or fake data elements.

2. **Style probes**
   - Produce or request at least three visually distinct candidates if the visual
     grammar is uncertain.
   - Include at least one non-boxed grammar when the paper is not a system or
     implementation paper.
   - Vary composition, not just palette: for example, compare annotated example,
     abstraction lens, and validation map.

3. **Critic gate**
   - Reject drafts that look primarily like generic cards, software workflow
     diagrams, dashboards, or implementation pipelines when the thesis is not
     about software architecture.
   - Reject drafts that place gold labels, references, or oracle information on
     the main route when they are evaluation-only or diagnostic-only.
   - Reject drafts that omit required labels, replace required labels with blank
     placeholders, mistranslate labels, add unrequested labels, or distort text.
   - Reject drafts with fake citations, unverified author-year text, tool
     provenance, assistant-user dialogue, or design explanations.

4. **Finalization path**
   - If the image generation is only a sketch, label it as a visual mother draft.
   - If text must be exact, first prompt image generation with the exact short
     labels and inspect the output. Recreate the accepted composition in SVG,
     TikZ, draw.io, Illustrator, PowerPoint, or another editable vector source
     only after repeated text-generation failure or when the venue requires
     deterministic vector text.
   - If the generated image is used directly, inspect all visible text, export at
     the venue-required resolution, and keep a separate non-manuscript trace of
     source prompt, evidence, and revision decisions.

## Main Table Standard Workflow

1. **Identify the decisive comparison**  
   What comparison would convince a reviewer that the paper's main claim is supported?

2. **Limit rows and columns**  
   Prefer 4-8 rows and 4-6 columns. Put diagnostics, full ablations, and secondary metrics in later tables or appendices.

3. **Separate evaluation settings**  
   If rows use different settings (e.g., oracle vs serial, in-domain vs cross-domain), label them explicitly and include a table note.

4. **Use meaningful row labels**  
   Rows should reflect task, method family, dataset/condition, or evaluation setting. Avoid opaque run IDs unless the paper is about the run IDs.

5. **Align the table with the main figure**  
   The main table should provide the numeric evidence for the claim made visually in the main figure.

6. **Use ACL-style table structure for NLP papers**  
   For ACL/NLP manuscripts, final tables should normally be LaTeX/booktabs-style
   artifacts, not decorative Markdown tables. Use grouped rows for settings or
   methods, model names with citations where appropriate, compact metric
   columns, units in headers or captions, and a caption note that defines every
   metric family. Use vertical rules sparingly and only when the target template
   or local precedent supports them.

7. **Separate main and appendix tables**  
   Main tables should be compact result matrices. Long taxonomy definitions,
   prompt schemas, dataset inventory, per-class counts, and verbose error
   examples belong in appendix tables or appendix figures unless they are the
   paper's central contribution.

8. **Preserve numeric auditability**  
   Every table cell must trace to a data file, metric script, or cited source.
   For mixed metric tables, define the metric scale in the caption: e.g.,
   accuracy for TF/MCQ, average score for MAQ, agreement rate for SAG, pass rate
   for RG. Do not mix metrics without a caption-level scale note.

### External-Anchor Main Tables

When no directly comparable prior work exists for the paper's exact language, domain, ontology abstraction target, or evaluation protocol, the main table may include an external-anchor panel. This is common for emerging tasks where the paper adapts a nearby literature family rather than competing on an established benchmark.

Rules:

- Keep the paper's own main results in the decisive panel.
- Label external-anchor rows as `Reference`, `External anchor`, or `Related task`, not as baseline or SOTA.
- Add a note that the anchor rows are not directly comparable because dataset, language, schema, input boundary, and evaluation protocol differ.
- Prefer anchors that justify the paper's framing, such as ontology learning, event schema induction, event extraction benchmarks, or LLM reasoning protocols.
- If adjacent Chinese event extraction or ontology-construction work exists but lacks the same ontology-abstraction protocol, cite it in related work and optionally add a qualitative reference row instead of forcing a numeric comparison.

Failure condition: if the table visually implies that external-anchor scores and the paper's scores are on the same benchmark, split the anchor into a separate table or add stronger panel separation.

## Graphical Abstract Standard Workflow

Use when the venue asks for a graphical abstract or visual abstract. It should be self-explanatory to a non-specialist reader.

Structure:

1. Problem or gap
2. Method/intervention
3. Primary result or finding
4. Implication

Rules:

- Use fewer words than a method overview figure.
- Do not include all metrics, ablations, or implementation details.
- Avoid venue-irrelevant decorative imagery.
- Avoid visual claims unsupported by the manuscript.

## Main-Figure Audit Checklist

A proposed main figure passes only if all mandatory checks pass.

| Check | Pass criterion | Failure action |
|---|---|---|
| Thesis alignment | The figure's top-level structure matches the paper's thesis | Redesign from thesis, not from data flow |
| Contribution clarity | A reader can identify the contribution in 10 seconds | Add hierarchy, remove secondary details |
| Abstraction level | The figure shows method/framework logic when the claim is methodological | Replace dataset-specific pipeline with method abstraction |
| Evidence linkage | Result callouts or validation settings map to reported evidence | Add main table linkage or remove unsupported claim |
| Scope control | The figure does not imply broader generality than the paper tests | Add boundary labels or notes |
| Text economy | Required short labels are present, exact, and readable at publication size; no in-image title | Shorten labels, enlarge label regions, or regenerate |
| Visual traceability | Every arrow/box has a semantic reason | Remove decorative or redundant elements |
| Accessibility | Color is not the only encoding; contrast and font size are adequate | Revise palette and labels |
| Typography | Figure labels use the declared paper font stack or formal serif fallback, not UI/dashboard fonts | Redraw text layer or regenerate with formal manuscript typography |
| Oracle separation | Oracle/gold/reference-assisted branches are visually separated from the main claim route | Move oracle branches to a dashed diagnostic band and label them upper-bound/diagnostic only |
| Evidence anchoring | The visual points to the decisive main table, metric, or validation result | Add a compact result callout or table-reference tag |
| Evidence tier labeling | Screening, full-validation, cross-model, and diagnostic evidence are visually distinguishable | Add tier labels or split into a figure group |
| Manuscript-artifact boundary | Visible figure/table text contains no assistant-user dialogue, planning commentary, or "I/you/user" explanation | Remove conversational text; move it to a separate audit note |
| In-image title ban | Generated manuscript figures contain no internal title; figure title belongs in the caption or manuscript text | Regenerate, crop/redraw, or remove the title in deterministic editing |
| Footer-note ban | Generated manuscript figures contain no bottom banners, footer notes, footnote strips, provenance captions, or disclaimer text such as "文献启发，不作实验结论" | Regenerate or crop/redraw the figure; put any disclosure or evidence-boundary note in the caption, table note, or audit artifact |

## Output Template

Use this template when responding to a main figure/main table request.

```markdown
## Main Visual Diagnosis

- Central thesis:
- Contribution type:
- Current visual risk:
- Recommended main figure job:
- Recommended main table job:

## Proposed Figure 1

- Title:
- One-sentence caption:
- Visual grammar:
- Panels:
- Required labels:
- What to omit:
- Evidence linkage:

## Proposed Table 1

- Title:
- Rows:
- Columns:
- Required note:
- What to move to supplementary tables:

## Audit

| Check | Status | Note |
|---|---|---|
| Thesis alignment | PASS/REVISE | ... |
| Contribution clarity | PASS/REVISE | ... |
| Abstraction level | PASS/REVISE | ... |
| Evidence linkage | PASS/REVISE | ... |
| Scope control | PASS/REVISE | ... |
```

## Image Generation Guidance

When using an image generator for ideation:

1. Apply `ai_scientific_image_generation.md` before prompting. Do not use image
   models for data charts, microscopy, western blots, tissue sections, clinical
   images, fake axes, fake statistics, or any evidence-bearing primary research
   panel.
2. Treat the generated image as a visual sketch, not the canonical manuscript artifact.
3. Inspect generated text and labels before accepting the output; exact labels,
   formulas, axes, legends, and metric values should be human-edited or rendered
   in deterministic vector/text tools.
4. Prefer direct image editing for small text/layout corrections when the generated composition is otherwise correct.
5. For the final manuscript, prefer deterministic source formats (TikZ, SVG, draw.io, Illustrator, PowerPoint exported to PDF/SVG, or Python-generated vector output) when exact text and journal compliance matter.
6. Keep a trace from the visual sketch to the manuscript claim and final source file
   only when the final submitted figure directly contains AI-generated visual
   content, the venue requires process disclosure, or the audit package itself
   needs the record. Do not add AI-use labels to figures or captions merely
   because an image model was used as a private composition sketch and the final
   figure was manually redrawn.
7. Reject or revise any generated image that contains user-facing explanation,
   planning notes, "I/you" wording, text meant to justify the design to the
   author, fake scientific decoration, fake data, unrequested labels, logos,
   watermarks, or unsupported mechanism elements.
