## Context

#125 reproduces lost revision-2 history becoming healthy revision 1. An empty segments directory is not evidence that an initialization event was never committed.

## Goals / Non-Goals

Goals: exact durable initialization recovery; reject history loss; preserve accepted artifacts, identities and legacy healthy runs. No alternate ledger or reconstruction from artifacts/projections.

## Decisions

Opt-in initialization writes a create-only prepared transaction before creating journal storage. It binds the exact request, manifest and initial-event digests. A separate create-only completion receipt is sealed after successful canonical replay. Writer entry seals any surviving prepared transaction before yielding to later commands, including a run whose initializer died immediately after the first event became durable. Both receipts are transaction evidence, never a source of accepted records or scientific status.

Missing first history is resumable only with an exact prepared transaction, no completion receipt, safe empty journal storage and no additional run material. Status uses the same pending-transaction predicate. Old complete runs remain readable without receipts; ambiguous legacy partial runs are rejected rather than retroactively authorized. An empty journal alone is never enough. Symlinks, malformed/cross-request transactions and changed retained inputs fail closed.

Keep receipts outside journal storage and keep existing canonical bytes unchanged. Use the existing sole-writer lock, exclusive writes and directory fsync. Read-only projections do not create receipts. Recovery never deletes user material or manufactures an acceptance event.

## Risks / Trade-offs

- Crash between first event and completion -> a later writer seals the same first event before any mutation; startup resumes existing history without rewriting it.
- Completion and journal lost together -> additional run material makes recovery ambiguous and is refused. Wholesale deletion/forgery of all independent files cannot be proven from their absence and is outside this local transaction protocol.
- Old manifest-only partial runs -> explicit recovery required; do not fabricate a prepared transaction.

## Migration Plan

New research starts use the transaction receipts. Existing intact runs need no migration. Missing legacy history fails closed. No receipt is admitted as a canonical event; downgrade does not reinterpret accepted history.

## Open Questions

None for #125; performance and subsequent research features remain separate issues/PRs.
