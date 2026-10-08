## Context and field mapping

| Existing record | Query/pool/rank/dedup/selection evidence | Actual reading / round / stop evidence | Gap handling |
|---|---|---|---|
| ARS frozen query plan | Claim, query text, index targets, caps, consent, plan digest | None | Never treat planned query as a read |
| ARS retrieval input | Attempts, returned/truncated counts, raw hit, provider rank, input digest | None | Never treat returned hit as a read |
| ARS candidate ledger | Work-family/version dedup, relevance assessment, selected family cap, terminal state | None | Selection means candidate for reading only |
| ARS transmission ledger | Query/stance-provider transmission counts | None | No human reading inference |
| ARW accepted artifact event/manifest | Same-run event, manifest, content digest and path | Only if content is an explicit reading trace | Reject stale/cross-run/changed bytes |
| Explicit accepted reading trace | Candidate family/raw ID, position, round, human stance assertion, reached rounds and stop reason when complete | Yes, to the extent the author's log states it | Missing/incomplete remains `unknown` |

## Decisions

The export reads only parent-accepted JSON artifacts under one healthy run and requires the caller's expected journal head. It validates the retained ARS plan, retrieval input, and candidate ledger with the bundled normative builder before producing a digest-sealed receipt. The installed plugin root is resolved from `ARW_PLUGIN_ROOT`; the checkout path is used only for source development. Missing bundled ARS is a typed unavailable capability. No persistent `sys.path` changes occur.

The receipt binds event/manifest/content digests, query and pool digests, raw provider ranks and dedup states, selected family IDs, explicit reading positions, rounds, stop reason, and coverage. If the reading log is absent or incomplete, complete coverage remains unknown. Final citations are never queried. Synthetic labels cannot be used in a retained human reading trace.

The fixed public fixture has two supportive, two opposing, one neutral, and one unknown/unread family, including a duplicate preprint/journal version. Its original citation has an exact synthetic source byte span and SHA-256 while two opposing families remain unread. It retains original order and early-stop outcome; paired support-first and oppose-first reorders use the same two-read budget. Direction is only the fixture label balance, not a manuscript or scientific conclusion. A separate four-item finite SRS example enumerates six equally likely draws to recompute inclusion probability 1/2 and a Horvitz–Thompson arithmetic example. Production export remains descriptive because neither the ARS candidate ledger nor a reading log proves a sampling design or inclusion/selection/reach probabilities.

## Risks and limits

An accepted author's log can still misstate what happened. The output identifies it as an assertion, not verified cognitive reading. An incomplete or missing log cannot establish zero reading. Search index omissions and undisclosed papers remain outside the retained pool. Equal-budget orderings show sensitivity within the fixture only; they do not estimate real-world bias or correct an actual review.
