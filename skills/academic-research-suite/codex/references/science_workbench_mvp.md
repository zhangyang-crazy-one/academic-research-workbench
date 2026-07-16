# Science Workbench MVP Contract

This Codex-only reference captures the Science Workbench MVP requirements derived from:

`ARS_SCIENCE_WORKBENCH_MVP_REQUIREMENTS.md` (maintainer-supplied local reference)

Use it when a task asks for auditable scientific report generation, strict academic PDF/export, Markdown-to-paper conversion, source integration, run ledgers, citation verification, semantic verification, or paid/full-text evidence handoff.

## Scope

The MVP is an auditable research production workflow, not a general chat workflow.

It must:

- Accept a readable Markdown research report as the author-facing source.
- Preserve source Markdown unless the user explicitly asks for rewriting.
- Produce structured intermediate artifacts suitable for strict validation, including a paper AST or XML-style representation.
- Generate publication-style outputs from structured artifacts, not from ad hoc Markdown rendering.
- Keep all generated audit artifacts in a task-scoped run directory.
- Default to citation and semantic verification for paper-like outputs.
- Treat paid or inaccessible full text as a human decision gate.

It must not:

- Claim inaccessible full-text evidence was verified.
- Silently use private credentials, paid databases, or local unpublished data.
- Mix unrelated task artifacts in a shared flat directory.
- Modify vendored upstream ARS files under `ars/` while implementing Codex adapter behavior.

## Run Directory Contract

Every auditable run writes under:

```text
experiments/runs/<task_slug>__<YYYYMMDD-HHMMSS>__<hash8>/
```

Rules:

- `task_slug` comes first for scanability.
- Use stable lowercase ASCII slugs when possible.
- `hash8` should be derived from source path, source content hash, profile, and timestamp seed.
- Do not overwrite prior runs.
- Keep all evidence, validation, export, and handoff files inside the run directory.

Recommended structure:

```text
run/
  input/
  normalized/
  paper/
  exports/
  audit/
    citations/
    semantic_claims/
    format/
    sources/
    human_review/
  logs/
  state.json
  run_manifest.json
```

## Document Profiles

Use an explicit profile for every conversion or validation run.

| Profile | Default TOC | Expected Output | Notes |
| --- | ---: | --- | --- |
| `technical_report` | 2 | PDF plus structured paper artifact | Default for long technical reports. |
| `long_paper` | 0 | Conference/journal-like PDF | No TOC unless venue requires it. |
| `short_paper` | 0 | Compact conference-like PDF | Parameterize page limits and omit TOC by default. |
| `preprint` | 0 | Preprint PDF | Allow fuller methods and appendices. |

TOC depth must be explicit. The user decision for technical reports is TOC depth 2.

## Structured Paper Artifact

Markdown is the readable authoring format. The strict output path should normalize Markdown into a structured artifact before export.

Minimum AST fields:

```json
{
  "schema_version": "science_workbench.paper_ast.v1",
  "profile": "technical_report",
  "title": "...",
  "authors": [],
  "abstract": "...",
  "sections": [],
  "figures": [],
  "tables": [],
  "equations": [],
  "citations": [],
  "references": [],
  "appendices": []
}
```

Required invariants:

- Sections carry stable academic numbering unless a target venue disables numbering.
- Figures, tables, and equations carry stable labels and captions.
- Cross-references resolve against AST identifiers before PDF export.
- Citations resolve against normalized bibliography records.
- PDF rendering must not be the only validation layer.

XML or JATS-like export can be added after the AST is stable. Treat XML as a strict interchange/export target, not the only internal representation.

## Format Rules

Use formal academic defaults unless a venue template overrides them.

- Body text should use a standard scholarly serif font for English reports, with CJK font fallback when Chinese text appears.
- Math should use LaTeX-compatible math fonts and must visually match the body scale.
- Inline citations, footnotes, references, captions, and table text must use profile-controlled sizes; citation text must not become unexpectedly smaller than surrounding body text.
- Tables should use academic table conventions: readable column widths, consistent caption placement, repeated headers for long tables where supported, and no decorative UI styling.
- Equations should be numbered when referenced or when the profile requires numbering.
- Headings must be numbered according to the profile and cannot rely on visual size alone.

Before final delivery, audit rendered pages for inconsistent font size, broken line wraps, overflowing tables, missing equation glyphs, and unresolved references.

## Evidence And Verification Defaults

For paper-like outputs, default verification is required, not optional.

Verification layers:

- Citation existence: check DOI, title, venue, year, author list, and publication status where possible.
- Citation relevance: verify that each citation supports the nearby claim.
- Semantic claim verification: extract claims and compare them against cited evidence or declared experiment outputs.
- Bibliography consistency: normalize duplicate records and flag mismatched metadata.
- Source access state: record whether evidence came from abstract, metadata, open full text, local PDF, or paid/inaccessible full text.

Access failures must remain visible. If Cloudflare or another WAF, CAPTCHA,
HTTP 401/403/429, paywall, or institutional login blocks retrieval, report the
specific failure to the user and log it; do not silently substitute an abstract.
Abstract-only evidence may support only statements directly present in the
abstract. Detailed claims about methods, datasets, settings, results, or
limitations require full text with a page/section/table/figure locator. Prefer a
user-supplied local PDF when one is available. If full text cannot be obtained
legitimately, narrow or omit the claim, or mark it unresolved/retrieval-failed.

If a source requires payment, institutional login, unavailable full text, or unclear licensing, create a human review item instead of making a support judgment.

## Human Review States

Use explicit states in `state.json` and audit manifests:

```text
draft
machine_verified
human_verified
ready
blocked_human_review
```

Rules:

- `machine_verified` requires citation and semantic checks to pass or be explicitly waived by the user.
- `human_verified` is required for paid/inaccessible full-text judgments.
- `ready` requires no unresolved blocking format, citation, semantic, or access issues.
- Waivers must be recorded with reason, timestamp, and requesting user context.

## Source Integration Policy

Primary user research direction: computer science, computer technology, and data engineering.

Biomedical connectors may exist as optional domain examples, but they are not the default research scope.

Prioritize public, metadata-friendly sources:

- Crossref for DOI and bibliographic metadata.
- OpenAlex for literature graph, concepts, institutions, and open-access hints.
- Semantic Scholar for paper metadata, abstracts where available, citation graph, and TLDR-like metadata when licensing permits.
- arXiv for open preprints in CS, AI, data engineering, and related quantitative fields.
- DBLP for computer science bibliographic authority.
- IEEE Xplore as a human-gated or API-key-gated venue source for IEEE publications.
- ACM Digital Library as a human-gated or API-key-gated venue source for ACM publications.

Do not assume IEEE is a single paper collection. Treat it as a publisher/platform with IEEE journals, magazines, standards, and conference proceedings, accessible through IEEE Xplore or indexed indirectly by other metadata services.

## Audit Artifacts

Minimum artifacts for a complete run:

- `run_manifest.json`: source path, hashes, profile, timestamps, tool versions, and output list.
- `paper.ast.json`: normalized structured paper artifact.
- `audit/citations/citation_report.json`: citation existence and metadata checks.
- `audit/semantic_claims/claim_report.json`: extracted claims, linked evidence, verdicts, and unresolved items.
- `audit/format/format_report.json`: fonts, headings, table, equation, reference, and layout checks.
- `audit/human_review/items.json`: paid, inaccessible, ambiguous, or policy-sensitive items.
- `state.json`: current state, gates, waivers, and next required action.

For user-facing review, also produce a concise Markdown summary that links to the run artifacts and lists only actionable blockers.

## Implementation Order

When implementing this MVP inside the skill or a project that consumes it, build in this order:

1. Run directory and manifest creation.
2. Markdown ingestion and normalized AST generation.
3. Bibliography extraction and citation metadata verification.
4. Semantic claim extraction and evidence-link validation.
5. Academic format profile rendering.
6. PDF export and format audit.
7. Human-review queue for paid/inaccessible sources.
8. Optional source connectors and cache invalidation.

Keep each stage restartable from the previous artifact. Avoid hidden state.

## Minimum Validation Checklist

Before reporting completion for a Science Workbench task:

- The run directory follows the required naming pattern.
- The source Markdown path and content hash are recorded.
- The selected profile and TOC depth are recorded.
- `paper.ast.json` exists and validates against the minimum schema.
- Tables, equations, headings, citations, and references are represented structurally.
- Citation verification ran or a waiver exists.
- Semantic verification ran or a waiver exists. For normal paper generation, do not waive silently.
- Paid or inaccessible full-text items are in the human review queue.
- Rendered PDF was checked for font-size consistency, table overflow, equation glyphs, and heading/citation scale.
- Final response states artifact paths and remaining blockers.
