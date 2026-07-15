---
phase: 06
status: residual_findings_with_qualification_block
depth: standard
files_reviewed: 30
critical: 1
warning: 0
info: 0
total: 10
---

# Phase 06 Code Review

**Scope:** Phase 6 scientific-integrity receipts, external provenance,
access/claim gates, audit dossier, schema registry, stage allowlist, verifier,
runtime documentation, fixtures, and Phase 6 tests. Existing dirty Phase 4
and 04.1 files were excluded from implementation review.

**Review depth:** standard. The review included source inspection, focused
Phase 6 tests (`15 passed`), compile checks, staged validation, and direct
negative probes for claim, provenance, and integration-lock boundaries.

## Findings

### CR-01 — Public evidence promotion accepts an unverified hash

**Severity:** Critical
**Location:** `src/arw/evidence_access.py:188-205, 302-305`

`EvidenceAccessDecision` only requires that a `public_verification_receipt_sha256`
field be present. `validate_access_transition()` then compares the caller's
optional string with that same field; it never loads the receipt, checks its
canonical bytes, binds it to the evidence subject/input digests, or evaluates
freshness. A human-review decision can therefore be promoted to
`publicly_verified` with an invented digest. The direct probe below succeeds
without any receipt file:

```text
human_review_required -> publicly_verified
public_verification_receipt_sha256 = "e" * 64
```

This violates D-08/D-09 and allows `evaluate_claim_capability()` to consume a
false public state. Require a typed, digest-bound, fresh verification receipt
and parent-authorized transition before accepting public promotion.

### CR-02 — Claim freshness is broken and stale lifecycle records are accepted

**Severity:** Critical
**Location:** `src/arw/evidence_access.py:387-420, 460-478, 509-552`

`_fresh_until()` returns `False` only for `None` and has no executable body for
non-`None` values; its intended parsing code is unreachable after the
`_lifecycle_record_present()` return at line 415. Consequently every
`independent_review_complete` decision is reported as `review_gate_stale`, even
when `fresh_until` is in the future. Conversely, citation and audit capability
paths call `_lifecycle_record_present()`, which accepts any mapping containing
an arbitrary 64-character `*_sha256` field and does not check a typed record,
subject binding, or freshness. The existing audit test's six fabricated
`{"receipt_sha256": "..."}` mappings consequently produce `PASS`.

This gives both a false-negative review gate and false-positive citation/audit
claims, contrary to SCI-07. Restore a reachable, timezone-strict freshness
check and validate each lifecycle record against its canonical model and exact
subject before allowing `PASS`.

### CR-03 — Audit dossier accepts caller-supplied PASS claims and qualification

**Severity:** Critical  
**Location:** `src/arw/audit_dossier.py:319-328, 558-629`

`AuditDossierManifest` validates the hash of whatever verdicts it receives but
does not require evidence for a technical `PASS`, recompute claim capabilities,
or reject a `PASS` claim lacking access/integrity/review evidence. In
`assemble_audit_dossier()`, caller-supplied `claim_capabilities` and
`technical_qualification` override the default blocked/derived values. A
minimal manifest with no replay events, no receipts, and
`claim_capabilities=[{"capability":"citation_verified","verdict":"PASS"}]`
seals successfully. The function also trusts a supplied `replay_state` object
instead of re-running and validating the canonical journal/accepted manifests.

This permits a renderer caller to launder scientific or technical qualification
through a correctly hashed but unsupported dossier. The assembler must replay
and validate canonical state, derive capabilities and technical qualification
from typed fresh evidence, and reject unsupported caller verdicts.

### CR-04 — Phase 6 verifier does not enforce the Phase 04.1 integration lock

**Severity:** Critical  
**Location:** `scripts/verify-phase-6:147-165, 228-243`

The verifier merely records the lexicographically latest retained lock as an
optional identity. It does not require a lock, validate its canonical bytes,
compare it with the current staged ARW/file-base/hook/license identities, or
pass it to `stage-plugin --integration-lock`. The stage produced by the
verifier has no `supply-chain/integration-lock.json`, yet the verifier can emit
`technical_qualification: PASS`.

Current retained lock `phase-04.1-host-canary-20260715e` binds the ARW wheel to
`ab4770249f109083415bf3d4ca12f8dd8118b11c49c06ba3acb82b2d5769b7db`, while the
current staged wheel is `bb859698dca2f37f95416543d7a4f157fc1597c5cb0682a8bc1e5178f574e16a`.
The exact drift requested by the Phase 4/04.1 acceptance criteria is therefore
present but not rejected. Require an explicit lock input, validate it against
the stage, and fail closed on any ARW/ARS/file-base/Codex/hook/license drift.

### CR-05 — Missing local provenance references are silently accepted

**Severity:** Critical  
**Location:** `src/arw/experiment_provenance.py:508-533`

`_verify_local_references()` continues when a local dataset or artifact path is
absent. A provenance envelope can therefore name `missing/source.json` and
`missing/result.json`, provide arbitrary content digests, and still pass the
local-reference check and proceed to parent acceptance. This is not cold
replayable evidence and conflicts with SCI-04/D-04's strict digest-bound
ingestion contract. Missing local references must produce a typed blocker (or
reject ingestion); they must never be treated as verified merely because the
digest field is syntactically valid.

### CR-06 — Direct dossier sealing still accepts an un-derived technical PASS

**Severity:** Critical
**Location:** `src/arw/audit_dossier.py:151-157, 327-343, 365-377`

`assemble_audit_dossier()` now rejects caller-supplied PASS values and derives
claim/technical verdicts from validated replay and typed evidence. However,
`AuditDossierManifest.model_validate()` / `seal_audit_dossier()` and the public
`publish_audit_dossier()` path still accept a hand-built manifest whose
`technical_qualification` is `PASS` with a self-computed canonical proof but
without any run root, replay state, typed lifecycle receipts, or qualification
receipt. Starting from an empty blocked dossier, a caller can compute
`_qualification_proof(mapping)` and the outer dossier hash, and both the model
and seal paths accept the forged PASS:

```text
AuditDossierManifest.model_validate({technical_qualification: PASS,
  evidence_sha256: [_qualification_proof(mapping)], ...})  -> PASS
```

This leaves a second API path that can publish a correctly hashed but
unsupported technical qualification, bypassing the replay-first assembler.
The proof must bind to a parent replay/qualification receipt or publication
must accept only an assembler-produced authority envelope; a self-computed
subject digest is not evidence of replay.

## Warnings

### WR-01 — Read APIs create evidence directories

**Severity:** Warning  
**Location:** `src/arw/integrity.py:205-223`; `src/arw/experiment_provenance.py:478-500`

`load_integrity_receipt()` and `load_experiment_provenance()` call directory
helpers with `create=True`. A failed read of a missing receipt mutates the run
root by creating `integrity/receipts/sha256` or
`experiment/provenance/sha256`. Cold replay and read-only evidence inspection
should use `create=False`; publication is the only operation that should
materialize directories.

### WR-02 — Verifier can miss skip/xfail markers after output truncation

**Severity:** Warning  
**Location:** `scripts/verify-phase-6:124-143`

Command output is truncated to 512 KiB before the verifier scans it for
`skipped`, `xfailed`, and `xpassed`. A marker beyond the retained prefix is not
checked, although the command is then treated as clean. Retain bounded summary
metadata from the producer or scan an untruncated status channel before
declaring technical PASS.

### WR-03 — Parent authority envelope is forgeable at the API boundary

**Severity:** Warning  
**Location:** `src/arw/experiment_provenance.py:536-570`

`_authority_parts()` accepts a raw mapping and constructs a
`RuntimeCommandRequest` from caller data; the only authority test is the
self-declared `actor_role == "parent_control_plane"`. It can also instantiate a
new `RuntimeCommandService` when no service is supplied. There is no
parent-issued authentication/authority receipt binding the actor, request,
run root, and expected revision. The public ingest API should require the
already-created parent service plus a validated authority envelope and reject
raw mappings.

### WR-04 — Access decisions do not redact secret/private rationale or URIs

**Severity:** Warning  
**Location:** `src/arw/evidence_access.py:100-151`

Only NUL/backslash characters are rejected from `source_uri`; `rationale` and
`scope` have length constraints but no secret/private-path scan. API-token URLs,
credentials, private filesystem references, or copied private text can be
persisted in an otherwise valid access decision. Add the same positive
redaction/path policy used by provenance and dossier records, with tests for
query-string secrets and private paths.

## Review conclusion

CR-01 through CR-05 and WR-01 through WR-04 are resolved in `171db95`,
`922cbc9`, `4ae96d3`, `72f38a9`, and `bb087f3`. Public evidence promotion now loads a
canonical, digest-bound fresh integrity receipt from the approved run root and
requires a validated parent authority envelope; lifecycle claims and dossier
qualification are derived from typed replay evidence; local provenance and
authority APIs fail closed (including transition-role binding); credential-bearing
access references are rejected; read loaders are side-effect free; and the
verifier scans complete status streams and enforces the retained Phase 04.1 lock.

Post-fix verification on the current `bb087f3` checkout is **83 passed** for
the focused Phase 6 suite and **34 passed** for the Phase 4/5 composition
subset. The serial verifier was rerun with an owned repo-local temporary root;
it exits 70 and writes technical/release `BLOCKED` to
`build/evidence/phase-06-review/verdict.json`. Its exact retained-lock evidence
is in `integration-lock-drift.json`: ARW wheel SHA drift, file-base
`source-manifest.json` SHA drift, and ARS adapter `0.1.20 != 0.1.19`; the
stage-build stderr additionally records that the retained lock's patch set is
missing the qualified `0004-phase5-research-graph.patch`. The verifier therefore
fails closed rather than laundering a stale lock into technical PASS. Release
remains independently BLOCKED by SUP-04/P04-09 and unresolved CC BY-NC
intended-use/permission evidence.

A broad non-host invocation initially used the deliberately relative
`TMPDIR=build/tmp/phase-06` and produced **455 passed, 3 failed**. The failures
were `test_post_materialization_gate_preserves_native_toolchain_and_receipt`
(native gate `mktemp` could not resolve that relative directory),
`test_component_identity_and_release_classifier_do_not_collapse_licenses`
(the pre-existing dirty `supply-chain/use-distribution.json` carries stale
technical-provenance hashes), and
`test_phase1_clean_evidence_gate_retains_every_required_domain` (the broad
run's shared staged/evidence state yielded an identity mismatch). With the
controlled absolute repo-local TMPDIR required by the Phase 6 verifier, the
complete non-host regression rerun is **458 passed in 373.35s**; the two
affected modules also pass **3/3** in 71.44s. These are
environment/dirty-worktree qualification notes, not residual Phase 6 source
findings. CR-06 remains open after `e3a9250`: the canonical proof makes
persisted PASS round-trippable, but a caller can compute the same proof from a
forged mapping without replay or typed evidence. This is not a clean
code-review verdict until the qualification proof is parent-bound.
