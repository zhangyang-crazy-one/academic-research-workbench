---
name: writing
description: Prepare academic revisions with explicit author goals, measured surface controls and source-bound preservation review.
---

# Writing revisions

Use the installed `bin/arw writing` contract. Preserve the accepted source.
Select one capability: `writing.academic_rewrite` (academic tone/organization),
`writing.naturalize` (readability), `writing.statistical_humanize` (declared surface
regularities), `writing.claim_preserving_rewrite` (claim-centered wording), or
`writing.citation_aware_rewrite` (evidence attribution).

1. Record the author's target, source artifact ID/digest, language (`en`, `zh`,
   `en-zh`), protected terms/quotations and controls. Produce an explicit
   `arw.writing-proposal.v1` JSON: ordered Unicode-character offsets with exact
   `before` and `replacement` spans; record actual provider/model/version,
   prompt SHA-256 and parameters. Do not invent model identity or credentials.
2. Call `bin/arw writing prepare --run-root RUN --source-id ARTIFACT --proposal FILE`.
   Inspect actual before/after metrics and each control's effective/ineffective
   outcome. Revise ineffective edits; Unicode or metadata cleanup does not fulfill
   statistical controls. Surface metrics are not human-authorship evidence and
   no statistical watermark detector is currently qualified.
3. Record rejected or unresolved candidates with `writing record` and the same
   arguments plus `--request REQUEST`. The request is the existing parent runtime
   command envelope. A ledger-bound review receipt is not accepted manuscript prose.
4. Compare claims, logical direction, values/units/equations, citations and scope,
   hedging, negation, comparisons, experimental conditions, method/dataset names
   and quoted meaning. Hard drift must be corrected. Every other changed candidate
   needs explicit human review; never fabricate approval. The parent may admit
   the real review as artifact kind `writing-human-review`, then use
   `writing record ... --review-artifact-id REVIEW --request NEW_REQUEST`.
   Review JSON binds source/candidate/proposal/verification digests, decision
   `APPROVED`, all `unresolved_dimensions` as `reviewed_dimensions`, reviewer and
   rationale. Prior review of different bytes is invalid.

Generators and reviewers propose; the parent alone uses canonical admission.
Read `docs/runtime/writing.md` in the source distribution for metric definitions,
review schema and limitations. Original and candidate text remain in the immutable
bundle so review can be repeated without regenerating model output.
