## 1. Portable qualification

- [x] 1.1 Implement a host-independent installed-core probe and actual command receipts.
- [x] 1.2 Make portable preparation the default and retain explicit legacy diagnostics.

## 2. Release transfer

- [x] 2.1 Accept and independently validate portable evidence in bundle and formal gates.
- [x] 2.2 Replace mandatory harness/version instructions with the owner's permissive policy.

## 3. Verification and delivery

- [x] 3.1 Verify real installed lifecycle behavior, absent harnesses, mutations, unsafe paths and legacy readers.
- [x] 3.3 Bind executable bits and verify permission mutation rejection at qualification, bundle creation and technical release checks.
- [x] 3.4 Preserve the selected supported interpreter in the credential-isolated probe and verify an older-only PATH.
- [ ] 3.2 Use fresh successful main CI subjects, portable qualification and owner authority for publication; the historical v0.2.0 tag is superseded by the planned v0.2.1 candidate, without moving the old tag.

## 4. Bounded integrity hashing (#150)

- [x] 4.1 Stream build-identity, core and integration-lock hashes with unchanged digests and fail-closed behavior; verify empty/boundary/large inputs, bounded allocation, I/O failure, replacement, symlinks and fresh processes.

- [x] 4.2 Harden PR171 invocation-local digest reuse with live descriptor/change identity, rejection on drift and end verification; preserve internal build-to-audit sharing while removing public caller-cache trust. Verify real filesystem mutations, FIFO/open races, read errors, fallback, independent public calls and bounded allocation.
- [ ] 4.3 Measure installed `version`, `route` and memory/files MCP startup A/B wall time, process-tree RSS/PSS and idle/exit behavior before claiming #150 complete.

Cross-process preflight deduplication remains separate follow-up scope. Existing PR171 launcher startup behavior is retained; these tests establish no installed performance result.

## 5. v0.2.1 release identity (#164)

- [x] 5.1 Align package, plugin, launcher and release metadata; preserve old IntegrationLock readers and verify current identity consistency and mismatch rejection.
- [ ] 5.2 Review the metadata PR, then generate signed main CI subjects and fresh portable installed-core qualification for the final release commit.
- [ ] 5.3 Obtain the actual owner use/distribution declaration and independently verify publication authority before publishing the new tag.
