## Context

Current candidate bundles carry technical inventories and historical unknown use/approval records. Repository visibility and locally rewritten PASS values do not establish accountable authority. The candidate CI signs only successful push-to-main wheel/sdist/SBOM subjects. Actual host qualification requires a locally observed Codex tuple and cannot be synthesized in a generic Actions runner.

## Goals / Non-Goals

Goals: preserve all existing technical gates, consume exact main CI subjects, retain genuine Phase 7 evidence, bind an explicit owner declaration to independently verified GitHub identity, publish only verified subjects.

Non-goals: infer intended use, qualify missing commercial grants, rewrite historical evidence, introduce model API credentials, or manufacture host receipts.

## Decisions

- A dedicated `release-authority.yml` workflow runs only on main workflow_dispatch. Live GitHub API owner/triggering actor IDs, workflow path, main SHA, original attempt and successful candidate run are checked. GitHub-hosted OIDC signs a custom strict predicate; `gh attestation verify` establishes cryptographic identity before additional policy validation.
- Original candidate wheel/sdist/build evidence/SBOM are preserved byte-for-byte. The qualified archive adds exact actual Phase 7 stage, lock, canary and referenced evidence. One draft release targeted to the full main SHA transports this archive. The predicate binds release ID, asset ID/name/digest as well as CI run/artifact ID/name/digest and bundle subject digests.
- Existing pinned licenses and notices form the supported permission basis only for an explicit noncommercial academic declaration. Unknown or unsupported declarations fail closed. Privacy alone is never permission.
- `--technical-only` is restricted in purpose to preparation before signing; publication always runs the ordinary gate with independent authority verification. Draft publication uploads the precise subjects, accepts only identical retry uploads, removes only the bound intermediate asset ID, and publishes the same draft ID.
- Historical legal BLOCKED records remain unchanged. Current release authority is a separate signed record.
- Strict Phase 7 subprocesses receive only enumerated candidate and stage path inputs in addition to the existing positive environment. Credentials remain excluded. Fresh-home native Codex exec calls explicitly use gpt-6.1-sol/high with existing authentication and no retries.

## Risks / Trade-offs

The trust root is the repository owner's authenticated GitHub dispatch and the GitHub-hosted workflow at the exact source SHA. This supports the current personal repository, not organization delegation. A changed candidate, replaced asset or rerun requires new authorization. An interrupted publication after intermediate deletion requires restoring the asset and signing its new ID before proceeding.

## Migration Plan

Implement and verify policy and workflows in the reviewed PR, merge after CI, build the actual main candidate, regenerate qualification from that wheel, sign the true user declaration, then publish v0.2.0. Preserve all previous evidence and refuse release when any step fails.
