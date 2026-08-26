---
phase: quick-260826-9p7-research-integrity-bridge
quick_task: 260826-9p7
verified: 2026-08-26T14:26:15Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: gaps_found
  previous_score: 4/6
  gaps_closed:
    - "The bridge now rejects authoritative-ARS-schema-invalid literature entries, including malformed arXiv IDs, explicit nulls, missing required fields, unknown fields, invalid patterns, and all sampled cross-field rules."
    - "The technical-provenance declaration now carries the exact final SBOM digest, and validate-only rejects stale digests even after an attacker rebinds build identity and inventory rows."
  gaps_remaining: []
  regressions: []
---

# Quick Task 260826-9p7 Verification Report

**Goal:** Implement the research-integrity bridge and close the diagnosed installation/adapter defects in one reviewable feature PR.

**Verified:** 2026-08-26T14:26:15Z
**Status:** `passed`
**Re-verification:** Yes — after gap closure in `c986552`

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Operators can distinguish the planned integration failures, and diagnostics cannot bypass the final exact verifier. | ✓ VERIFIED | Ten closed layers remain defined in `src/arw/integration_lock.py`; a verifier-injected final exact-verifier rejection still produced `BLOCKED/exact_lock_drift` after nine PASS layers. Plain and diagnostic route contracts remain fail-closed. |
| 2 | A strict ARS literature entry becomes a deterministic source -> span -> claim digest chain through installed schemas. | ✓ VERIFIED | `research_source_from_ars_entry` now applies the authoritative arXiv pattern, explicit-null boundary and all bundled-schema cross-field invariants before building a source manifest (`src/arw/research_integrity.py:37-71,141-278,414-437`). Required/pattern/additionalProperties/allOf probes reject at both the bundled ARS validator and bridge. Source/span/link builders still recompute canonical upstream digests and whole-chain validation rejects replacement. |
| 3 | Unicode/CJK filenames preserve display text and emit deterministic, collision-safe ASCII citekeys without Latin regression. | ✓ VERIFIED | The unchanged Task 3 implementation retains explicit Unicode family grammar, private NFKC hashing, ASCII collision suffixes and exact display text. All folder-adapter tests passed in the 180-test relevant regression. |
| 4 | Technical and legal qualification remain independent; experiments stay disabled and unresolved legal blockers remain BLOCKED. | ✓ VERIFIED | Plain route and diagnostics independently emitted `release_qualification=BLOCKED` and `experiment_execution=disabled`; `license-verdict.json` retains all four unresolved blockers. Commit `c986552` adds no legal approval, experiment enablement or canonical writer. |
| 5 | Root hooks are directly supply-chain gated, nested hooks cannot substitute, and hooks remain observational with parent-only canonical authority. | ✓ VERIFIED | All eight ARS gates pass, including exact root-hook SBOM binding. Root hook digests remain `4836bd8c...` and `ab94f35f...`; the fix commit does not touch hooks or introduce ArtifactAcceptance, Passport, ledger, retry, provenance or gate authority. |
| 6 | Stage/schema/SBOM/provenance metadata is exact and self-consistent. | ✓ VERIFIED | Actual and declared SBOM SHA-256 are both `1733c35df39190c7dadd9e92aedbe3b8b47bd84e2b65231081c99a6372272627`. Source freshness tests pass; a stale SBOM digest with rebound build identity/inventory is rejected by `stage-plugin --validate-only`; a fresh isolated stage builds and validates. |

**Score:** 6/6 truths verified

## Gap Closure Verification

### Gap 1: Authoritative ARS Schema Strictness

| Check | Result | Status |
|---|---|---|
| Original malformed arXiv counterexample | `arxiv_id=not-an-arxiv-id` is rejected by both authoritative schema and bridge | ✓ CLOSED |
| Original explicit-null counterexample | `venue: null` and every non-nullable optional top-level field are rejected | ✓ CLOSED |
| Required fields | Missing citation key, title, authors, year or source pointer is rejected | ✓ CLOSED |
| Patterns | Invalid citation key, DOI, arXiv ID and description source are rejected | ✓ CLOSED |
| `additionalProperties` | Unknown top-level and nested fields are rejected by frozen strict models | ✓ CLOSED |
| `allOf` sample | Source verification, venue pairing, trusted-source, contamination and arXiv-omission cases match the authoritative validator | ✓ CLOSED |
| Valid boundary sample | Minimal valid entry and sampled permitted boundary combinations remain accepted | ✓ CLOSED |

Independent custom probe covered eight invalid classes: malformed arXiv, explicit null, missing required, invalid pattern, additional property, source-verification allOf, venue-pair allOf and arXiv-omission allOf. All were rejected by both layers; a valid control entry passed both.

### Gap 2: Technical-Provenance Freshness

| Check | Result | Status |
|---|---|---|
| Repository freshness | Declared SBOM digest equals exact current `SBOM.cdx.json` bytes | ✓ CLOSED |
| All evidence rows | `test_use_distribution_technical_provenance_hashes_are_fresh` recomputes every declared file digest | ✓ CLOSED |
| Rebound stale declaration | Test mutates the staged SBOM row, then rebinds build identity and stage inventory | ✓ ATTACK CONSTRUCTED |
| Runtime rejection | `validate-only` exits nonzero with `technical provenance digest mismatch: SBOM.cdx.json` | ✓ CLOSED |
| Fresh stage | New `stage-plugin --clean` followed by `--validate-only` | ✓ PASS |

## Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `schemas/v1/research-integrity-contracts.schema.json` | Discriminated diagnostic/source/span/link schema | ✓ VERIFIED | Strict model projection, registry validation and staged installation remain byte-consistent. |
| `src/arw/research_integrity.py` | Strict ARS entrance, pure builders and whole-chain validator | ✓ VERIFIED | 573 substantive lines; authoritative invalids fail closed, valid Unicode metadata is preserved, and no parent writer is exposed. |
| `skills/academic-research-suite/ars/scripts/adapters/folder_scan.py` | Unicode-aware ingestion preserving display text | ✓ VERIFIED | Adapter 1.2.0 and all CJK/Latin/security regressions pass. |
| `scripts/stage-plugin` | Exact stage and provenance validation | ✓ VERIFIED | Both build and validate-only paths recompute technical provenance; unsafe, duplicate, stale and self-referential records fail closed. |
| `supply-chain/use-distribution.json` | Fresh non-cyclic evidence declaration | ✓ VERIFIED | SBOM row is current; the declaration itself is deliberately absent from SBOM components to avoid a hash cycle. |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `bin/arw` | `src/arw/cli.py` | Locked-wheel forwarding and additive diagnostics mode | ✓ WIRED | Route behavior is unchanged by the gap fix. |
| `src/arw/cli.py` | `src/arw/integration_lock.py` | Shared discovery plus exact final verification | ✓ WIRED | Diagnostic PASS still requires the original complete verifier. |
| `src/arw/research_integrity.py` | ARS entry schema semantics | Equivalent input constraints exercised against the bundled validator | ✓ WIRED | No runtime schema-file read was introduced; parity is pinned by 61 bridge tests. |
| `src/arw/research_integrity.py` | `src/arw/canonical.py` | Canonical bytes and SHA-256 at source/span/link hops | ✓ WIRED | Substitution/replacement tests remain green. |
| `src/arw/schema_registry.py` | `scripts/stage-plugin` | Schema registration and exact stage allowlist | ✓ WIRED | Relevant schema/stage regression passes. |
| `supply-chain/use-distribution.json` | `scripts/stage-plugin` | Recomputed technical-provenance digests | ✓ WIRED | Fresh stage passes; adversarial stale stage fails even after metadata rebinding. |

## Data-Flow Trace

| Artifact | Data | Source | Status |
|---|---|---|---|
| Integration diagnostics | lock/stage/host/hook/legal observations | Existing exact validators; final verifier owns PASS | ✓ FLOWING |
| Research-integrity bridge | validated ARS entry -> source -> span -> claim | Caller-supplied immutable documents, canonical digest helpers | ✓ FLOWING |
| Folder adapter | Unicode/Latin filenames -> passport entries | Confined directory scan and shared writer | ✓ FLOWING |
| Provenance gate | declaration rows -> exact staged target bytes | Source and staged SBOM/legal artifacts | ✓ FLOWING |

## Behavioral Spot-Checks

| Behavior | Command / Probe | Result | Status |
|---|---|---|---|
| Gap-focused bridge/freshness tests | Research-integrity module plus source freshness node | `62 passed in 1.95s` | ✓ PASS |
| Rebound stale provenance | Dedicated staged validate-only attack node | `1 passed in 9.82s` | ✓ PASS |
| Relevant feature regression | Integration lock, research integrity, schema drift, supply chain, ARS full-runtime gates and folder adapter | `180 passed in 190.39s` | ✓ PASS |
| Static ARS gates | `ars_codex_quality_gates.py all --json` | All eight gates PASS | ✓ PASS |
| Isolated exact stage | Fresh `--clean`, then `--validate-only` | `stage ready`; `stage valid` | ✓ PASS |
| Legal/execution invariants | Plain and diagnostic route probes | BLOCKED release and disabled experiments | ✓ PASS |
| Syntax/hygiene | `bash -n`, Python compilation, `git diff --check` | Exit 0 | ✓ PASS |

## Full Non-Host Regression Attribution

Independent rerun:

```text
22 failed, 567 passed, 4 skipped, 3 deselected, 1 error in 492.64s
```

The failures do not identify a `c986552` regression:

| Class | Count | First failing condition | Attribution |
|---|---:|---|---|
| Materialized vendor inputs | 3 failures + 1 setup error | `vendor/sources` or component license tree absent | Isolated checkout prerequisite absent before behavior under test |
| Retained qualification/history evidence | 10 failures | Missing/stale Phase 1 sanitizer/license receipts or Phase 4.1/5 verdict trees | Historical evidence prerequisite absent; none of the five gap-fix files is exercised before failure |
| System tracing | 2 failures | `offline-exec: strace is unavailable` or no verdict produced after that abort | Host tool prerequisite absent |
| Installed launcher isolation | 6 failures | Retained stderr: `bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted` | Sandbox capability denial before installed CLI/MCP behavior; independently reproduced for version, CLI and MCP |
| Existing route reason-code expectation | 1 failure | Test expects `integration_inputs_incomplete`, runtime returns `integration_lock_not_verified` after all qualification inputs are absent | Pre-existing main test/contract mismatch; `c986552` touches neither CLI/contracts nor this test and does not change the fail-closed outcome |

All tests that directly exercise the five gap-fix files are green, including the complete staged supply-chain module within the 180-test selection. The non-host failures therefore remain environmental/pre-existing audit debt, not a regression introduced by the closure commit.

## Requirements Coverage

No requirement IDs are declared in the quick-task PLAN frontmatter. The six observable truths above cover the PLAN must-haves and the verifier-specific hook, authority, schema and provenance checks.

## Anti-Patterns

No `TBD`, `FIXME` or `XXX` marker, placeholder implementation, install-cache edit, alternate canonical writer, legal approval, or experiment enablement was introduced by `c986552`.

## Commit and Diff Integrity

- Original task commits remain `50d76b6`, `819b1ce`, and `1058967`.
- Gap closure is one atomic commit: `c986552 fix(integrity): close schema and provenance gaps`.
- The fix modifies exactly five relevant files and deletes nothing.
- Final `origin/main...HEAD` contains four commits and 18 implementation files.
- `git diff --check origin/main...HEAD` passes; tracked worktree was clean before this report update.

## Remaining Risks

- Release remains intentionally BLOCKED pending intended-use, distribution-class, accountable-approval and CC BY-NC permission evidence.
- Current sandbox cannot execute bwrap network namespace isolation; this does not affect the independently passing stage, contract or provenance checks.
- The pre-existing missing-lock reason-code assertion should be reconciled separately, but it neither permits PASS nor changes this quick task's delivered behavior.

## Final Assessment

Both previously blocking gaps are closed with executable negative tests and runtime gates. No regression attributable to `c986552` was found. All must-haves are verified and the quick-task goal is achieved.

---

_Verified: 2026-08-26T14:26:15Z_
_Verifier: independent GSD quick-task verifier_
