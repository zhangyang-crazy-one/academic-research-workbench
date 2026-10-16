# v0.2.1 stability release preparation

Status: preparation only. A version change or passing pull-request CI does not
authorize publication.

Release tracking:
[#164](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/164).

The existing `v0.2.0` tag and draft identify commit
`1166d28e3ebd7e95f7e808c8b434fa325dcfe768`. Preserve that tag and its historical
candidate. Use a new `v0.2.1` tag for the exact reviewed release commit after the
following gates pass; do not publish the old draft as the updated code.

## Included stability changes

| PR | Change | Scope |
| --- | --- | --- |
| [#156](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/156) | ScanCode startup and Pluggy compatibility | Excludes the reproduced incompatible Pluggy 1.7.0 release; scanning and legal gates remain mandatory. |
| [#148](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/148) | Claim-only advisory review | Revalidates manuscript digests and occurrences after source modification or deletion. |
| [#149](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/149) | Initialization recovery | Publishes complete, fsynced receipts atomically; retained incomplete staging files cannot become canonical receipts. |
| [#154](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/154) | Integrity hashing memory | Reads payloads in 1 MiB chunks while retaining independent verification and existing digest semantics. |
| [#161](https://github.com/zhangyang-crazy-one/academic-research-workbench/pull/161) | Qualification discovery regressions | Adds ten tests; does not change production discovery or supply live qualification evidence. |

These changes are merged on `main` at
`c0b1ef147d6eaa724930912448af252418bfee8d`. Release metadata preparation is a
subsequent change and needs owner review before merge. Its optional IntegrationLock
reader and schema accept 0.2.1 alongside retained 0.1.0/0.2.0 identities, while
rejecting mixed package, plugin and wheel versions. The eventual candidate
must identify the resulting main commit, not this intermediate source.

The broader startup optimization in
[#150](https://github.com/zhangyang-crazy-one/academic-research-workbench/issues/150)
remains open: redundant-read reduction, mutation-safe reuse and complete
installed-command startup/process-tree measurements are not part of this fix.
The hashing benchmark measures its documented retained-stage verifier workload;
it does not establish an end-to-end CLI startup improvement.

PR #144 is a separate research pilot and is not included in this preparation.
Figure-role routing, figure composition, visual benchmarks and mechanism
components (#157, #158, #159 and draft #163) remain deferred. Their passing
subsets do not qualify those capabilities for this release.

For the cumulative capabilities planned since v0.1.0, see the
[v0.2.0 feature notes](release-v0.2.0.md). Those historical notes and receipts do
not establish eligibility of a new candidate.

## Candidate and publication gates

1. Review and merge the v0.2.1 metadata PR. Wait for successful **push-to-main**
   CI at the resulting source commit, including `Attest validated main
   candidate`. PR checks or a workflow-dispatch run do not substitute for that
   source-bound CI attestation.
2. Download the exact `academic-research-workbench-ci-<source-commit>` artifact
   from that run. Extract and verify it with `scripts/candidate-bundle`.
   Verify the wheel, sdist and SBOM attestations against the exact source commit
   and `.github/workflows/ci.yml`; preserve the original bytes.
3. Run `scripts/prepare-qualified-stage` with that candidate wheel,
   `build-evidence.json`, candidate evidence directory and **fresh** stage and
   evidence output directories. Use the default portable installed-core path.
   Retain the actual installation, core integrity, bounded artifact inspection,
   initialization, status and journal replay command results. Qualification of
   an earlier wheel, stage, source commit or version cannot be reused.
4. Create a qualified bundle with `scripts/candidate-bundle create
   --qualification-root <fresh-evidence-root>/qualification`, preserving the
   original CI subjects. Verify its archive round trip and run
   `scripts/check-release-candidate --technical-only` against the exact source
   commit. Technical readiness is separate from permission to distribute.
5. After technical verification and explicit owner release approval, create a
   new `v0.2.1` tag and draft at the exact candidate source commit. Upload the
   qualified transfer as `arw-qualified-candidate-v0.2.1.tar.gz`.
6. The repository owner supplies the actual intended use and distribution class
   through `release-authority.yml` on `main`, bound to that tag, CI run and
   artifact name. The current workflow supports
   `intended_use=noncommercial-academic-research` and the actual `public` or
   `private` distribution class. Do not infer permission from repository
   visibility or copy an earlier declaration. An unsupported use needs its own
   permission evidence before publication.
7. Only after owner authorization and its independent signature verify, dispatch
   `release.yml` with the same exact candidate identity. Verify the published
   tag commit and wheel/sdist/SBOM digests after publication.

Portable qualification requires no named harness, exact harness version, model,
model credential, integration lock or paid model call. Observed versions remain
evidence metadata. Optional platform-specific qualification is a separate
deployment diagnostic; it must not become a blanket release requirement.

No tag creation, release-authority dispatch or publication is performed by this
metadata preparation. The final CI identity, signed subjects, fresh portable
qualification and owner declaration remain outstanding until actually produced.
