# Manuscript Artifact Boundary

Use this protocol whenever ARS drafts, edits, formats, exports, or visually
designs a manuscript-facing artifact: paper body, abstract, title, figure,
table, caption, graphical abstract, XML/LaTeX/DOCX/PDF output, supplementary
tables, or open evaluation package prose intended for readers.

## Core Rule

Separate collaboration from publication. User-facing explanations, planning
notes, audit diagnoses, status updates, and design rationale written to the
author are not manuscript content.

## Prohibited In Manuscript Artifacts

Do not include visible text that:

- addresses the author or user directly (`you`, `the user`, `as requested`,
  `I recommend`, `we discussed`, `用户要求`, `给你的解释`, `我认为`, `你需要`);
- explains why the assistant chose a design rather than stating the paper's
  scholarly claim;
- describes internal workflow state (`approved by user`, `next I will`, `this
  was changed because the user said`);
- explains the artifact's delivery role instead of the artifact's substantive
  content, including title/subtitle/body phrases such as `本报告用于...`,
  `本案例报告用于配合...`, `PPT 负责...`, `本报告负责...`, `报告不嵌入...`,
  `正文重点...`, `配合 15 页 PPT...`, or equivalent "this document is for..."
  wording;
- uses casual Chinese-English mixing in Chinese manuscript/report artifacts.
  Necessary official product names, standards, protocol acronyms, code identifiers,
  and technology names may remain, but they should be introduced or framed with
  Chinese terminology and used consistently. Delivery-package labels such as
  `PPT`, `slide`, or `deck` do not belong in the final manuscript/report unless
  the artifact itself is a slide inventory;
- copies audit or planning commentary into captions, figure labels, table notes,
  abstracts, section titles, or PDF/XML output.

## Allowed In Manuscript Artifacts

Use manuscript-safe scholarly labels when they describe the evidence itself:

- `sample-200 screening`
- `full-validation main result`
- `cross-model robustness check`
- `single-model full ablation`
- `oracle upper bound / diagnostic only`
- `semantic validation gate`
- `efficiency trade-off`
- `human review required for inaccessible full text`

## Evidence-Tier Rule

When writing empirical evolution narratives or generating figure groups, label
evidence tiers explicitly:

1. Main results require full-validation evidence on the declared primary setting.
2. Cross-model claims require corresponding cross-model validation.
3. Screening runs may guide method selection but must not be presented as final
   evidence.
4. Oracle/gold/reference-assisted branches must be separated from the main route.
5. Cost, concurrency, semantic-verifier, and human-handoff findings are diagnostic
   unless the paper's main contribution is explicitly about those mechanisms.

## Final Leak Check

Before emission, inspect every visible string in the artifact:

- Does this string support a research question, method, result, limitation, or
  venue requirement?
- Would this string still make sense to a reviewer who has never seen the chat?
- Is it free of assistant-user dialogue markers?

If any answer is no, remove the string or move it to a separate non-manuscript
audit note.
