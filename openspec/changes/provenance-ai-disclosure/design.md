## Context

Accepted provenance is the source; graph associations and hooks are observations. Missing history for imported or external editing remains unknown. Native/platform and API harness identities are recorded as data, never constrained by this feature.

## Goals / Non-Goals

Cover unanchored accepted text, figure specifications and analysis code. Separate receipt-observed from human-declared statements and unknown coverage. No determination of human authorship, forensic AI detection, scientific gate changes or policy compliance certification.

## Decisions

Add typed AI activity receipts (target exact ParentArtifactRef, activity/system/usage) and typed human participation declarations (target, author, usage), accepted through the existing parent artifact writer. Receipt-observed means integrity-bound accepted receipt contents; it does not independently attest that a particular host/model executed. All evidence is validated with the original AcceptedRef resolver. A record cannot bless a generic JSON receipt, missing output, future prefix or mismatched target. Missing records are unknown. Distinct sources and mixed histories remain separately listed; absent records do not default to human.

PolicySnapshot retains a venue, version, verified date, primary source URL/digest and bounded original normalized requirements/template. ARR checklist and IEEE acknowledgment templates stay separate. Draft embeds its entire snapshot, canonical summary and exact run prefixes; digest and replay use old prefixes/snapshot without network access. Latest policy changes cannot rewrite old draft bytes. Final review is explicitly required and never fabricated.

## Risks / Trade-offs

Incomplete real history -> unknown plus human review. Declared receipt contents mistaken for authenticated calls -> explicit proof scope. Policy changing -> dated frozen snapshots and owner verification before submission. No source redistribution permission -> retain brief normalized paraphrases and source digests, not full policy documents. Invented application status -> no automatic submission or approval fields.

## Owner review amendment

Expose disclosure through the public launcher and distinguish imported receipts from AI drafting in versioned draft wording, preserving generator 1.0.0 replay.
