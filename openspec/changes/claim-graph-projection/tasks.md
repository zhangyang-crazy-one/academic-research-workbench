## 1. Snapshot and journal contracts

- [x] 1.1 Add original-validator fixed-prefix run replay and tamper/tail regressions.
- [x] 1.2 Add strict snapshot, semantic claim, occurrence, evidence and declared contracts; generate schemas.
- [x] 1.3 Extend existing narrative journal with claim registration/evidence/declared events while preserving retained event bytes and existing strategy projections.

## 2. Projection and advisory

- [x] 2.1 Implement bounded multi-log current/historical projection, optimistic double read and dependency closure using AcceptedRef adapters.
- [x] 2.2 Project accepted anchors, independent states, versioned UTF-8 occurrences and explicit coverage/unknown provenance.
- [x] 2.3 Implement revision/evidence-aware N-1 declared confirmation and advisory-only CLI handler.

## 3. Validation and documentation

- [x] 3.1 Exercise #94 fixtures 4–7, 9, 10 and 14 using real multi-run journals, tamper and historical replay.
- [x] 3.2 Verify unchanged narrative, writing and memory behavior; document CLI, limitations and schema contracts.

## 4. Authenticated parent anchors

- [x] 4.1 Add distinct authenticated-intent schema, parent 1.6.0 anchor reader migration and complete reducer authority semantics.
- [x] 4.2 Verify actual journal bytes/N-1 closure, separate historical authorization/current applicability and expose explicit hard MVP checks.
- [x] 4.3 Verify identity/time/prefix/tamper/resume cases and run-local canonical replay.

## 5. Figure, numeric and caption composition

- [x] 5.1 Compose the original fixed-prefix result_plot verifier through the public CLI with an optional kernel callback and explicit unsupported default.
- [x] 5.2 Recompute accepted sealed numeric derivations and verify Figure-backed own-result numeric identity/display, retaining per-claim binding verdicts.
- [x] 5.3 Add a true parent-anchor caption verifier over independent frozen targets, including real hard-caption writer acceptance and declared/wrong-target/prefix-negative tests.

## 6. PR #96 review corrections

- [x] 6.1 Keep cross-log pre-admission checks and run-local canonical replay; project unavailable/tampered anchor proofs as unverifiable.
- [x] 6.2 Remove replay-only anchor budget and verify archival, sibling lock, 129 anchors and incremental journal validation.
- [x] 6.3 Reserve core journal capacity and document the minimum reader/downgrade boundary.
- [x] 6.4 Bind hard caption applicability to an explicit instant or parent qualification request time.
- [x] 6.5 Update launcher cases and execute the complete non-host CI test tree, schemas and compatibility checks.
