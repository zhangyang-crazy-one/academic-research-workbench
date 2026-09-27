# Downstream ARS Codex adapter reference

Original material: academic-research-skills by Imbad0202, CC BY-NC 4.0.
Modified by Academic Research Workbench: moved intact from the adapter router
for progressive loading; see repository MODIFICATIONS.md for provenance.

+## Manuscript Artifact Boundary

Separate user-facing collaboration from manuscript-facing artifacts. Notes written
to explain choices to the user, audit diagnoses, planning commentary, status updates,
or phrases addressed to "you"/"the user"/"我/你" are not manuscript content.

When drafting papers, generating figures/tables, writing captions, exporting PDF/XML,
or preparing camera-ready assets:

- Do not copy conversation explanations, coaching text, implementation notes, or
  "why I designed it this way" commentary into the manuscript, figure labels, table
  notes, captions, abstracts, titles, or supplementary artifacts.
- Do not include phrases such as "as you requested", "I recommend", "we discussed",
  "给你的解释", "我认为", "你需要", "用户要求", or equivalent assistant-user
  dialogue markers in final paper artifacts.
- Do not include meta-delivery explanations in titles, subtitles, abstracts, body
  text, captions, or PDF cover pages. Prohibited examples include "本报告用于...",
  "本案例报告用于配合...", "PPT 负责...", "本报告负责...", "报告不嵌入...",
  "正文重点...", "配合 15 页 PPT...", "behind each slide", and equivalent
  wording that explains the artifact's role in a conversation or delivery package
  instead of stating project facts, methods, evidence, decisions, or execution
  status.
- For Chinese manuscript/report artifacts, enforce terminology normalization.
  Avoid casual Chinese-English mixing in body text, headings, captions, tables, and
  cover pages. Keep only necessary official product names, standards, protocol
  acronyms, code identifiers, and technology names; when a non-Chinese term is
  necessary, introduce it with a Chinese explanation once and keep subsequent usage
  consistent. Do not use English delivery labels such as "PPT", "slide", "deck",
  or similar packaging terms in the manuscript unless the artifact itself is a
  slide inventory rather than the final report.
- Keep internal audit labels only when they are legitimate scholarly labels, for
  example `diagnostic`, `oracle upper bound`, `sample-200 screening`, or
  `full-validation`; strip conversational rationale around them.
- Before final emission, run a manuscript-artifact leak check: every visible string
  must serve the paper's research claim, method, evidence, limitation, or venue
  requirement. If a string only explains the work to the user, remove it or place it
  in a separate non-manuscript audit note.

## Evidence-Tiered Experiment Narratives

For empirical paper writing, figure planning, main-table planning, and result
summaries, separate evidence tiers before making claims:

- **Main results** require full-validation evidence on the declared primary setting.
  If a cross-model or cross-dataset generalization claim is made, the same level of
  validation is required for that claim.
- **Screening or evolution results** may use smoke, small, or sample-200 runs, but
  figures/tables must label them as screening, method selection, or pilot evidence.
- **Diagnostic results** such as oracle labels, gold/reference-assisted settings,
  span guards, repair branches, semantic verifiers, cost probes, and concurrency
  probes must be visually and textually separated from the main claim route.
- **Figure groups** are preferred when the argument depends on research-question
  framing, literature anchors, method evolution, final full-validation evidence, and
  diagnostics. Do not force these into one overloaded figure.
- Never state that an entire evolution chain is fully validated across models unless
  every component in that chain has the corresponding full-validation evidence.

## Non-Boxed Academic Main Figures

When generating a main figure, overview figure, graphical abstract, or teaser
figure for a paper, do not default to a rigid box-and-arrow architecture diagram.
First test whether a richer paper visual grammar better communicates the research
question, motivating example, protocol boundary, and evidence. Use
`ars/academic-paper/references/main_figure_table_standards.md` for the
figure-narrative brief, style probes, critic gate, and finalization rules.

For manuscript-facing image-generation prompts, lead with a vivid positive
description of the paper content: the concrete research scene, what the reader
should notice, how the method changes the task, and where evidence enters. Do
not make the prompt primarily a long list of prohibitions. Keep negative
requirements compact and reserved for hard manuscript constraints. Generated
paper figures should not contain an in-image title; figure names and explanatory
titles belong in the caption or manuscript text, while visible text inside the
image should be limited to panel tags, object labels, task labels, and short
evidence labels.

When the user provides a formal reference PDF for visual, figure, or table
style, first extract and inspect every figure and table one by one. Classify
each artifact by scholarly role (motivating case, dataset construction,
method architecture, main result table, appendix prompt/rubric figure, data
analysis chart, taxonomy table, dataset-statistics table) before designing new
figures or tables. Do not infer the style from captions alone.

Reference papers are exemplars for scholarly role, evidence density, table
logic, caption discipline, and venue-appropriate artifact types only. Do not
copy, trace, crop into the manuscript, visually recreate, or closely imitate a
reference paper's protected figure/table expression, wording, layout geometry,
icons, color arrangement, or distinctive composition. Abstract the reusable
principle, then design a new artifact from the user's own research question,
data, evidence, labels, and manuscript argument.

Framework boxes and pipeline arrows are acceptable only when the paper's central
contribution is literally a system architecture or execution pipeline. For LLM
event extraction, ontology abstraction, prompt optimization, or feasibility
studies, prefer manuscript-safe visual narratives such as annotated examples,
evidence dossiers, abstraction lenses, failure-to-protocol contrasts, or
validation maps.

