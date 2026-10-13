## Context

#120 requires ten actual independent human annotations. The owner returned ten answers, clarified the third as option B, and explicitly requested recording them in CSV. Ten NumPy proposals provide inspectable numerical-method and research infrastructure decisions, including maintained, superseded, rejected, withdrawn and deferred proposals.

## Goals / Non-Goals

Retain independently inspectable frozen source locators and the owner's actual annotation text. Preserve owner answers, historical labels, pending and explicitly unknown as distinct information. Do not infer authors' motives from code diffs, claim pilot accuracy, or generalize this single-project convenience sample to all research.

## Decisions

Record immutable upstream commit URLs, whole-source SHA-256 and retrieval date. Only brief original summaries and metadata observations are redistributed, not upstream bodies. Upstream status is a source observation, not the human label. Store the owner's answers in `human_annotation` with `annotation_basis=owner_response`, a current-session response locator, owner identity and transcription time; record option B in `selected_option`. Do not translate adoption conditions or reporting instructions into unsupported historical state/reason labels. Legacy source-history rows remain readable. Keep the previously frozen machine encoding unchanged. Defer actual historical comparison and two-round handoff acceptance until corresponding evidence exists.

The owner subsequently supplied explicit historical status labels after a source explanation: samples 1–6 and 10 are kept, 7 unknown, and 8–9 abandoned. Preserve the earlier responses byte-for-byte in `owner-policy-responses.csv`; use `annotations.csv` for the new source-history labels and original status wording. Reasons remain unknown because this answer only confirmed statuses. Describe these as assisted human annotations, not blind independent labels. Preserve sample 10's kept label despite the source's Superseded status, and report that difference during comparison without retuning the frozen mapping.

## Risks / Trade-offs

Single-project sampling -> disclose restricted scope. Changed live web page -> immutable source commit plus digest. Deferred is not automatically abandoned -> unknown machine disposition until stronger public decision evidence. No response from annotator -> pending, not fabricated unknown or agreement.
