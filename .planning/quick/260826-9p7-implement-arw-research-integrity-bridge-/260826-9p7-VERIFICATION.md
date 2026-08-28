---
phase: quick-260826-9p7-research-integrity-bridge
quick_task: 260826-9p7
verified: 2026-08-28T01:25:38Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: passed
  previous_score: 6/6
  gaps_closed:
    - "The bridge now rejects authoritative-ARS-schema-invalid literature entries, including malformed arXiv IDs, explicit nulls, missing required fields, unknown fields, invalid patterns, and all sampled cross-field rules."
    - "The technical-provenance declaration now carries the exact final SBOM digest, and validate-only rejects stale digests even after an attacker rebinds build identity and inventory rows."
  gaps_remaining: []
  regressions: []
incremental_commits_verified:
  - df7bcfb
  - 7a8ed97
  - c986e8f
---

# Quick Task 260826-9p7 Verification Report

**Goal:** Implement the research-integrity bridge and close the diagnosed installation/adapter defects in one reviewable feature PR.

**Verified:** 2026-08-28T01:25:38Z
**Status:** `passed`
**Re-verification:** Yes — after all review closures and final evidence refresh on 2026-08-28

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Operators can distinguish the planned integration failures, and diagnostics cannot bypass the final exact verifier. | ✓ VERIFIED | Ten closed layers remain defined in `src/arw/integration_lock.py`; a verifier-injected final exact-verifier rejection still produced `BLOCKED/exact_lock_drift` after nine PASS layers. Plain and diagnostic route contracts remain fail-closed. |
| 2 | A strict ARS literature entry becomes a deterministic source -> span -> claim digest chain through installed schemas. | ✓ VERIFIED | `research_source_from_ars_entry` now applies the authoritative arXiv pattern, explicit-null boundary and all bundled-schema cross-field invariants before building a source manifest (`src/arw/research_integrity.py:37-71,141-278,414-437`). Required/pattern/additionalProperties/allOf probes reject at both the bundled ARS validator and bridge. Source/span/link builders still recompute canonical upstream digests and whole-chain validation rejects replacement. |
| 3 | Unicode/CJK filenames preserve display text and emit deterministic, collision-safe ASCII citekeys without Latin regression. | ✓ VERIFIED | The Task 3 implementation and ASCII-compatibility fix retain explicit Unicode family grammar, private NFKC hashing, ASCII collision suffixes, legacy Latin citation keys, exact display text and fail-soft undecodable-byte rejection. All 245 adapter tests passed. |
| 4 | Technical and legal qualification remain independent; experiments stay disabled and unresolved legal blockers remain BLOCKED. | ✓ VERIFIED | Plain route and diagnostics independently emitted `release_qualification=BLOCKED` and `experiment_execution=disabled`; `license-verdict.json` retains all four unresolved blockers. The three incremental commits add no legal approval, experiment enablement or canonical writer. |
| 5 | Root hooks are directly supply-chain gated, nested hooks cannot substitute, and hooks remain observational with parent-only canonical authority. | ✓ VERIFIED | All eight ARS gates pass, including exact root-hook SBOM binding. Root hook digests remain `4836bd8c...` and `ab94f35f...`; none of `df7bcfb`, `7a8ed97` or `c986e8f` touches hooks or introduces ArtifactAcceptance, Passport, ledger, retry, provenance or gate authority. |
| 6 | Stage/schema/SBOM/provenance metadata is exact and self-consistent. | ✓ VERIFIED | Integration lock v2 binds the cycle-free build-identity metadata projection while live verification recomputes manifest coverage. ARS suite/ars tree hashes are exactly `388785916d7e95ade8f828f7de15bfa1e787cca88d5cfa0d8e2b408889b14b29` / `72be4da2405e441ebd2a9afd1dda7a168986df8053192c919d8dcc4db019f5b2`; actual and declared SBOM SHA-256 are both `18c4e1ce44d3f8dc36d368c58f1b7d51159335f79f936973ab8d4ebda812092a`. Source freshness, quality gates and a fresh isolated stage all pass. |

**Score:** 6/6 truths verified

## Final Incremental Commit Verification

### `df7bcfb`: Fresh Pytest Basetemp

`tests/conftest.py` now removes only the run-specific `build/pytest-tmp` tree and then creates its parent before assigning `config.option.basetemp`. An independent invocation replaced `TEST_TMP_BASE` with a never-created `<temp>/fresh-checkout/build/pytest-tmp`; `pytest_configure` created `<temp>/fresh-checkout/build` and assigned the expected basetemp without error. This closes the fresh-checkout startup failure without weakening test cleanup or changing test evidence bytes.

### `7a8ed97`: Python 3.13/3.14 Matrix Interpreter

The Python job has one authoritative matrix value at both interpreter-selection boundaries:

- `uv sync --frozen --all-groups --python "${{ matrix.python-version }}"` creates the job-local environment with the `actions/setup-python` interpreter.
- Job-wide `UV_PYTHON: ${{ matrix.python-version }}` is inherited by all four later `uv run` commands, including the ARS working-directory invocation.

`uv run --help` confirms `UV_PYTHON` is the environment form of `--python`; a local control with `UV_PYTHON=/usr/bin/python3.14` ran under Python 3.14.6. The Python job contains no hard-coded `3.14.6` or `.python-version` read, so a fresh 3.13 job is no longer redirected to the repository pin.

### `c986e8f`: Five-Document Layout Export Contract

The five synchronized documents contain operational rules rather than isolated marker strings:

| Document | Substantive Contract |
| --- | --- |
| `academic-paper/WORKFLOW.md` | Phase 7 must apply paragraph, proportional-asset, float-order and all-page render checks; compilation alone cannot support camera-ready status. |
| `agents/formatter_agent.md` | Concrete prohibitions and actions for global `parindent`, proportional asset fitting, one/two-column float choice, pending starred floats and PNG contact-sheet review. |
| `academic_pdf_format_reference.md` | Class-aware indentation, local exceptions, source-order scheduling, barrier timing and every-page inspection. |
| `latex_template_reference.md` | Official-class indentation, non-destructive figure fitting, `figure*` selection, callout ownership and legal barrier placement. |
| `venue_family_hard_packs.md` | Hard expectations for source-order float scheduling and compiler-insufficient render audit. |

The two-line workflow label is a stable audit identifier, but it is not the sole content: the same section immediately imposes the Phase 7 and camera-ready gates. The mutation suite passes and proves removal of a substantive formatter rule or a synchronized document fails closed.

## Gap Closure Verification

### Gap 1: Authoritative ARS Schema Strictness

| Check | Result | Status |
| --- | --- | --- |
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
| --- | --- | --- |
| Repository freshness | Declared SBOM digest equals exact current `SBOM.cdx.json` bytes | ✓ CLOSED |
| All evidence rows | `test_use_distribution_technical_provenance_hashes_are_fresh` recomputes every declared file digest | ✓ CLOSED |
| Rebound stale declaration | Test mutates the staged SBOM row, then rebinds build identity and stage inventory | ✓ ATTACK CONSTRUCTED |
| Runtime rejection | `validate-only` exits nonzero with `technical provenance digest mismatch: SBOM.cdx.json` | ✓ CLOSED |
| Fresh stage | New `stage-plugin --clean` followed by `--validate-only` | ✓ PASS |

## Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `schemas/v1/research-integrity-contracts.schema.json` | Discriminated diagnostic/source/span/link schema | ✓ VERIFIED | Strict model projection, registry validation and staged installation remain byte-consistent. |
| `src/arw/research_integrity.py` | Strict ARS entrance, pure builders and whole-chain validator | ✓ VERIFIED | 573 substantive lines; authoritative invalids fail closed, valid Unicode metadata is preserved, and no parent writer is exposed. |
| `skills/academic-research-suite/ars/scripts/adapters/folder_scan.py` | Unicode-aware ingestion preserving display text | ✓ VERIFIED | Adapter 1.2.0 and all CJK/Latin/security regressions pass. |
| `scripts/stage-plugin` | Exact stage and provenance validation | ✓ VERIFIED | Both build and validate-only paths recompute technical provenance; unsafe, duplicate, stale and self-referential records fail closed. |
| `supply-chain/use-distribution.json` | Fresh non-cyclic evidence declaration | ✓ VERIFIED | SBOM row is current; the declaration itself is deliberately absent from SBOM components to avoid a hash cycle. |

## Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `bin/arw` | `src/arw/cli.py` | Locked-wheel forwarding and additive diagnostics mode | ✓ WIRED | Route behavior is unchanged by the gap fix. |
| `src/arw/cli.py` | `src/arw/integration_lock.py` | Shared discovery plus exact final verification | ✓ WIRED | Diagnostic PASS still requires the original complete verifier. |
| `src/arw/research_integrity.py` | ARS entry schema semantics | Equivalent input constraints exercised against the bundled validator | ✓ WIRED | No runtime schema-file read was introduced; parity is pinned by 61 bridge tests. |
| `src/arw/research_integrity.py` | `src/arw/canonical.py` | Canonical bytes and SHA-256 at source/span/link hops | ✓ WIRED | Substitution/replacement tests remain green. |
| `src/arw/schema_registry.py` | `scripts/stage-plugin` | Schema registration and exact stage allowlist | ✓ WIRED | Relevant schema/stage regression passes. |
| `supply-chain/use-distribution.json` | `scripts/stage-plugin` | Recomputed technical-provenance digests | ✓ WIRED | Fresh stage passes; adversarial stale stage fails even after metadata rebinding. |

## Data-Flow Trace

| Artifact | Data | Source | Status |
| --- | --- | --- | --- |
| Integration diagnostics | lock/stage/host/hook/legal observations | Existing exact validators; final verifier owns PASS | ✓ FLOWING |
| Research-integrity bridge | validated ARS entry -> source -> span -> claim | Caller-supplied immutable documents, canonical digest helpers | ✓ FLOWING |
| Folder adapter | Unicode/Latin filenames -> passport entries | Confined directory scan and shared writer | ✓ FLOWING |
| Provenance gate | declaration rows -> exact staged target bytes | Source and staged SBOM/legal artifacts | ✓ FLOWING |

## Behavioral Spot-Checks

| Behavior | Command / Probe | Result | Status |
| --- | --- | --- | --- |
| Gap-focused bridge/freshness tests | Research-integrity module plus source freshness node | `62 passed in 1.95s` | ✓ PASS |
| Rebound stale provenance | Dedicated staged validate-only attack node | `1 passed in 9.82s` | ✓ PASS |
| Relevant feature regression | Integration lock, research integrity, schema drift, supply chain, ARS full-runtime gates and folder adapter | `180 passed in 190.39s` | ✓ PASS |
| Static ARS gates | `ars_codex_quality_gates.py all --json` | All eight gates PASS | ✓ PASS |
| Isolated exact stage | Fresh `--clean`, then `--validate-only` | `stage ready`; `stage valid` | ✓ PASS |
| Fresh-checkout basetemp | Invoke exact `pytest_configure` with a missing `<temp>/fresh-checkout/build` parent | Parent created and basetemp assigned | ✓ PASS |
| CI matrix pin | Parse workflow; inspect sync and all four `uv run` consumers; confirm uv maps `UV_PYTHON` to `--python` | 3.13/3.14 matrix value reaches sync and every run | ✓ PASS |
| Layout export contract | `test_check_layout_export_contract.py` plus semantic inspection of all five additions | `3 passed`; every surface carries actionable rules | ✓ PASS |
| Final incremental regression | Layout contract, provenance freshness, bridge and folder adapter | `82 passed in 3.66s` | ✓ PASS |
| Final ARS/SBOM freshness | Independently recompute both ARS tree hashes and declaration SBOM hash | All exact; fresh stage validates | ✓ PASS |
| Legal/execution invariants | Plain and diagnostic route probes | BLOCKED release and disabled experiments | ✓ PASS |
| Syntax/hygiene | `bash -n`, Python compilation, `git diff --check` | Exit 0 | ✓ PASS |

## Full Non-Host Regression Attribution

Independent rerun:

```text
22 failed, 567 passed, 4 skipped, 3 deselected, 1 error in 492.64s
```

The failures do not identify a `c986552` regression:

| Class | Count | First failing condition | Attribution |
| --- | ---: | --- | --- |
| Materialized vendor inputs | 3 failures + 1 setup error | `vendor/sources` or component license tree absent | Isolated checkout prerequisite absent before behavior under test |
| Retained qualification/history evidence | 10 failures | Missing/stale Phase 1 sanitizer/license receipts or Phase 4.1/5 verdict trees | Historical evidence prerequisite absent; none of the five gap-fix files is exercised before failure |
| System tracing | 2 failures | `offline-exec: strace is unavailable` or no verdict produced after that abort | Host tool prerequisite absent |
| Installed launcher isolation | 6 failures | Retained stderr: `bwrap: loopback: Failed to create NETLINK_ROUTE socket: Operation not permitted` | Sandbox capability denial before installed CLI/MCP behavior; independently reproduced for version, CLI and MCP |
| Existing route reason-code expectation | 1 failure | Test expects `integration_inputs_incomplete`, runtime returns `integration_lock_not_verified` after all qualification inputs are absent | Pre-existing main test/contract mismatch; `c986552` touches neither CLI/contracts nor this test and does not change the fail-closed outcome |

All tests that directly exercise the five gap-fix files are green, including the complete staged supply-chain module within the 180-test selection. The non-host failures therefore remain environmental/pre-existing audit debt, not a regression introduced by the closure commit.

## Requirements Coverage

No requirement IDs are declared in the quick-task PLAN frontmatter. The six observable truths above cover the PLAN must-haves and the verifier-specific hook, authority, schema and provenance checks.

## Anti-Patterns

No `TBD`, `FIXME` or `XXX` marker, placeholder implementation, install-cache edit, alternate canonical writer, legal approval, or experiment enablement was introduced by the three final incremental commits. The layout markers are embedded in prescriptive contract sections, not detached string fixtures.

## Commit and Diff Integrity

- Original task commits remain `50d76b6`, `819b1ce`, and `1058967`.
- Gap closure is one atomic commit: `c986552 fix(integrity): close schema and provenance gaps`.
- Final incremental fixes are `df7bcfb` (fresh basetemp + matrix sync), `7a8ed97` (job-wide matrix pin), and `c986e8f` (layout contract + provenance refresh); their file ownership is disjoint except the intentional two-step CI workflow edit.
- `c986e8f` updates exactly five contract documents plus the enclosing/ARS SBOM tree rows and fresh use-distribution SBOM digest; it deletes nothing.
- Final `origin/main...HEAD` contains seven implementation/fix commits plus `4282002` (verification-artifact commit): eight commits and 29 changed files including PLAN/SUMMARY/STATE/VERIFICATION artifacts.
- `git diff --check origin/main...HEAD` passes; tracked worktree was clean before this report update.

## Remaining Risks

- Release remains intentionally BLOCKED pending intended-use, distribution-class, accountable-approval and CC BY-NC permission evidence.
- Current sandbox cannot execute bwrap network namespace isolation; this does not affect the independently passing stage, contract or provenance checks.
- The pre-existing missing-lock reason-code assertion should be reconciled separately, but it neither permits PASS nor changes this quick task's delivered behavior.

## Final Assessment

Both previously blocking gaps remain closed with executable negative tests and runtime gates. The final CI and layout-contract commits close their targeted fresh-checkout/matrix/synchronization failures without changing authority, legal status or execution policy. No new gap was found; all must-haves remain verified and the quick-task goal is achieved.

---

_Verified: 2026-08-26T15:33:48Z_
_Verifier: independent GSD quick-task verifier_
