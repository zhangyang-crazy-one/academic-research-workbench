# v0.2.0 release procedure and notes

v0.2.0 adds authenticated, revision-bound claim graphs and exact numeric
derivations, with deterministic single-panel result plots. Authorization
confirmation is anchored to the parent ledger's `occurred_at`. Proof checking
remains independent of canonical parent replay; graph and hard-caption
consumers verify evidence at their own boundaries.

Since v0.1.0 the workbench also gained receipt-bound experiment planning,
source-linked narrative workflows, bounded deduplicated writing receipts,
versioned exact experiment evaluators, independent offline/native evaluation
profiles, retrieval-selection audit, evidence-bound learning, and the optional
paper-method package. Daemon root-session checks and nightly sanitizer
execution were corrected. Current readers retain explicitly supported legacy
records; downgrades must follow the reader-compatibility documentation.

The result-plot MVP covers one panel, source-bound estimates and explicit
interval semantics. SD/SE recomputation, TeX/disclosure expansion and
ReviewConcern integration remain follow-up work.

## Formal release

1. Complete review and local gates; merge the exact tested changes to `main`.
2. Wait for the successful push-to-main CI run and its signed wheel, sdist and
   SBOM. Download its candidate bundle and preserve those bytes unchanged.
3. Using that wheel, build the native plugin stage, capture the three-fresh-HOME
   Codex canary, generate the integration lock, and run `verify-phase-7`.
   The complete non-host regression has a one-hour execution budget, including
   the actual installed CLI regressions; every test and strict gate still runs.
   The six native Codex dispatches explicitly select `gpt-6.1-sol/high` and use
   existing platform authentication. They have no automatic retries.
   Native safety records must match the current upstream test tree and retain
   the complete original runtime/flags/inventory/network trace, not only a
   collected PASS summary. When local privileged namespaces are unavailable,
   use the explicit `ci.yml` input `release_native_qualification=true` on the
   exact reviewed source ref. Admit only successful upstream, ASan/UBSan and
   TSan artifacts whose live GitHub source/run IDs and raw digests match.
4. Create a qualified candidate bundle containing the original CI build
   evidence and subjects plus the actual Phase 7 stage/lock/canary evidence.
   Use `scripts/phase7-release-evidence export` to retain the full actual
   verifier root and pinned prior-phase graph, then add the unchanged stage,
   lock, canary and its transitive files to that qualification root. The
   consumer revalidates every command result and stream hash and reconstructs
   the complete Phase 7 aggregate from the reviewed producer's validators.
   `check-release-candidate --technical-only` must pass. This mode establishes
   technical readiness and cannot authorize publication.
5. Create a **draft** `v0.2.0` release with `--target` set to the exact main
   commit SHA. Upload `arw-qualified-candidate-v0.2.0.tar.gz`. The draft asset
   is temporary transfer storage, not the published deliverable.
6. The repository owner dispatches `release-authority.yml` on `main` with the
   exact CI run, artifact name, tag, and an explicit true use/distribution
   declaration. The workflow verifies CI attestations and technical gates,
   then signs the declaration with GitHub Actions OIDC. Repository visibility
   or a historical `PASS` does not establish permission.
7. Dispatch `release.yml` using the same exact candidate identity. It verifies
   the independent signature and live GitHub actor/run/artifact/draft IDs,
   validates the actual Phase 7 installation qualification evidence,
   uploads only verified publication subjects,
   removes only the bound intermediate asset, and publishes the draft.
8. Confirm the published tag commit and final wheel/sdist/SBOM digests.

Preserved historical qualification/legal receipts remain unchanged. A new
signed authority supplies the accountable declaration for this exact release;
it does not retroactively clear old blocked receipts. Commercial permission
without independently supported grants remains blocked.

Preparation replaced incomplete local raw license evidence with a real fresh
native audit. All 17 raw files matched their new receipt, and all three native
commands passed. The old receipt remains byte-identical in
`supply-chain/historical/pre-vendor/`; readers preserve explicit old/new
compatibility while new stage production requires the fresh receipt.
