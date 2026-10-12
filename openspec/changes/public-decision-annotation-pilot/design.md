## Context

#120 requires ten actual independent human annotations. The owner has asked for materials to annotate. Ten NumPy proposals provide inspectable numerical-method and research infrastructure decisions, including maintained, superseded, rejected, withdrawn and deferred proposals.

## Goals / Non-Goals

Prepare independently inspectable frozen source locators and a blank annotation sheet. Preserve pending versus explicitly unknown. Do not infer authors' motives from code diffs, claim pilot accuracy, or generalize this single-project convenience sample to all research.

## Decisions

Record immutable upstream commit URLs, whole-source SHA-256 and retrieval date. Only brief original summaries and metadata observations are redistributed, not upstream bodies. Upstream status is a source observation, not the human label. Human status, reason, locator, identity and date remain blank. Before annotations, freeze a separate source-status encoding protocol; do not adjust the machine recipe to fit later human labels. Defer actual comparison and two-round handoff acceptance until the owner returns annotations.

## Risks / Trade-offs

Single-project sampling -> disclose restricted scope. Changed live web page -> immutable source commit plus digest. Deferred is not automatically abandoned -> unknown machine disposition until stronger public decision evidence. No response from annotator -> pending, not fabricated unknown or agreement.
