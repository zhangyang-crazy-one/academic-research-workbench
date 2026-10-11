## 1. Configuration and evidence

- [x] 1.1 Add strict named harness configuration, assignment/role selectors, safe runtime credential loading and documentation examples.
- [x] 1.2 Add platform-neutral identity v2 and schema/decoder support while preserving v1 canonical receipts and panel replay.

## 2. Execution and admission

- [x] 2.1 Implement bounded command-driver execution with real task namespace isolation and cancellation.
- [x] 2.2 Implement stateless Responses/Chat Completions API workers with no model tools, no redirects, bounded output and secret-free receipts.
- [x] 2.3 Expose configured harness selection through orchestration-dispatch and application registry; preserve the existing exact Codex route and parent result acceptance.

## 3. Verification and delivery

- [x] 3.1 Verify actual local command and loopback HTTP dispatch through parent acceptance, cancellation, oversize/error/credential/path/identity failures and mixed harness selection.
- [x] 3.2 Run schema checks and legacy orchestration/identity/provenance regressions; document tested versus live-unqualified platforms.
- [ ] 3.3 Submit and merge the reviewed harness PR after CI, then regenerate the final v0.2.0 candidate and formal release evidence.
