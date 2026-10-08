## Context

`.arw/narrative/events.jsonl` already records selected plans, proposed replacement plans and reasons, and author-confirmed approvals. It is hash chained and read under a project lock. The current snapshot alone hides superseded routes; a pending proposal has no existing way to be explicitly withdrawn. Run journals and memory records contain their own artifact and successor relations, but they do not establish an author's motivation for a narrative change.

## Goals / Non-Goals

**Goals:** Derive an exact, bounded view of selected, superseded, withdrawn, and pending routes; cite the original event for each plan and reason; let an author withdraw a pending proposal without selecting a successor; expose the current and abandoned route summary at paper continuation.

**Non-Goals:** Infer intent from Git diffs, index all project runs, reinterpret memory as a scientific fact, or build a second decision ledger. A public ten-entry author-record pilot requires identifiable source material and remains open until it is actually measured.

## Decisions

1. **Replay the existing journal in full before projecting an old view.** The trail uses the current `_read` validation and shared lock, then projects a prefix selected by `--at-sequence`. `--expected-head-sha256` checks the full history head, so a stale caller fails before export. Missing selection, damaged history, and unrelated non-paper projects have distinct results. This avoids treating a corrupt tail as a valid old view.
2. **Represent missing abandonment as an append-only withdrawal event.** `withdrawn` names the pending proposal digest and records a bounded author ID and reason after explicit `--author-confirmed`. It clears only that pending proposal. The current selected plan remains active. This supports a withdrawn branch followed by another proposal without rewriting earlier events.
3. **Keep provenance and interpretation separate.** A selected plan's `rationale` is a plan statement, not independently authenticated author intent. An adoption reason comes from its proposal; a later supersession reason is separate and keeps its own proposal source. The approval event records the claimed author confirmation. A withdrawal reason comes from the withdrawal event. Pending proposals have `unknown` disposition. Actual research artifacts and memory successors may be listed only from an explicitly supplied, validated run journal; absent links remain unknown, never guessed from matching text. A historical project view rejects a current run attachment.
4. **Build continuation context from the same projector.** Paper handoff/resume responses include a concise `current_choices`, `abandoned_routes`, and `unresolved_questions` projection bound to the same history head as the current narrative snapshot. It is computed on read; no projection file is stored. Non-paper runs retain `not_applicable`.

## Risks / Trade-offs

- Large histories can exceed a continuation context budget. The CLI caps trajectory rows and bytes and fails with an explicit limit error; handoff keeps a smaller summary and refuses to silently omit abandoned choices.
- `--author-confirmed` is an operator assertion, as with approval. The CLI does not authenticate the human author; output labels this provenance accurately.
- An old view is historical, not an actionable current strategy. It carries both the requested view head and the validated current history head.

## Migration Plan

Existing v1 events and selected plans replay unchanged. The new event kind is additive. Rollback to an older runtime after a withdrawal would reject the unknown event, so releases that contain withdrawals must retain the updated reader. No background migration or data rewrite occurs.
