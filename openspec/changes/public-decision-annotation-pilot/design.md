## Context

#120 requires ten actual human annotations. The owner returned ten answers, clarified the third as option B, and explicitly requested recording them in CSV. Ten NumPy proposals provide inspectable numerical-method and research infrastructure decisions, including maintained, superseded, rejected, withdrawn and deferred proposals.

## Goals / Non-Goals

Retain independently inspectable frozen source locators and the owner's actual annotation text. Preserve owner answers, historical labels, pending and explicitly unknown as distinct information. Do not infer authors' motives from code diffs, claim pilot accuracy, or generalize this single-project convenience sample to all research.

## Decisions

Record immutable upstream commit URLs, whole-source SHA-256 and retrieval date. Only brief original summaries and metadata observations are redistributed, not upstream bodies. Upstream status is a source observation, not the human label. Store the owner's answers in `human_annotation` with `annotation_basis=owner_response`, a current-session response locator, owner identity and transcription time; record option B in `selected_option`. Do not translate adoption conditions or reporting instructions into unsupported historical state/reason labels. Legacy source-history rows remain readable. Keep the previously frozen machine encoding unchanged. Defer actual historical comparison and two-round handoff acceptance until corresponding evidence exists.

The owner subsequently supplied explicit historical status labels after a source explanation: samples 1–6 and 10 are kept, 7 unknown, and 8–9 abandoned. Preserve the earlier responses byte-for-byte in `owner-policy-responses.csv`; use `annotations.csv` for the new source-history labels and original status wording. Reasons remain unknown because this answer only confirmed statuses. Describe these as assisted human annotations, not blind independent labels. Preserve sample 10's kept label despite the source's Superseded status, and report that difference during comparison without retuning the frozen mapping.

## Executed disposition replay

Read each pinned source's actual Status from hash-verified bytes and feed the previously frozen encoding into existing CLI select/propose/withdraw/approve operations. Bind each sample to one exported choice and keep necessary baseline/successor scaffolds outside the comparison. `pilot.source-replay` is the importer identity; its operator assertion is not NumPy-author authentication. Plan rationale and control reasons declare historical reasons unknown, rather than relabeling operational replay statements as causal evidence.

Keep all ten actual CLI trails, command transcripts, source/choice bindings and input snapshots. Recompute the report from validated canonical project journals; report 8 known agreements, 1 disagreement and 1 explicit unknown separately. Assisted human labels and this single-project operational replay cannot establish generalized accuracy or original-author scientific provenance.

For each abandoned case, initialize a real paper-bound run, admit the pilot's author-target artifact, and execute two memory handoff/checkpoint/Passport resume rounds in separate CLI processes. Supersede the first memory in round two. Verify accepted resume events, current IDs and abandoned notices, and reread canonical memory during offline evidence validation. This checks control-plane continuation context and an operator-authored next action, not language-model recommendation behavior.

The runner explicitly binds the repository plugin manifest for launcher resume; the missing automatic manifest binding is a separately recorded runtime defect. No production runtime contract is modified by this pilot.

## Risks / Trade-offs

Single-project sampling -> disclose restricted scope. Changed live web page -> immutable source commit plus digest. Deferred is not automatically abandoned -> unknown machine disposition until stronger public decision evidence. No response from annotator -> pending, not fabricated unknown or agreement.
