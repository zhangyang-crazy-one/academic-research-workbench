## Context

The parent runtime already appends `experiment.provenance.accepted` under a writer lock. Contracts are write-once files with version and predecessor fields, but no parent acceptance event. The evaluator has an optional caller-supplied timing interface and CLI reports all predeclaration as unverified.

## Goals / Non-Goals

**Goals:** Record contract acceptance in the existing journal, validate succession under the same transaction, derive contract/provenance order from verified bytes, preserve historical receipt replay, and state the limited evidence claim.

**Non-Goals:** Proving the contract preceded external data collection, executing experiments, or claiming scientific preregistration.

## Decisions

- Add a compact `experiment.contract.accepted` Phase 4 event at additive event schema version `1.5.0`, with contract digest, version, and predecessor digest. Keep the full immutable contract in the existing content-addressed store; the journal remains the admission authority. Existing event families keep their historical schema versions.
- Publish immutable contract bytes before the event, then use the runtime's locked replay, expected revision, command ID, and reducer gate. An unaccepted published file has no timing authority. Under lock, validate that a successor's predecessor was accepted, belongs to the same claim and contract ID, and is the latest accepted version in that chain.
- Validate accepted contract and provenance manifests against each event during replay. A missing, changed, or mismatched artifact invalidates timing. Journal hashes and canonical bytes are verified by `replay_run`.
- Introduce evaluator 1.2.0 for journal-derived timing. It ignores caller-supplied sequence/time, reports external execution timing as unobserved, and adds an optional parent-order scope field only when both admission events are present. Keep 1.0.0 and 1.1.0 replay on their original arithmetic and timing rules, with old receipt bytes unchanged.
- Expose `arw experiment freeze --run-root --contract --request` and have accept/replay use the run journal. The request contains the existing parent `RuntimeCommandRequest` fields, not sequence or chain hashes.

## Risks / Trade-offs

- [Contract accepted before provenance does not prove execution began afterward] → Report `parent_acceptance_order_only` and describe external execution timing as unverified.
- [An immutable contract file may exist after a rejected command] → Only an accepted journal event counts; retries use a fresh command ID/revision or inspect the accepted event.
- [Existing 1.0.0 and 1.1.0 receipts may encode caller-supplied timing] → Preserve their legacy replay paths, and do not label those historical assertions as parent proof.

## Migration Plan

Add the new event type to the existing versioned reader without rewriting old journals. Existing contracts and receipts remain loadable; only newly accepted contracts have journal admission evidence.
