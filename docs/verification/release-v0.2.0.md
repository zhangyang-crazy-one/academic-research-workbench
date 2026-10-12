# v0.2.0 release procedure and notes

v0.2.0 adds authenticated, revision-bound claim graphs and exact numeric
derivations, with deterministic single-panel result plots. Authorization
confirmation is anchored to the parent ledger's `occurred_at`. Proof checking
remains independent of canonical parent replay; graph and hard-caption
consumers verify evidence at their own boundaries.

Project-bound research startup now shares the core stable identity with the
legacy memory alias and persists exact initialization requests for interruption
recovery. External versioned direction packages delegate original ARS profile
and branch validation, AcceptedRef, citation and numeric replay; intake keeps
source versions, carriers and declared reading separate from scientific support.
The two replaceable examples and offline walkthrough retain negative and missing
results without model calls or automatic author adoption. See the
[research direction contract](../runtime/research-direction-workflow.md).

Named execution harnesses now support assignment/role/default routing to existing
qualified Codex hosts, external command drivers, or configured Responses/Chat
Completions APIs. Platform-neutral v2 identities bind retained local execution
observations while original Codex v1 receipts remain readable. Local command and
loopback HTTP regression evidence does not qualify live third-party models.
See [the harness contract](../runtime/execution-harnesses.md).

Trusted experiment checks require typed canonical acceptance, contract/provenance
acceptance before the receipt, and original evaluator replay of retained raw data.
Ordinary JSON evidence cannot promote a self-reported check status. Host namespace
qualification also normalizes hidden intermediate launcher aliases without
mounting host HOME; network-free alias probes are separate from model canaries.

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
3. Build the allowlisted plugin stage from that wheel and run the default
   `scripts/prepare-qualified-stage` path. It produces portable installed-core
   qualification under the selected evidence root's `qualification/` directory.
   This path checks package installation, core integrity, bounded artifact
   inspection, canonical initialization, status and journal replay. It requires
   no named harness, model, model credentials, integration lock, exact host
   version, paid invocation or minimum number of fresh model sessions. Tool and
   dependency versions are retained as observed metadata. Declared runtime
   compatibility remains in package metadata; release eligibility follows actual
   installation and behavior rather than equality to a previously observed host.
   Python dependencies resolve from declared ranges in a private package profile;
   subsequent core probes run offline. Source pins and native build/safety records
   remain provenance of the shipped code, not a whitelist of execution platforms.
4. Create the qualified bundle from unchanged CI subjects and evidence, using
   `scripts/candidate-bundle create --qualification-root <qualification-dir>`.
   The portable consumer verifies actual command results and stream digests,
   the exact installed stage, original wheel and original build evidence.
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
   validates the portable installed-core qualification evidence,
   uploads only verified publication subjects,
   removes only the bound intermediate asset, and publishes the draft.
8. Confirm the published tag commit and final wheel/sdist/SBOM digests.

Specific deployment platforms can additionally use the native host qualifiers,
including `qualify-codex-host` and the historical `verify-phase-7` path. Selecting
an explicit legacy host-canary/launcher/native/lock tuple in preparation invokes
that optional diagnostic. Those checks do not define the default formal release
requirements. Pi, Claude, command drivers, API integrations and future harnesses
retain their own models and authentication; release policy contains no platform
or model brand whitelist. Updating a host does not force a package-release model
rerun. Live platform evidence describes only the deployment actually observed.

Preserved historical qualification/legal receipts remain unchanged. A new
signed authority supplies the accountable declaration for this exact release;
it does not retroactively clear old blocked receipts. Commercial permission
without independently supported grants remains blocked.

Preparation replaced incomplete local raw license evidence with a real fresh
native audit. All 17 raw files matched their new receipt, and all three native
commands passed. The old receipt remains byte-identical in
`supply-chain/historical/pre-vendor/`; readers preserve explicit old/new
compatibility while new stage production requires the fresh receipt.
